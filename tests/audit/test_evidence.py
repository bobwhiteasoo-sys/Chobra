import copy
import json

from chobra_agents.llm import FakeAdapter, ModelAgent, ModelConfig
from chobra_agents.budget import RunBudget
from chobra_agents.policies import ScriptedAgent
from chobra_agents.profiles import PROFILES
from chobra_audit.comparison import compare_runs, run_summary, wilson_interval
from chobra_audit.findings import build_findings
from chobra_audit.fixes import propose_fixes, check_fix_on_counterexample
from chobra_audit.minimize import minimize_counterexample
from chobra_audit.recipe import RunRecipe, execute
from chobra_audit.replay_verify import verify_replay
from chobra_envs.rules_catalog import starting_rules
from chobra_envs.registry import get_environment

ISSUE_004 = {"root_issue_id": "issue_004", "assignee_id": "agent_02", "arrival_tick": 0, "required_effort_units": 3, "true_complexity": "hard", "deadline_tick": 12}


def recipe(rule_key="SD-P1", seed=101, env_name="supportdesk", **config):
    env = get_environment(env_name)
    cfg = env.default_config()
    cfg.update(config)
    rules = starting_rules(env_name)
    return RunRecipe(run_id=f"run-{rule_key}-{seed}", environment=env_name, config=cfg, rule=rules[rule_key]["tree"], rule_version_id=rule_key,
                     rule_meta=rules[rule_key], seed=seed, actor_ids=["agent_01", "agent_02", "agent_03"], check_ids=None)


def scripted(rec, mode="incentive_seeking"):
    env = get_environment(rec.environment)
    return [ScriptedAgent(a, env, rec.rule, PROFILES[mode], rec.seed) for a in rec.actor_ids]


def run(rec, mode="incentive_seeking"):
    return execute(rec, scripted(rec, mode))


def events_of(session):
    return [e.to_dict() for e in session.log.events]


# --- replay -------------------------------------------------------------------------

def test_replay_reproduces_state_hashes_and_the_violation():
    rec = recipe()
    session = run(rec)
    finding = build_findings(rec, events_of(session), session.audit)[0]
    result = verify_replay(rec, events_of(session), check_id=finding["check_id"])
    assert result["status"] == "replay_verified"
    assert result["ticks_compared"] == session.tick + 1


def test_replay_detects_a_tampered_record():
    rec = recipe()
    session = run(rec)
    events = events_of(session)
    proposal = next(e for e in events if e["type"] == "action.proposed" and e["payload"]["action_type"] == "close_issue")
    proposal["payload"]["action_type"] = "wait"
    proposal["payload"]["arguments"] = {}
    result = verify_replay(rec, events, check_id="false_closure_v1")
    assert result["status"] == "replay_failed"
    assert result["first_divergent_tick"] is not None


def test_replay_never_calls_the_model():
    rec = recipe(horizon_ticks=4, issue_count=4)
    env = get_environment("supportdesk")
    answer = json.dumps({"action_type": "wait", "arguments_json": "{}", "decision_summary": "", "referenced_observation_ids": []})
    adapter = FakeAdapter([answer] * 20)
    agents = [ModelAgent(a, env, adapter, ModelConfig(), PROFILES["incentive_seeking"], RunBudget(max_calls=50), sleep=lambda s: None) for a in rec.actor_ids]
    session = execute(rec, agents)
    calls_before = len(adapter.requests)
    result = verify_replay(rec, events_of(session), check_id=None)
    assert result["status"] == "replay_verified"
    assert len(adapter.requests) == calls_before


# --- minimization ------------------------------------------------------------------

def test_minimized_counterexample_is_re_executed_and_still_fails():
    rec = recipe()
    session = run(rec)
    original = [e for e in events_of(session) if e["type"] == "action.committed" and e["payload"]["action_type"] != "wait"]
    result = minimize_counterexample(rec, events_of(session), check_id="false_closure_v1")
    assert result["status"] in ("minimal", "reduced")
    assert 0 < len(result["actions"]) < len(original)
    assert result["verified"] is True
    assert result["executions"] <= 200


