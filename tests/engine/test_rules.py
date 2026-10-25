import copy

import pytest

from chobra_engine.ledger import RewardLedger
from chobra_engine.rules import EvalError, compute_examples, evaluate_rule, rule_hash, validate_rule
from chobra_envs.rules_catalog import starting_rules
from chobra_envs.supportdesk import SupportDesk

ENV = SupportDesk()
POINT = 1_000_000

SPEC_EXAMPLE = {
    "schema_version": "1.0",
    "environment": "supportdesk",
    "trigger": "issue.confirmation_completed",
    "condition": {"op": "eq", "left": {"field": "event.confirmation_status"}, "right": {"literal": "confirmed", "type": "enum"}},
    "amount": {"literal": 10000000, "type": "int"},
    "unit": "reward_microunits",
    "recipient": {"field": "event.responsible_actor_id"},
    "deduplication": {"mode": "once_per_root", "key_fields": ["event.root_issue_id"]},
    "settlement": {"mode": "immediate_after_trigger"},
}


def codes(result):
    return [e.code for e in result.errors]


def test_spec_example_rule_is_valid():
    result = validate_rule(SPEC_EXAMPLE, ENV)
    assert result.errors == []


def test_unknown_field_blocks_publication_with_path():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["condition"]["left"] = {"field": "event.customer_mood"}
    result = validate_rule(rule, ENV)
    assert codes(result) == ["RULE_UNKNOWN_FIELD"]
    assert result.errors[0].path == "condition.left"


def test_unknown_operation_and_trigger_are_rejected():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["trigger"] = "issue.deleted"
    rule["amount"] = {"op": "pow", "args": [{"literal": 2, "type": "int"}, {"literal": 3, "type": "int"}]}
    result = validate_rule(rule, ENV)
    assert "RULE_UNKNOWN_TRIGGER" in codes(result)
    assert "RULE_UNKNOWN_OP" in codes(result)


def test_adding_duration_and_points_is_a_type_mismatch():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["amount"] = {
        "op": "add",
        "args": [{"literal": 5_000_000, "type": "int", "unit": "reward_microunits"}, {"field": "event.age_ticks"}],
    }
    result = validate_rule(rule, ENV)
    error = result.errors[0]
    assert error.code == "RULE_TYPE_MISMATCH"
    assert error.path == "amount.args[1]"
    assert error.details == {"expected_unit": "reward_microunits", "actual_unit": "duration_ticks"}
    assert error.message == "Нельзя сложить длительность и очки"


def test_division_without_zero_policy_is_rejected():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["amount"] = {
        "op": "round",
        "arg": {"op": "div", "args": [{"literal": 10_000_000, "type": "int", "unit": "reward_microunits"}, {"field": "event.age_ticks"}]},
    }
    assert "RULE_DIV_NO_POLICY" in codes(validate_rule(rule, ENV))
    rule["amount"]["arg"]["on_zero"] = {"literal": "0", "type": "decimal", "unit": "reward_microunits"}
    assert validate_rule(rule, ENV).errors == []


def test_depth_node_and_size_limits():
    deep = {"field": "event.root_problem_solved"}
    for _ in range(13):
        deep = {"op": "not", "arg": deep}
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["condition"] = deep
    assert "RULE_TOO_DEEP" in codes(validate_rule(rule, ENV))

    wide = copy.deepcopy(SPEC_EXAMPLE)
    wide["condition"] = {"op": "and", "args": [{"literal": True, "type": "boolean"}] * 520}
    assert "RULE_TOO_MANY_NODES" in codes(validate_rule(wide, ENV))

    big = copy.deepcopy(SPEC_EXAMPLE)
    big["description"] = "x" * 300_000
    assert "RULE_TOO_LARGE" in codes(validate_rule(big, ENV))


def test_enum_literal_must_belong_to_the_field():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["condition"]["right"] = {"literal": "kinda_confirmed", "type": "enum"}
    assert codes(validate_rule(rule, ENV)) == ["RULE_ENUM_VALUE"]


def test_decimal_amount_must_be_rounded_explicitly():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["amount"] = {"literal": "1.5", "type": "decimal", "unit": "reward_microunits"}
    assert "RULE_TYPE_MISMATCH" in codes(validate_rule(rule, ENV))
    rule["amount"] = {"op": "round", "mode": "half_even", "arg": rule["amount"]}
    assert validate_rule(rule, ENV).errors == []


def test_unknown_keys_and_bad_dedup_are_rejected():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["python"] = "import os"
    rule["deduplication"] = {"mode": "once_per_root", "key_fields": ["event.no_such_field"]}
    result = codes(validate_rule(rule, ENV))
    assert "RULE_UNKNOWN_KEY" in result and "RULE_BAD_DEDUP" in result


def test_mutable_field_produces_warning_not_error():
    rules = starting_rules("supportdesk")
    p3 = copy.deepcopy(rules["SD-P3"]["tree"])
    p3["amount"]["args"][0]["cond"]["left"] = {"field": "event.reported_complexity"}
    result = validate_rule(p3, ENV)
    assert result.errors == []
    assert "RULE_WARN_MUTABLE_FIELD" in [w.code for w in result.warnings]


