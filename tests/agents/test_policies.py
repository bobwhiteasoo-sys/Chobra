import pytest

from chobra_agents.policies import ScriptedAgent
from chobra_agents.profiles import PROFILES
from chobra_audit.catalog import build_checks
from chobra_engine.runner import RunSession, RunSpec
from chobra_envs.rules_catalog import starting_rules
from chobra_envs.supportdesk import ACTION_CATALOG, SupportDesk

ACTORS = ["agent_01", "agent_02", "agent_03"]


def run(rule_key, mode, seed=101, **overrides):
    env = SupportDesk()
    config = env.default_config()
    config.update(overrides)
    rules = starting_rules("supportdesk")
    rule = rules[rule_key]["tree"]
    agents = [ScriptedAgent(actor, env, rule, PROFILES[mode], seed) for actor in ACTORS]
    spec = RunSpec(run_id=f"run-{rule_key}-{mode}-{seed}", env=env, config=config, rule=rule, rule_version_id=rule_key, seed=seed,
                   agents=agents, checks=build_checks("supportdesk", config), rule_meta=rules[rule_key], agent_mode=mode)
    session = RunSession(spec)
    session.initialize()
    while not session.finished:
        session.step()
    return session


def status(session, check_id):
    return {r["check_id"]: r["status"] for r in session.audit["checks"]}[check_id]


def metric_value(session, key):
    return session.audit["metrics"][key]


def test_paying_closures_makes_reward_seekers_close_unsolved_issues():
    session = run("SD-P1", "incentive_seeking")
    assert session.status == "completed"
    assert status(session, "false_closure_v1") == "fail"
    assert status(session, "rewarded_rejected_resolution_v1") == "fail"
    assert session.audit["verdict"] == "observed_violation"


def test_paying_confirmed_solutions_removes_false_closures_for_reward_seekers():
    p1 = run("SD-P1", "incentive_seeking")
    p2 = run("SD-P2", "incentive_seeking")
    assert status(p2, "false_closure_v1") in ("pass", "not_applicable")
    assert status(p2, "duplicate_root_reward_v1") in ("pass", "not_applicable")
    assert metric_value(p2, "resolved_rate")["numerator"] > metric_value(p1, "resolved_rate")["numerator"]


def test_equal_pay_per_problem_makes_reward_seekers_prefer_easy_problems():
    p2 = run("SD-P2", "incentive_seeking")
    easy = metric_value(p2, "easy_coverage")
    hard = metric_value(p2, "hard_coverage")
    assert easy["applicability"] == hard["applicability"] == "applicable"
    assert easy["numerator"] * hard["denominator"] >= hard["numerator"] * easy["denominator"]


@pytest.mark.parametrize("rule_key", ["SD-P1", "SD-P2", "SD-P3"])
def test_cooperative_agents_never_close_unsolved(rule_key):
    session = run(rule_key, "cooperative")
    assert status(session, "false_closure_v1") in ("pass", "not_applicable")


def test_adversarial_search_finds_a_loophole_under_paid_closures():
    session = run("SD-P1", "adversarial_search")
    failed = {r["check_id"] for r in session.audit["checks"] if r["status"] == "fail"}
    assert failed & {"false_closure_v1", "split_anomaly_v1", "duplicate_root_reward_v1", "unsolved_paid_v1"}


def test_scripted_runs_are_deterministic():
    a = run("SD-P3", "incentive_seeking", seed=7)
    b = run("SD-P3", "incentive_seeking", seed=7)
    assert a.log.last_hash == b.log.last_hash


def test_scripted_agents_only_use_catalog_actions():
    session = run("SD-P1", "adversarial_search", allow_report_complexity=True, allow_reopen=True)
    proposed = {e.payload["action_type"] for e in session.log.events if e.type == "action.proposed"}
    assert proposed <= set(ACTION_CATALOG)


def test_all_modes_complete_with_invariants_intact():
    for mode in PROFILES:
        for key in ("SD-P1", "SD-P2", "SD-P3"):
            session = run(key, mode, seed=11)
            assert session.status == "completed", (mode, key, session.stop_reason)
