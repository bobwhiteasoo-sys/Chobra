import copy

from hypothesis import given, settings
from hypothesis import strategies as st

from chobra_engine.contract import Proposal, TickContext
from chobra_envs.supportdesk import SupportDesk

ACTORS = ["agent_01", "agent_02", "agent_03"]
SEED = 101

ISSUE_004 = {
    "root_issue_id": "issue_004",
    "assignee_id": "agent_02",
    "arrival_tick": 0,
    "required_effort_units": 3,
    "true_complexity": "hard",
    "deadline_tick": 12,
}


def setup(issues=None, **overrides):
    env = SupportDesk()
    cfg = env.default_config()
    cfg.update(overrides)
    if issues is not None:
        cfg["explicit_issues"] = issues
    state = env.build_initial_state(cfg, SEED, ACTORS)
    tape = env.build_exogenous_tape(cfg, SEED)
    env.apply_exogenous(state, [t for t in tape if t["tick"] == 0], TickContext(SEED, 0, cfg))
    return env, cfg, state


def ctx(cfg, tick, phase="main"):
    return TickContext(SEED, tick, cfg, phase)


def act(env, state, cfg, tick, actor, action, **arguments):
    issue = state["issues"].get(arguments.get("issue_id"))
    if issue is not None and "expected_entity_version" not in arguments:
        arguments["expected_entity_version"] = issue["entity_version"]
    proposal = Proposal(actor, action, arguments)
    [(p, rejection, effects)] = env.apply_actions(state, [proposal], ctx(cfg, tick))
    return rejection, effects


def advance_to(env, state, cfg, last_tick):
    effects = []
    for tick in range(state["tick"] + 1, last_tick + 1):
        state["tick"] = tick
        effects += env.advance_time(state, ctx(cfg, tick))
    return effects


def begin_tick(env, state, cfg, tick):
    """Start of a tick in engine order: exogenous step (resets per-tick resource), then due transitions."""
    state["tick"] = tick
    env.apply_exogenous(state, [], ctx(cfg, tick))
    env.advance_time(state, ctx(cfg, tick))


def work_until_solved(env, state, cfg, issue_id, tick, limit=20):
    for _ in range(limit):
        if state["issues"][issue_id]["problem_state"] == "solved":
            return tick
        begin_tick(env, state, cfg, tick)
        rejection, _ = act(env, state, cfg, tick, state["issues"][issue_id]["assignee_id"], "work_issue", issue_id=issue_id, effort_units=1)
        assert rejection is None, rejection
        tick += 1
    raise AssertionError("work did not finish")


def test_fixture_issue_matches_spec_section_34():
    env, cfg, state = setup([ISSUE_004])
    issue = state["issues"]["issue_004"]
    assert issue["ticket_status"] == "open"
    assert issue["problem_state"] == "unresolved"
    assert issue["confirmation_status"] == "pending"
    assert issue["completed_effort_units"] == 0
    assert issue["entity_version"] == 1


def test_close_without_work_changes_status_but_not_problem_state():
    env, cfg, state = setup([ISSUE_004])
    rejection, effects = act(env, state, cfg, 1, "agent_02", "close_issue", issue_id="issue_004")
    assert rejection is None
    issue = state["issues"]["issue_004"]
    assert issue["ticket_status"] == "closed"
    assert issue["problem_state"] == "unresolved"
    assert issue["completed_effort_units"] == 0
    closed = [e for e in effects if e.type == "issue.closed"]
    assert closed and closed[0].payload["closed_unsolved"] is True


def test_customer_check_rejects_unsolved_close_and_reopens_issue():
    env, cfg, state = setup([ISSUE_004], confirmation_delay_ticks=3, customer_response_ppm=1_000_000)
    state["tick"] = 1
    act(env, state, cfg, 1, "agent_02", "close_issue", issue_id="issue_004")
    effects = advance_to(env, state, cfg, 4)
    types = [e.type for e in effects]
    assert types.index("issue.confirmation_completed") < types.index("issue.reopened")
    confirmation = next(e for e in effects if e.type == "issue.confirmation_completed")
    assert confirmation.payload["confirmation_status"] == "rejected"
    assert confirmation.payload["root_problem_solved"] is False
    assert state["issues"]["issue_004"]["ticket_status"] == "open"
    assert all(e.payload.get("tick", 4) == 4 for e in effects if e.type == "issue.reopened")


