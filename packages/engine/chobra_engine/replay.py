"""Recorded participants and verified replay (spec sections 06 and 15).

Replay feeds the recorded, validated proposals back into the engine. It never calls a
model. A replay is `replay_verified` only if every tick reproduces the stored state hash
and the property under test fails again.
"""
from __future__ import annotations

from typing import Any, Callable

from .agent import AgentDecision
from .contract import Proposal, TickContext


class RecordedAgent:
    kind = "replay"

    def __init__(self, actor_id: str, proposals_by_tick: dict[int, list[dict[str, Any]]], mode: str = "recorded"):
        self.actor_id = actor_id
        self.mode = mode
        self.plan = {int(k): list(v) for k, v in proposals_by_tick.items()}
        self.used: dict[int, int] = {}

    @classmethod
    def from_plan(cls, actor_id: str, plan: dict[int, tuple[str, dict[str, Any]]]) -> "RecordedAgent":
        return cls(actor_id, {tick: [{"action_type": kind, "arguments": dict(args)}] for tick, (kind, args) in plan.items()})

    def decide(self, observation: dict[str, Any], ctx: TickContext, notify: Callable[[str, dict[str, Any]], None]) -> AgentDecision:
        index = self.used.get(ctx.tick, 0)
        self.used[ctx.tick] = index + 1
        recorded = self.plan.get(ctx.tick, [])
        if index < len(recorded):
            item = recorded[index]
            return AgentDecision(Proposal(self.actor_id, item["action_type"], dict(item.get("arguments") or {}), item.get("decision_summary", "")), degraded=bool(item.get("degraded")))
        return AgentDecision(Proposal(self.actor_id, "wait", {}, ""))

    def get_state(self) -> dict[str, Any]:
        return {"used": {str(k): v for k, v in self.used.items()}}

    def set_state(self, state: dict[str, Any]) -> None:
        self.used = {int(k): v for k, v in state.get("used", {}).items()}


def recorded_plan(events: list[dict[str, Any]]) -> dict[str, dict[int, list[dict[str, Any]]]]:
    """Proposals per participant and tick, taken from the domain events of a run."""
    plan: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for event in sorted((e for e in events if e["type"] == "action.proposed"), key=lambda e: e["seq"]):
        payload = event["payload"]
        plan.setdefault(event["actor_id"], {}).setdefault(event["tick"], []).append(
            {
                "action_type": payload["action_type"],
                "arguments": payload["arguments"],
                "decision_summary": payload.get("decision_summary", ""),
                "degraded": payload.get("degraded", False),
            }
        )
    return plan
