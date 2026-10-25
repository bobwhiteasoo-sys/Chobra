import pytest

from chobra_agents.policies import ScriptedAgent
from chobra_agents.profiles import PROFILES
from chobra_audit.catalog import build_checks
from chobra_engine.rules import compute_examples, validate_rule
from chobra_engine.runner import RunSession, RunSpec
from chobra_envs.registry import ENVIRONMENTS, TEMPLATES, get_environment
from chobra_envs.rules_catalog import starting_rules

ACTORS = ["agent_01", "agent_02", "agent_03"]


def run(env_name, rule_key, mode, seed=21, **overrides):
    env = get_environment(env_name)
    config = env.default_config()
    config.update(overrides)
    rules = starting_rules(env_name)
    rule = rules[rule_key]["tree"]
    agents = [ScriptedAgent(a, env, rule, PROFILES[mode], seed) for a in ACTORS]
    spec = RunSpec(run_id=f"{env_name}-{rule_key}-{mode}", env=env, config=config, rule=rule, rule_version_id=rule_key, seed=seed,
                   agents=agents, checks=build_checks(env_name, config, TEMPLATES[env_name]["default_checks"]), rule_meta=rules[rule_key])
    session = RunSession(spec)
    session.initialize()
    while not session.finished:
        session.step()
    return session


def statuses(session):
    return {r["check_id"]: r["status"] for r in session.audit["checks"]}


@pytest.mark.parametrize("env_name", sorted(ENVIRONMENTS))
def test_each_template_gives_a_valid_scenario_and_valid_rules(env_name):
    env = get_environment(env_name)
    assert env.validate_config(env.default_config()) == []
    rules = starting_rules(env_name)
    assert sorted(rules) == sorted(TEMPLATES[env_name]["rules"])
    for key, rule in rules.items():
        result = validate_rule(rule["tree"], env)
        assert result.errors == [], (key, [e.to_dict() for e in result.errors])
        examples = compute_examples(rule["tree"], env)
        assert len(examples) >= 3, key


@pytest.mark.parametrize("env_name", sorted(ENVIRONMENTS))
@pytest.mark.parametrize("mode", sorted(PROFILES))
def test_scripted_runs_complete_with_invariants(env_name, mode):
    for rule_key in TEMPLATES[env_name]["rules"]:
        session = run(env_name, rule_key, mode)
        assert session.status == "completed", (rule_key, session.stop_reason)
        assert session.log.verify_chain()


def test_paying_for_extraction_depletes_the_commons_for_reward_seekers():
    assert statuses(run("resourcecommons", "RC-P1", "incentive_seeking"))["rc_depletion_v1"] == "fail"


def test_minimum_stock_condition_keeps_the_commons_for_reward_seekers():
    result = statuses(run("resourcecommons", "RC-P3", "incentive_seeking"))
    assert result["rc_depletion_v1"] == "pass"


def test_paying_done_marks_rewards_marks_without_work():
    assert statuses(run("taskboard", "TB-P1", "incentive_seeking"))["tb_done_without_work_v1"] == "fail"
    assert statuses(run("taskboard", "TB-P2", "incentive_seeking"))["tb_done_without_work_v1"] in ("pass", "not_applicable")
