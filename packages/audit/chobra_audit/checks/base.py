"""Verifiable properties (spec section 13 "Проверка нарушения").

A property has a scope, a predicate, a horizon, a threshold and a version. Online checks
emit `check.failed` the moment a violation is established; `finalize` turns the run into
`pass`, `fail`, `not_applicable` or `inconclusive` with a reason. Checks never read the
participants' text explanations.
"""
from __future__ import annotations

from typing import Any


def violation(key: str, message: str, evidence_seqs: list[int], entity_ids: list[str]) -> dict[str, Any]:
    return {"key": key, "message": message, "evidence_seqs": sorted(set(evidence_seqs)), "entity_ids": entity_ids}


class Check:
    check_id = ""
    version = "1"
    title = ""
    formula = ""
    threshold = "0"
    scope = ""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.fired: dict[str, dict[str, Any]] = {}

    # online -------------------------------------------------------------------------
    def detect(self, new_events: list[dict[str, Any]], state: dict[str, Any], history: list[dict[str, Any]], env: Any) -> list[dict[str, Any]]:
        return []

    def observe(self, new_events: list[dict[str, Any]], state: dict[str, Any], history: list[dict[str, Any]], env: Any) -> list[dict[str, Any]]:
        fresh = []
        for item in self.detect(new_events, state, history, env):
            if item["key"] not in self.fired:
                self.fired[item["key"]] = item
                fresh.append(item)
        return fresh

    # final --------------------------------------------------------------------------
    def applicability(self, state: dict[str, Any], history: list[dict[str, Any]], metrics: dict[str, Any], env: Any) -> tuple[bool, str]:
        return True, ""

    def detect_final(self, state: dict[str, Any], history: list[dict[str, Any]], metrics: dict[str, Any], env: Any) -> list[dict[str, Any]]:
        return []

    def pending_reason(self, state: dict[str, Any], history: list[dict[str, Any]], env: Any) -> str:
        """Non-empty when the property cannot be decided yet (for example confirmations still pending)."""
        return ""

    def finalize(self, state: dict[str, Any], history: list[dict[str, Any]], metrics: dict[str, Any], complete: bool, env: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        late = []
        for item in self.detect_final(state, history, metrics, env):
            if item["key"] not in self.fired:
                self.fired[item["key"]] = item
                late.append(item)
        applicable, why = self.applicability(state, history, metrics, env)
        if self.fired:
            status, reason = "fail", f"Нарушений: {len(self.fired)}"
        elif not applicable:
            status, reason = "not_applicable", why
        elif not complete:
            status, reason = "inconclusive", "Испытание не завершено; горизонт не пройден"
        elif self.pending_reason(state, history, env):
            status, reason = "inconclusive", self.pending_reason(state, history, env)
        else:
            status, reason = "pass", "В выполненном испытании нарушение не наблюдалось"
        return (
            {
                "check_id": self.check_id,
                "version": self.version,
                "title": self.title,
                "formula": self.formula,
                "threshold": self.threshold,
                "scope": self.scope,
                "status": status,
                "reason": reason,
                "violations": list(self.fired.values()),
            },
            late,
        )

    def get_state(self) -> dict[str, Any]:
        return {"fired": self.fired}

    def set_state(self, state: dict[str, Any]) -> None:
        self.fired = dict(state.get("fired", {}))
