"""Verified replay (spec section 15 "Проверенное воспроизведение").

Recorded validated proposals are executed again from the initial snapshot. No model is
called. The result is `replay_verified` only if every tick reproduces its stored state
hash and the property under test fails again.
"""
from __future__ import annotations

from typing import Any

from chobra_engine.replay import RecordedAgent, recorded_plan

from .recipe import RunRecipe, execute


def recorded_tick_hashes(events: list[dict[str, Any]]) -> dict[int, str]:
    return {e["tick"]: e["state_hash"] for e in events if e["type"] == "tick.completed"}


def verify_replay(recipe: RunRecipe, events: list[dict[str, Any]], *, check_id: str | None) -> dict[str, Any]:
    stored = recorded_tick_hashes(events)
    if not stored:
        return {"status": "replay_unavailable", "reason": "Нет сохраненных контрольных сумм тиков", "ticks_compared": 0, "first_divergent_tick": None, "property_reproduced": None}
    plan = recorded_plan(events)
    agents = [RecordedAgent(actor, plan.get(actor, {})) for actor in recipe.actor_ids]
    final_tick = max(stored)
    session = execute(recipe, agents, until_tick=final_tick)
    replayed = {e.tick: e.state_hash for e in session.log.events if e.type == "tick.completed"}
    divergent = next((tick for tick in sorted(stored) if replayed.get(tick) != stored[tick]), None)
    reproduced = None
    if check_id is not None:
        reproduced = any(e.type == "check.failed" and e.payload["check_id"] == check_id for e in session.log.events)
    ok = divergent is None and (check_id is None or reproduced)
    return {
        "status": "replay_verified" if ok else "replay_failed",
        "ticks_compared": len(stored),
        "first_divergent_tick": divergent,
        "property_reproduced": reproduced,
        "replay_chain_root": session.log.last_hash,
        "model_calls": 0,
    }
