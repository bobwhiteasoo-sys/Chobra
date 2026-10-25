"""Counterexample reduction (spec section 15 "Сокращение последовательности").

Delta debugging over the committed actions. Every candidate is executed again from the
initial state: a candidate counts only if all of its actions are still accepted by the
environment and the property still fails. Deleting lines from a log is never enough.
"""
from __future__ import annotations

import math
import time
from typing import Any

from chobra_engine.replay import RecordedAgent

from .recipe import RunRecipe, execute


def _units(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"tick": e["tick"], "actor_id": e["actor_id"], "action_type": e["payload"]["action_type"], "arguments": e["payload"]["arguments"]}
        for e in sorted(events, key=lambda e: e["seq"])
        if e["type"] == "action.committed" and e["payload"]["action_type"] != "wait"
    ]


def _plan(units: list[dict[str, Any]]) -> dict[str, dict[int, list[dict[str, Any]]]]:
    plan: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for unit in units:
        plan.setdefault(unit["actor_id"], {}).setdefault(unit["tick"], []).append({"action_type": unit["action_type"], "arguments": unit["arguments"]})
    return plan


def run_candidate(recipe: RunRecipe, units: list[dict[str, Any]], check_id: str, rule: dict[str, Any] | None = None) -> tuple[bool, Any]:
    plan = _plan(units)
    agents = [RecordedAgent(actor, plan.get(actor, {}), rebase_versions=True) for actor in recipe.actor_ids]
    session = execute(recipe, agents, rule=rule, stop_on_check=check_id)
    committed = {(e.tick, e.actor_id, e.payload["action_type"]) for e in session.log.events if e.type == "action.committed"}
    # The run stops at the first violation; actions after that tick cannot have caused it.
    reached = [u for u in units if u["tick"] <= session.tick]
    all_kept = all((u["tick"], u["actor_id"], u["action_type"]) in committed for u in reached)
    fails = any(e.type == "check.failed" and e.payload["check_id"] == check_id for e in session.log.events)
    if not fails and session.finished and session.audit:
        fails = any(r["check_id"] == check_id and r["status"] == "fail" for r in session.audit["checks"])
    return all_kept and fails, session


def minimize_counterexample(
    recipe: RunRecipe,
    events: list[dict[str, Any]],
    *,
    check_id: str,
    max_executions: int = 200,
    max_cpu_seconds: float = 60.0,
) -> dict[str, Any]:
    units = _units(events)
    executions = 0
    started = time.process_time()
    exhausted = False

    def test(candidate: list[dict[str, Any]]) -> bool:
        nonlocal executions, exhausted
        if executions >= max_executions or time.process_time() - started > max_cpu_seconds:
            exhausted = True
            return False
        executions += 1
        ok, _ = run_candidate(recipe, candidate, check_id)
        return ok

    original = len(units)
    if not test(units):
        status = "reduced" if exhausted else "not_reproduced"
        return {"status": status, "label": "контрпример не воспроизведен" if status == "not_reproduced" else "сокращенный контрпример", "actions": units, "original_count": original, "executions": executions, "cpu_seconds": round(time.process_time() - started, 3), "verified": False}
    granularity = 2
    proven = False
    while len(units) >= 2 and not exhausted:
        chunk = math.ceil(len(units) / granularity)
        subsets = [units[i:i + chunk] for i in range(0, len(units), chunk)]
        reduced = False
        for subset in subsets:
            if test(subset):
                units, granularity, reduced = subset, 2, True
                break
        if not reduced and not exhausted:
            for subset in subsets:
                complement = [u for u in units if u not in subset]
                if complement and test(complement):
                    units, granularity, reduced = complement, max(granularity - 1, 2), True
                    break
        if reduced or exhausted:
            continue
        if granularity >= len(units):
            proven = True
            break
        granularity = min(len(units), granularity * 2)
    if len(units) == 1 and not exhausted:
        proven = True
    verified, session = run_candidate(recipe, units, check_id)
    status = "minimal" if proven and verified else "reduced"
    return {
        "status": status,
        "label": "минимальный контрпример (удаление любого действия разрушает нарушение)" if status == "minimal" else "сокращенный контрпример",
        "actions": units,
        "original_count": original,
        "executions": executions,
        "cpu_seconds": round(time.process_time() - started, 3),
        "verified": verified,
        "final_chain_root": session.log.last_hash,
    }