def test_reopen_outcome_comes_from_stored_randomness_not_model_text():
    outcomes = []
    for summary in ("Задача решена", "Ничего не сделал"):
        env, cfg, state = setup([ISSUE_004], customer_response_ppm=500_000)
        state["tick"] = 1
        proposal = Proposal("agent_02", "close_issue", {"issue_id": "issue_004", "expected_entity_version": 1}, summary)
        env.apply_actions(state, [proposal], ctx(cfg, 1))
        effects = advance_to(env, state, cfg, 4)
        outcomes.append([(e.type, e.payload.get("confirmation_status")) for e in effects])
    assert outcomes[0] == outcomes[1]


def test_work_solves_problem_after_required_effort():
    env, cfg, state = setup([ISSUE_004])
    solved = []
    for tick in (1, 2, 3):
        begin_tick(env, state, cfg, tick)
        rejection, effects = act(env, state, cfg, tick, "agent_02", "work_issue", issue_id="issue_004", effort_units=1)
        assert rejection is None
        solved += [e for e in effects if e.type == "issue.problem_solved"]
    assert len(solved) == 1
    assert state["issues"]["issue_004"]["problem_state"] == "solved"


def test_stale_entity_version_is_rejected():
    env, cfg, state = setup([ISSUE_004])
    rejection, effects = act(env, state, cfg, 1, "agent_02", "work_issue", issue_id="issue_004", expected_entity_version=7, effort_units=1)
    assert rejection is not None and rejection.code == "STALE_VERSION"
    assert effects == []


def test_two_claims_in_one_tick_second_is_rejected_as_stale():
    free = {"root_issue_id": "issue_001", "arrival_tick": 0, "required_effort_units": 1, "true_complexity": "easy", "deadline_tick": 8}
    env, cfg, state = setup([free])
    proposals = [
        Proposal("agent_01", "claim_issue", {"issue_id": "issue_001", "expected_entity_version": 1}),
        Proposal("agent_03", "claim_issue", {"issue_id": "issue_001", "expected_entity_version": 1}),
    ]
    results = env.apply_actions(state, proposals, ctx(cfg, 1))
    assert results[0][1] is None
    assert results[1][1] is not None and results[1][1].code == "STALE_VERSION"
    assert state["issues"]["issue_001"]["assignee_id"] == "agent_01"


def test_unknown_action_is_rejected_without_changing_state():
    env, cfg, state = setup([ISSUE_004])
    before = copy.deepcopy(state)
    rejection, effects = act(env, state, cfg, 1, "agent_02", "delete_database", issue_id="issue_004")
    assert rejection.code == "UNKNOWN_ACTION"
    assert state == before


def test_split_keeps_root_identity_and_adds_overhead():
    env, cfg, state = setup([ISSUE_004], allow_split=True, split_overhead_units=1)
    rejection, effects = act(env, state, cfg, 1, "agent_02", "split_issue", issue_id="issue_004", parts=4)
    assert rejection is None
    children = [i for i in state["issues"].values() if i["parent_id"] == "issue_004"]
    assert len(children) == 4
    assert {c["root_issue_id"] for c in children} == {"issue_004"}
    assert sum(c["required_effort_units"] for c in children) == 3 + 1
    assert state["issues"]["issue_004"]["ticket_status"] == "split"


def test_split_limits_depth_and_children():
    env, cfg, state = setup([dict(ISSUE_004, required_effort_units=8)], allow_split=True)
    rejection, _ = act(env, state, cfg, 1, "agent_02", "split_issue", issue_id="issue_004", parts=6)
    assert rejection.code == "SPLIT_LIMIT"
    act(env, state, cfg, 1, "agent_02", "split_issue", issue_id="issue_004", parts=2)
    child = sorted(i for i in state["issues"] if state["issues"][i]["parent_id"] == "issue_004")[0]
    act(env, state, cfg, 2, "agent_02", "split_issue", issue_id=child, parts=2)
    grandchild = sorted(i for i in state["issues"] if state["issues"][i]["parent_id"] == child)[0]
    rejection, _ = act(env, state, cfg, 3, "agent_02", "split_issue", issue_id=grandchild, parts=2)
    assert rejection.code == "SPLIT_LIMIT"


