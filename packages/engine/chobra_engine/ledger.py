"""Reward ledger (spec section 10 "Расчеты и реестр наград").

Append only: settlement of a held payout, rejection and clawback are new entries that
reference the original one. Processing the same technical event twice changes nothing.
"""
from __future__ import annotations

from typing import Any

from .contract import Environment
from .rules.interpreter import RuleOutcome, _Scope, evaluate_expr


class RewardLedger:
    def __init__(self, run_id: str, entries: list[dict[str, Any]] | None = None):
        self.run_id = run_id
        self.entries: list[dict[str, Any]] = entries or []
        self._sources = {(e["rule_version_id"], e["source_event_key"]) for e in self.entries}

    def _append(self, **fields: Any) -> dict[str, Any]:
        entry = {
            "entry_id": f"{self.run_id}:L{len(self.entries) + 1}",
            "run_id": self.run_id,
            "related_entry_id": None,
            "hold_match": None,
            "clawback_match": None,
            "reason": None,
            **fields,
        }
        self.entries.append(entry)
        self._sources.add((entry["rule_version_id"], entry["source_event_key"]))
        return entry

    def _undone(self) -> set[str]:
        """Entries cancelled by a later rejection or reversal, following settle-from-hold links."""
        undone = {e["related_entry_id"] for e in self.entries if e["state"] in ("reversed", "rejected") and e["related_entry_id"]}
        changed = True
        while changed:
            changed = False
            for e in self.entries:
                if e["entry_id"] in undone and e["related_entry_id"] and e["related_entry_id"] not in undone:
                    undone.add(e["related_entry_id"])
                    changed = True
        return undone

    def _active_units(self) -> set[str]:
        """Dedup keys that currently hold a payout: pending or settled, and not undone."""
        undone = self._undone()
        return {
            e["dedup_key"]
            for e in self.entries
            if e["dedup_key"] and e["entry_id"] not in undone and (e["state"] == "pending" or (e["state"] == "settled" and e["amount"] > 0))
        }

    def record_trigger(
        self,
        *,
        rule_version_id: str,
        rule: dict[str, Any],
        source_key: str,
        source_seq: int,
        tick: int,
        outcome: RuleOutcome,
    ) -> list[dict[str, Any]]:
        if (rule_version_id, source_key) in self._sources or not outcome.fired:
            return []
        common = {
            "rule_version_id": rule_version_id,
            "source_event_key": source_key,
            "source_event_seq": source_seq,
            "actor_id": outcome.recipient,
            "unit_ref": outcome.unit_ref,
            "dedup_key": outcome.dedup_key,
            "tick": tick,
        }
        if outcome.dedup_key is not None and outcome.dedup_key in self._active_units():
            return [self._append(**common, amount=0, state="rejected", reason="duplicate_unit")]
        settlement = rule["settlement"]
        if settlement["mode"] == "hold_until_confirmation":
            match = settlement["match_field"].partition(".")[2]
            return [self._append(**common, amount=outcome.amount, state="pending", hold_match=outcome.payload.get(match))]
        claw = settlement.get("clawback")
        claw_match = outcome.payload.get(claw["match_field"].partition(".")[2]) if claw else None
        return [self._append(**common, amount=outcome.amount, state="settled", clawback_match=claw_match)]

    def resolve_holds(
        self,
        *,
        rule: dict[str, Any],
        env: Environment,
        event_type: str,
        payload: dict[str, Any],
        source_key: str,
        source_seq: int,
        tick: int,
        rule_version_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Settle or reject held payouts and apply clawbacks triggered by this event."""
        settlement = rule["settlement"]
        new: list[dict[str, Any]] = []
        resolved = {e["related_entry_id"] for e in self.entries if e["related_entry_id"]}
        if settlement["mode"] == "hold_until_confirmation" and event_type == settlement["confirm_event"]:
            match = payload.get(settlement["match_field"].partition(".")[2])
            ok = bool(evaluate_expr(settlement["confirm_condition"], _Scope(payload, None, tick, []), "settlement.confirm_condition"))
            for entry in list(self.entries):
                if entry["state"] != "pending" or entry["hold_match"] != match or entry["entry_id"] in resolved:
                    continue
                key = f"{source_key}->{entry['entry_id']}"
                if (entry["rule_version_id"], key) in self._sources:
                    continue
                new.append(
                    self._append(
                        rule_version_id=entry["rule_version_id"],
                        source_event_key=key,
                        source_event_seq=source_seq,
                        actor_id=entry["actor_id"],
                        unit_ref=entry["unit_ref"],
                        dedup_key=entry["dedup_key"],
                        tick=tick,
                        amount=entry["amount"] if ok else 0,
                        state="settled" if ok else "rejected",
                        reason="confirmed" if ok else "confirmation_failed",
                        related_entry_id=entry["entry_id"],
                    )
                )
        claw = settlement.get("clawback")
        if claw and event_type == claw["event"]:
            match = payload.get(claw["match_field"].partition(".")[2])
            for entry in list(self.entries):
                if entry["state"] != "settled" or entry["amount"] <= 0 or entry["clawback_match"] != match or entry["entry_id"] in resolved:
                    continue
                key = f"{source_key}->{entry['entry_id']}"
                if (entry["rule_version_id"], key) in self._sources:
                    continue
                new.append(
                    self._append(
                        rule_version_id=entry["rule_version_id"],
                        source_event_key=key,
                        source_event_seq=source_seq,
                        actor_id=entry["actor_id"],
                        unit_ref=entry["unit_ref"],
                        dedup_key=entry["dedup_key"],
                        tick=tick,
                        amount=-entry["amount"],
                        state="reversed",
                        reason="clawback",
                        related_entry_id=entry["entry_id"],
                    )
                )
        return new

    def expire_holds(self, *, max_wait_ticks: int, tick: int, source_key: str, source_seq: int) -> list[dict[str, Any]]:
        resolved = {e["related_entry_id"] for e in self.entries if e["related_entry_id"]}
        new = []
        for entry in list(self.entries):
            if entry["state"] == "pending" and entry["entry_id"] not in resolved and tick - entry["tick"] >= max_wait_ticks:
                new.append(
                    self._append(
                        rule_version_id=entry["rule_version_id"], source_event_key=f"{source_key}->{entry['entry_id']}", source_event_seq=source_seq,
                        actor_id=entry["actor_id"], unit_ref=entry["unit_ref"], dedup_key=entry["dedup_key"], tick=tick,
                        amount=0, state="rejected", reason="confirmation_timeout", related_entry_id=entry["entry_id"],
                    )
                )
        return new

    def balance(self, actor_id: str | None = None) -> int:
        return sum(e["amount"] for e in self.entries if e["state"] in ("settled", "reversed") and (actor_id is None or e["actor_id"] == actor_id))

    def pending_total(self, actor_id: str | None = None) -> int:
        resolved = {e["related_entry_id"] for e in self.entries if e["related_entry_id"]}
        return sum(e["amount"] for e in self.entries if e["state"] == "pending" and e["entry_id"] not in resolved and (actor_id is None or e["actor_id"] == actor_id))