def test_paying_each_close_is_a_warning_and_still_publishable():
    p1 = starting_rules("supportdesk")["SD-P1"]["tree"]
    result = validate_rule(p1, ENV)
    assert result.errors == []
    warning_codes = {w.code for w in result.warnings}
    assert {"RULE_WARN_UNCONFIRMED_TRIGGER", "RULE_WARN_REPEATABLE_PER_EVENT"} <= warning_codes


def test_starting_rules_validate_for_supportdesk():
    for key, rule in starting_rules("supportdesk").items():
        assert validate_rule(rule["tree"], ENV).errors == [], key


def test_p1_pays_for_unsolved_close():
    p1 = starting_rules("supportdesk")["SD-P1"]["tree"]
    payload = {"issue_id": "issue_004", "root_issue_id": "issue_004", "actor_id": "agent_02", "closed_unsolved": True, "is_root": True,
               "true_complexity": "hard", "triage_complexity": "hard", "reported_complexity": "hard", "age_ticks": 1, "close_count": 1}
    outcome = evaluate_rule(p1, ENV, "issue.closed", payload, tick=1)
    assert outcome.fired and outcome.amount == 10 * POINT and outcome.recipient == "agent_02"


def test_p2_does_not_pay_rejected_confirmation():
    p2 = starting_rules("supportdesk")["SD-P2"]["tree"]
    payload = {"issue_id": "issue_004", "root_issue_id": "issue_004", "responsible_actor_id": "agent_02", "confirmation_status": "rejected",
               "root_problem_solved": False, "is_root": True, "true_complexity": "hard", "triage_complexity": "hard", "reported_complexity": "hard", "age_ticks": 4}
    assert evaluate_rule(p2, ENV, "issue.confirmation_completed", payload, tick=4).fired is False
    payload.update(confirmation_status="confirmed", root_problem_solved=True)
    assert evaluate_rule(p2, ENV, "issue.confirmation_completed", payload, tick=4).amount == 10 * POINT


def test_p3_weights_complexity_and_age():
    p3 = starting_rules("supportdesk")["SD-P3"]["tree"]
    base = {"issue_id": "i", "root_issue_id": "i", "responsible_actor_id": "agent_01", "confirmation_status": "confirmed", "root_problem_solved": True,
            "is_root": True, "true_complexity": "easy", "triage_complexity": "easy", "reported_complexity": "easy", "age_ticks": 4}
    easy = evaluate_rule(p3, ENV, "issue.confirmation_completed", base, tick=4).amount
    hard = evaluate_rule(p3, ENV, "issue.confirmation_completed", {**base, "triage_complexity": "hard"}, tick=4).amount
    old = evaluate_rule(p3, ENV, "issue.confirmation_completed", {**base, "age_ticks": 40}, tick=40).amount
    assert hard > easy
    assert old > easy
    assert old == evaluate_rule(p3, ENV, "issue.confirmation_completed", {**base, "age_ticks": 10}, tick=10).amount


def test_division_by_zero_uses_declared_policy():
    rule = copy.deepcopy(SPEC_EXAMPLE)
    rule["condition"] = {"literal": True, "type": "boolean"}
    rule["amount"] = {"op": "round", "arg": {"op": "div", "args": [{"literal": 10_000_000, "type": "int", "unit": "reward_microunits"}, {"field": "event.age_ticks"}],
                                             "on_zero": {"literal": "7", "type": "decimal", "unit": "reward_microunits"}}}
    payload = {"issue_id": "i", "root_issue_id": "i", "responsible_actor_id": "a", "confirmation_status": "confirmed", "root_problem_solved": True,
               "is_root": True, "true_complexity": "easy", "triage_complexity": "easy", "reported_complexity": "easy", "age_ticks": 0}
    assert evaluate_rule(rule, ENV, "issue.confirmation_completed", payload, tick=0).amount == 7
    rule["amount"]["arg"]["on_zero"] = "error"
    with pytest.raises(EvalError):
        evaluate_rule(rule, ENV, "issue.confirmation_completed", payload, tick=0)


def test_rule_hash_is_stable_and_sensitive():
    assert rule_hash(SPEC_EXAMPLE) == rule_hash(copy.deepcopy(SPEC_EXAMPLE))
    changed = copy.deepcopy(SPEC_EXAMPLE)
    changed["amount"]["literal"] = 10000001
    assert rule_hash(changed) != rule_hash(SPEC_EXAMPLE)


# --- ledger ---------------------------------------------------------------------

def outcome_for(rule, payload, trigger="issue.closed", tick=1):
    return evaluate_rule(rule, ENV, trigger, payload, tick=tick)


CLOSE = {"issue_id": "issue_004", "root_issue_id": "issue_004", "actor_id": "agent_02", "closed_unsolved": True, "is_root": True,
         "true_complexity": "hard", "triage_complexity": "hard", "reported_complexity": "hard", "age_ticks": 1, "close_count": 1}