def test_minimization_stopped_by_budget_is_not_called_minimal():
    rec = recipe()
    session = run(rec)
    result = minimize_counterexample(rec, events_of(session), check_id="false_closure_v1", max_executions=3)
    assert result["status"] == "reduced"
    assert result["label"] == "сокращенный контрпример"


# --- comparison --------------------------------------------------------------------

def test_wilson_interval_known_values():
    low, high = wilson_interval(0, 10)
    assert low == "0.0000" and high == "0.2775"
    low, high = wilson_interval(5, 10)
    assert (low, high) == ("0.2366", "0.7634")


def paired_runs(seeds, mode="incentive_seeking"):
    summaries = []
    for key in ("SD-P1", "SD-P2"):
        for seed in seeds:
            rec = recipe(key, seed)
            session = run(rec, mode)
            summaries.append(run_summary(rec, session, variant=key, mode=mode))
    return summaries


def test_comparison_with_few_pairs_shows_values_not_intervals():
    result = compare_runs(paired_runs([101, 102, 103]), baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    assert result["pairs_complete"] == 3
    assert result["pairing"]["tapes_match"] is True
    assert result["pairing"]["changed_factors"] == ["rule"]
    metric = result["metrics"]["resolved_rate"]
    assert metric["bootstrap_ci"] is None
    assert len(metric["pair_values"]) == 3 and metric["range"] is not None
    p1 = result["violations"]["SD-P1"]["false_closure_v1"]
    assert p1["applicable"] == 3 and p1["incomplete"] == 0 and p1["wilson"] is not None


def test_bootstrap_requires_ten_pairs_and_is_deterministic():
    runs = paired_runs(list(range(200, 210)))
    first = compare_runs(runs, baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    second = compare_runs(runs, baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    assert first["pairs_complete"] == 10
    assert first["metrics"]["resolved_rate"]["bootstrap_ci"] is not None
    assert first["metrics"]["resolved_rate"]["bootstrap_ci"] == second["metrics"]["resolved_rate"]["bootstrap_ci"]


def test_modes_are_not_merged_and_tradeoffs_are_named():
    normal = paired_runs([101, 102])
    adversarial = paired_runs([101, 102], mode="adversarial_search")
    result = compare_runs(normal + adversarial, baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    assert result["error"] == "mixed_modes"
    single = compare_runs(normal, baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    assert "tradeoffs" in single and isinstance(single["tradeoffs"], list)
    assert "лучше" not in json.dumps(single["summary"], ensure_ascii=False)


def test_incomplete_runs_stay_in_the_denominator_of_technical_completeness():
    runs = paired_runs([101, 102])
    runs[0] = dict(runs[0], status="canceled", complete=False)
    result = compare_runs(runs, baseline="SD-P1", candidate="SD-P2", environment="supportdesk")
    assert result["counts"]["SD-P1"] == {"planned": 2, "completed": 1, "incomplete": 1}
    assert result["pairs_complete"] == 1


# --- findings and fixes -----------------------------------------------------------------

def test_finding_carries_property_versions_events_and_state():
    rec = recipe()
    session = run(rec)
    findings = build_findings(rec, events_of(session), session.audit)
    finding = next(f for f in findings if f["check_id"] == "rewarded_rejected_resolution_v1")
    assert finding["check_version"] and finding["rule_hash"] and finding["environment_version"]
    assert finding["evidence_seqs"] and finding["events"]
    assert finding["explanation"].startswith("Правило")
    assert "злой" not in finding["explanation"]
    assert finding["scope"].startswith("Нарушение наблюдалось")


def test_fix_candidates_validate_and_stop_the_original_counterexample():
    rec = recipe()
    session = run(rec)
    finding = next(f for f in build_findings(rec, events_of(session), session.audit) if f["check_id"] == "rewarded_rejected_resolution_v1")
    env = get_environment("supportdesk")
    candidates = propose_fixes(rec.rule, finding, env)
    assert 1 <= len(candidates) <= 3
    for candidate in candidates:
        assert candidate["validation"]["ok"], candidate["validation"]
        assert candidate["status"] == "candidate"
    outcome = check_fix_on_counterexample(rec, events_of(session), candidates[0]["tree"], check_id=finding["check_id"])
    assert outcome["reproduced"] is False
