"""Worked payout examples shown in the rule editor (RULE-003).

They run through the same interpreter and ledger that a run uses, so the numbers in the
editor and in a run cannot drift apart (AC-009).
"""
from __future__ import annotations

from typing import Any

from ..contract import Environment
from .interpreter import EvalError, evaluate_rule

KIND_LABELS = {
    "ordinary": "Обычное событие",
    "technical_repeat": "Повторная доставка того же технического события",
    "unit_repeat": "Повтор по той же единице учета",
    "boundary": "Пограничный случай",
}


def compute_examples(rule: dict[str, Any], env: Environment) -> list[dict[str, Any]]:
    from ..ledger import RewardLedger  # the ledger itself depends on the interpreter

    samples = env.rule_examples(rule["trigger"])
    if len(samples) < 3:
        return []
    (ordinary_label, ordinary), (repeat_label, repeat), (boundary_label, boundary) = samples[:3]
    plan = [
        ("ordinary", ordinary_label, ordinary, "example:1", 1),
        ("technical_repeat", "Та же запись события доставлена повторно", ordinary, "example:1", 1),
        ("unit_repeat", repeat_label, repeat, "example:2", 2),
        ("boundary", boundary_label, boundary, "example:3", 3),
    ]
    ledger = RewardLedger("example")
    results = []
    for kind, label, payload, source_key, tick in plan:
        try:
            outcome = evaluate_rule(rule, env, rule["trigger"], payload, tick=tick)
        except EvalError as exc:
            results.append({"kind": kind, "label": label, "payload": payload, "tick": tick, "fired": False, "amount": 0, "error": {"code": exc.code, "message": exc.message, "path": exc.path}, "ledger_states": [], "payout": 0})
            continue
        entries = ledger.record_trigger(rule_version_id="draft", rule=rule, source_key=source_key, source_seq=tick, tick=tick, outcome=outcome)
        payout = sum(e["amount"] for e in entries if e["state"] in ("settled", "pending"))
        results.append(
            {
                "kind": kind,
                "label": label,
                "payload": payload,
                "tick": tick,
                "fired": outcome.fired,
                "amount": outcome.amount if outcome.fired else 0,
                "ledger_states": [e["state"] for e in entries],
                "ledger_reasons": [e["reason"] for e in entries],
                "payout": payout,
                "error": None,
            }
        )
    return results