def test_repeated_technical_event_does_not_pay_twice():
    p1 = starting_rules("supportdesk")["SD-P1"]["tree"]
    ledger = RewardLedger("run-1")
    first = ledger.record_trigger(rule_version_id="v1", rule=p1, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(p1, CLOSE))
    again = ledger.record_trigger(rule_version_id="v1", rule=p1, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(p1, CLOSE))
    assert [e["state"] for e in first] == ["settled"]
    assert again == []
    assert ledger.balance("agent_02") == 10 * POINT


def test_per_event_rule_pays_each_close_of_same_root():
    p1 = starting_rules("supportdesk")["SD-P1"]["tree"]
    ledger = RewardLedger("run-1")
    ledger.record_trigger(rule_version_id="v1", rule=p1, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(p1, CLOSE))
    ledger.record_trigger(rule_version_id="v1", rule=p1, source_key="run-1:19", source_seq=19, tick=6, outcome=outcome_for(p1, {**CLOSE, "close_count": 2}))
    assert ledger.balance("agent_02") == 20 * POINT


def test_once_per_root_blocks_payout_for_child_of_same_root():
    rule = copy.deepcopy(starting_rules("supportdesk")["SD-P1"]["tree"])
    rule["deduplication"] = {"mode": "once_per_root", "key_fields": ["event.root_issue_id"]}
    ledger = RewardLedger("run-1")
    ledger.record_trigger(rule_version_id="v2", rule=rule, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(rule, {**CLOSE, "issue_id": "issue_004.1", "is_root": False}))
    second = ledger.record_trigger(rule_version_id="v2", rule=rule, source_key="run-1:9", source_seq=9, tick=2, outcome=outcome_for(rule, {**CLOSE, "issue_id": "issue_004.2", "is_root": False}))
    assert [e["state"] for e in second] == ["rejected"]
    assert second[0]["reason"] == "duplicate_unit"
    assert ledger.balance("agent_02") == 10 * POINT


def test_hold_until_confirmation_settles_or_rejects():
    rule = copy.deepcopy(starting_rules("supportdesk")["SD-P1"]["tree"])
    rule["settlement"] = {
        "mode": "hold_until_confirmation",
        "confirm_event": "issue.confirmation_completed",
        "match_field": "event.issue_id",
        "confirm_condition": {"op": "eq", "left": {"field": "event.confirmation_status"}, "right": {"literal": "confirmed", "type": "enum"}},
    }
    assert validate_rule(rule, ENV).errors == []
    ledger = RewardLedger("run-1")
    pending = ledger.record_trigger(rule_version_id="v3", rule=rule, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(rule, CLOSE))
    assert [e["state"] for e in pending] == ["pending"]
    assert ledger.balance("agent_02") == 0
    resolved = ledger.resolve_holds(rule=rule, env=ENV, event_type="issue.confirmation_completed",
                                    payload={**CLOSE, "responsible_actor_id": "agent_02", "confirmation_status": "rejected", "root_problem_solved": False},
                                    source_key="run-1:20", source_seq=20, tick=4)
    assert [e["state"] for e in resolved] == ["rejected"]
    assert ledger.balance("agent_02") == 0


def test_clawback_creates_compensating_entry_and_keeps_history():
    rule = copy.deepcopy(starting_rules("supportdesk")["SD-P1"]["tree"])
    rule["settlement"] = {"mode": "immediate_after_trigger", "clawback": {"event": "issue.reopened", "match_field": "event.issue_id"}}
    assert validate_rule(rule, ENV).errors == []
    ledger = RewardLedger("run-1")
    ledger.record_trigger(rule_version_id="v4", rule=rule, source_key="run-1:7", source_seq=7, tick=1, outcome=outcome_for(rule, CLOSE))
    reversed_entries = ledger.resolve_holds(rule=rule, env=ENV, event_type="issue.reopened",
                                            payload={"issue_id": "issue_004", "root_issue_id": "issue_004", "reason": "customer_rejected", "closed_by": "agent_02"},
                                            source_key="run-1:21", source_seq=21, tick=4)
    assert [e["state"] for e in reversed_entries] == ["reversed"]
    assert reversed_entries[0]["amount"] == -10 * POINT
    assert [e["state"] for e in ledger.entries] == ["settled", "reversed"]
    assert ledger.balance("agent_02") == 0


# --- examples (RULE-003) ----------------------------------------------------------

def test_examples_cover_ordinary_repeat_and_boundary_and_match_interpreter():
    p1 = starting_rules("supportdesk")["SD-P1"]["tree"]
    examples = compute_examples(p1, ENV)
    labels = [e["kind"] for e in examples]
    assert labels[:4] == ["ordinary", "technical_repeat", "unit_repeat", "boundary"]
    for example in examples:
        if example["kind"] == "technical_repeat":
            assert example["ledger_states"] == []
            continue
        direct = evaluate_rule(p1, ENV, p1["trigger"], example["payload"], tick=example["tick"])
        assert example["amount"] == (direct.amount if direct.fired else 0)