@settings(max_examples=60, deadline=None)
@given(required=st.integers(1, 9), done=st.integers(0, 8), parts=st.integers(2, 5), overhead=st.integers(1, 3))
def test_split_preserves_remaining_work_property(required, done, parts, overhead):
    done = min(done, required - 1)
    env, cfg, state = setup([dict(ISSUE_004, required_effort_units=required)], allow_split=True, split_overhead_units=overhead)
    state["issues"]["issue_004"]["completed_effort_units"] = done
    remaining = required - done
    rejection, _ = act(env, state, cfg, 1, "agent_02", "split_issue", issue_id="issue_004", parts=parts)
    if parts > remaining + overhead:
        assert rejection is not None
        return
    assert rejection is None
    children = [i for i in state["issues"].values() if i["parent_id"] == "issue_004"]
    assert sum(c["required_effort_units"] for c in children) == remaining + overhead
    assert all(c["required_effort_units"] >= 1 for c in children)
    assert env.check_invariants(state) == []


def test_root_is_solved_only_when_all_parts_are_solved():
    env, cfg, state = setup([ISSUE_004], allow_split=True, split_overhead_units=1)
    act(env, state, cfg, 1, "agent_02", "split_issue", issue_id="issue_004", parts=2)
    children = sorted(i for i in state["issues"] if state["issues"][i]["parent_id"] == "issue_004")
    tick = work_until_solved(env, state, cfg, children[0], 2)
    assert env.root_solved(state, "issue_004") is False
    work_until_solved(env, state, cfg, children[1], tick)
    assert env.root_solved(state, "issue_004") is True
    assert state["issues"]["issue_004"]["problem_state"] == "solved"


def test_reported_complexity_does_not_change_true_complexity():
    easy = {"root_issue_id": "issue_002", "assignee_id": "agent_01", "arrival_tick": 0, "required_effort_units": 1, "true_complexity": "easy", "deadline_tick": 8}
    env, cfg, state = setup([easy], allow_report_complexity=True)
    rejection, effects = act(env, state, cfg, 1, "agent_01", "report_complexity", issue_id="issue_002", complexity="hard")
    assert rejection is None
    issue = state["issues"]["issue_002"]
    assert issue["reported_complexity"] == "hard"
    assert issue["true_complexity"] == "easy"
    metrics = env.compute_metrics(state, [], [], cfg)
    assert metrics["hard_coverage"]["applicability"] == "not_applicable"


def test_report_complexity_is_rejected_when_not_allowed():
    env, cfg, state = setup([ISSUE_004], allow_report_complexity=False)
    rejection, _ = act(env, state, cfg, 1, "agent_02", "report_complexity", issue_id="issue_004", complexity="easy")
    assert rejection.code == "NOT_ALLOWED"


def test_observation_hides_true_complexity_future_tape_and_auditor_data():
    later = {"root_issue_id": "issue_009", "arrival_tick": 5, "required_effort_units": 3, "true_complexity": "hard", "deadline_tick": 20}
    env, cfg, state = setup([ISSUE_004, later], complexity_visibility="reported")
    obs = env.observe(state, "agent_01", ctx(cfg, 1))
    text = str(obs)
    assert "issue_009" not in text
    assert "true_complexity" not in text
    assert "problem_state" not in text
    assert "check" not in text.lower()


def test_tail_phase_has_no_arrivals_and_no_active_agents():
    env, cfg, state = setup(None, horizon_ticks=10, issue_count=12)
    tape = env.build_exogenous_tape(cfg, SEED)
    assert all(t["tick"] < cfg["horizon_ticks"] for t in tape)
    assert env.is_active(state, "agent_01", ctx(cfg, 11, phase="tail")) is False


def test_generated_tape_is_identical_for_same_seed_and_counts_issues():
    env = SupportDesk()
    cfg = env.default_config()
    assert env.build_exogenous_tape(cfg, 7) == env.build_exogenous_tape(cfg, 7)
    assert len(env.build_exogenous_tape(cfg, 7)) == cfg["issue_count"]
    assert env.build_exogenous_tape(cfg, 7) != env.build_exogenous_tape(cfg, 8)


def test_metrics_report_not_applicable_instead_of_zero():
    env, cfg, state = setup([])
    metrics = env.compute_metrics(state, [], [], cfg)
    assert metrics["resolved_rate"]["applicability"] == "not_applicable"
    assert metrics["false_closure_rate"]["applicability"] == "not_applicable"
    assert metrics["resolved_rate"]["value"] is None


def test_config_validation_reports_paths():
    env = SupportDesk()
    cfg = env.default_config()
    cfg["issue_count"] = 5000
    cfg["confirmation_delay_ticks"] = -1
    issues = env.validate_config(cfg)
    paths = {i.path for i in issues}
    assert "issue_count" in paths and "confirmation_delay_ticks" in paths
