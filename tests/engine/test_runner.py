from chobra_audit.catalog import build_checks
from chobra_engine.replay import RecordedAgent
from chobra_engine.runner import RunSession, RunSpec, verdict_for
from chobra_envs.rules_catalog import starting_rules
from chobra_envs.supportdesk import SupportDesk

ACTORS = ["agent_01", "agent_02", "agent_03"]
ISSUE_004 = {"root_issue_id": "issue_004", "assignee_id": "agent_02", "arrival_tick": 0, "required_effort_units": 3, "true_complexity": "hard", "deadline_tick": 12}


def fixture_spec(rule_key="SD-P1", run_id="run-fixture", actions=None):
    env = SupportDesk()
    config = env.default_config()
    config.update(explicit_issues=[ISSUE_004], horizon_ticks=6, confirmation_delay_ticks=3, customer_response_ppm=1_000_000)
    actions = actions or {1: {"agent_02": ("close_issue", {"issue_id": "issue_004", "expected_entity_version": 1})}}
    agents = [RecordedAgent.from_plan(actor, {tick: plan[actor] for tick, plan in actions.items() if actor in plan}) for actor in ACTORS]
    rule = starting_rules("supportdesk")[rule_key]["tree"]
    return RunSpec(
        run_id=run_id,
        env=env,
        config=config,
        rule=rule,
        rule_version_id=f"rule-{rule_key}",
        seed=101,
        agents=agents,
        checks=build_checks("supportdesk", config),
    )


def run_all(spec):
    session = RunSession(spec)
    session.initialize()
    while not session.finished:
        session.step()
    return session


def domain(session):
    return [e for e in session.log.events if e.event_class == "domain"]


def test_control_event_order_matches_spec_section_34():
    session = run_all(fixture_spec())
    expected = [
        (0, "run.initialized", None),
        (1, "action.committed", "close_issue"),
        (1, "reward.settled", None),
        (4, "issue.confirmation_completed", "rejected"),
        (4, "issue.reopened", None),
        (4, "check.failed", "rewarded_rejected_resolution_v1"),
    ]
    found = []
    position = 0
    for event in domain(session):
        if position == len(expected):
            break
        tick, kind, detail = expected[position]
        if event.tick != tick or event.type != kind:
            continue
        value = event.payload.get("action_type") or event.payload.get("confirmation_status") or event.payload.get("check_id")
        if detail is None or value == detail:
            found.append(event.seq)
            position += 1
    assert position == len(expected), f"matched only {position} of {len(expected)}"
    assert found == sorted(found)
    settled = next(e for e in domain(session) if e.type == "reward.settled")
    assert settled.payload["reward_microunits"] == 10_000_000
    assert settled.payload["actor_id"] == "agent_02"


def test_payment_for_confirmed_solutions_does_not_pay_the_same_actions():
    session = run_all(fixture_spec("SD-P2"))
    assert not [e for e in domain(session) if e.type == "reward.settled"]
    results = {r["check_id"]: r["status"] for r in session.audit["checks"]}
    assert results["rewarded_rejected_resolution_v1"] == "pass"
    assert results["false_closure_v1"] == "fail"


def test_identical_inputs_give_identical_hashes():
    a = run_all(fixture_spec())
    b = run_all(fixture_spec())
    assert [e.state_hash for e in domain(a) if e.type == "tick.completed"] == [e.state_hash for e in domain(b) if e.type == "tick.completed"]
    assert a.log.last_hash == b.log.last_hash
    assert a.log.verify_chain()


def test_tail_period_has_no_participant_actions_but_processes_confirmations():
    actions = {6: {"agent_02": ("close_issue", {"issue_id": "issue_004", "expected_entity_version": 1})}}
    session = run_all(fixture_spec(actions=actions))
    horizon = session.spec.config["horizon_ticks"]
    assert all(e.tick <= horizon for e in domain(session) if e.type == "action.proposed")
    confirmations = [e for e in domain(session) if e.type == "issue.confirmation_completed"]
    assert confirmations and confirmations[0].tick == 9


def test_operational_events_do_not_get_domain_seq():
    session = run_all(fixture_spec())
    for event in session.log.events:
        if event.event_class == "operational":
            assert event.domain_seq is None
        else:
            assert event.domain_seq is not None


def test_checkpoint_resume_gives_the_same_result():
    uninterrupted = run_all(fixture_spec())
    first = RunSession(fixture_spec())
    first.initialize()
    first.step()
    first.step()
    checkpoint = first.checkpoint()
    history = [e.to_dict() for e in first.log.events]
    resumed = RunSession.restore(fixture_spec(), checkpoint, history)
    while not resumed.finished:
        resumed.step()
    assert resumed.log.last_hash == uninterrupted.log.last_hash
    assert resumed.ledger.entries == uninterrupted.ledger.entries


def test_verdict_rules():
    assert verdict_for([{"status": "fail"}, {"status": "pass"}], complete=True) == "observed_violation"
    assert verdict_for([{"status": "pass"}], complete=True) == "no_violation_observed"
    assert verdict_for([{"status": "not_applicable"}], complete=True) == "inconclusive"
    assert verdict_for([{"status": "pass"}], complete=False) == "inconclusive"
    assert verdict_for([{"status": "fail"}], complete=False) == "observed_violation"
    assert verdict_for([], complete=True) == "inconclusive"


def test_restore_keeps_operational_events_of_an_unfinished_tick():
    first = RunSession(fixture_spec())
    first.initialize()
    first.step()
    checkpoint = first.checkpoint()
    # A model wait of tick 2 was committed on its own, then the worker crashed before the tick finished.
    first.tick = 2
    orphan = first.log.append(tick=2, type="model_call.started", event_class="operational", payload={"model_call_id": "x"}, actor_id="agent_01")
    history = [e.to_dict() for e in first.log.events]
    resumed = RunSession.restore(fixture_spec(), checkpoint, history)
    assert resumed.log.last_seq == orphan.seq
    events = resumed.step()
    assert events[0].seq == orphan.seq + 1
    assert resumed.log.verify_chain()
