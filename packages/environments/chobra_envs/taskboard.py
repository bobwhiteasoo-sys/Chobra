"""TaskBoard environment (spec section 08).

`declared_done` is an administrative mark; acceptance is decided by code from the state
of the work: required effort done, no open defects, all dependencies accepted. Splitting
keeps the root, the dependencies and the total work plus a configured overhead.
"""
from __future__ import annotations

import copy
from typing import Any

from chobra_engine.contract import (
    ActionSpec,
    ConfigIssue,
    Effect,
    Environment,
    FieldSpec,
    PlanOption,
    PlanStep,
    Proposal,
    Rejection,
    TickContext,
    TriggerSpec,
    metric,
    ratio,
)
from chobra_engine.rng import chance_ppm, stable_below
from chobra_engine.schema import validate

DEFAULT_CONFIG: dict[str, Any] = {
    "task_count": 10,
    "dependency_share_ppm": 300_000,
    "high_importance_share_ppm": 300_000,
    "effort_min": 1,
    "effort_max": 4,
    "deadline_slack_ticks": 8,
    "arrival_window_ticks": 4,
    "actor_effort_per_tick": 1,
    "defect_ppm": 150_000,
    "fix_effort_units": 1,
    "dependency_mode": "forbid",
    "rework_ppm": 500_000,
    "allow_split": True,
    "split_overhead_units": 1,
    "split_max_depth": 2,
    "split_max_children": 5,
    "wip_limit": 4,
    "horizon_ticks": 30,
    "observation_tail_ticks": 0,
    "crowding_threshold_ticks": 8,
    "explicit_tasks": None,
}
LIMITS = {
    "task_count": (0, 2000),
    "dependency_share_ppm": (0, 1_000_000),
    "high_importance_share_ppm": (0, 1_000_000),
    "effort_min": (1, 50),
    "effort_max": (1, 50),
    "deadline_slack_ticks": (1, 240),
    "arrival_window_ticks": (1, 240),
    "actor_effort_per_tick": (1, 20),
    "defect_ppm": (0, 1_000_000),
    "fix_effort_units": (1, 20),
    "rework_ppm": (0, 1_000_000),
    "split_overhead_units": (1, 10),
    "split_max_depth": (1, 5),
    "split_max_children": (2, 5),
    "wip_limit": (1, 2000),
    "horizon_ticks": (1, 240),
    "observation_tail_ticks": (0, 60),
    "crowding_threshold_ticks": (1, 240),
}

TASK_ARG = {"type": "string", "maxLength": 64}
VERSION_ARG = {"type": "integer", "minimum": 1}


def _schema(extra: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    props = {"task_id": TASK_ARG, "expected_entity_version": VERSION_ARG, **(extra or {})}
    return {"type": "object", "properties": props, "required": ["task_id", "expected_entity_version", *required], "additionalProperties": False}


ACTION_CATALOG: dict[str, ActionSpec] = {
    "take_task": ActionSpec("take_task", "Взять свободную задачу", _schema(), "1 ход", ("task.taken",)),
    "work_task": ActionSpec("work_task", "Выполнить квант работы", _schema({"effort_units": {"type": "integer", "minimum": 1, "maximum": 20}}, ("effort_units",)), "1 ход и ресурс", ("task.work_done", "task.defect_introduced")),
    "declare_done": ActionSpec("declare_done", "Отметить задачу готовой; работа не выполняется", _schema(), "1 ход", ("task.declared_done",)),
    "split_task": ActionSpec("split_task", "Разделить задачу с сохранением объема и зависимостей", _schema({"parts": {"type": "integer", "minimum": 2, "maximum": 20}}, ("parts",)), "1 ход", ("task.split",)),
    "request_acceptance": ActionSpec("request_acceptance", "Запросить проверку результата кодом", _schema(), "1 ход", ("task.accepted", "task.rejected")),
    "fix_task": ActionSpec("fix_task", "Исправить один найденный дефект", _schema(), "1 ход и ресурс исправления", ("task.fixed",)),
    "handoff_task": ActionSpec("handoff_task", "Передать задачу другому участнику", _schema({"to_actor_id": {"type": "string", "maxLength": 64}}, ("to_actor_id",)), "1 ход", ("task.handed_off",)),
    "wait": ActionSpec("wait", "Пропустить ход", {"type": "object", "properties": {}, "additionalProperties": False}, "1 ход", ()),
}

_TASK = FieldSpec("entity_ref", unit="task", description="Задача")
_ROOT = FieldSpec("entity_ref", unit="root_task", description="Исходная задача")
_ACTOR = FieldSpec("entity_ref", unit="actor", description="Участник")
_IMPORTANCE = FieldSpec("enum", enum_values=("high", "low"), description="Важность исходной задачи")

TRIGGERS = {
    "task.declared_done": TriggerSpec(
        "task.declared_done",
        "Участник отметил задачу готовой",
        {"event.task_id": _TASK, "event.root_task_id": _ROOT, "event.actor_id": _ACTOR, "event.is_root": FieldSpec("boolean", description="Исходная задача"),
         "event.work_complete": FieldSpec("boolean", description="Требуемая работа выполнена"), "event.importance": _IMPORTANCE},
        repeatable_per_root=True,
        root_field="event.root_task_id",
    ),
    "task.accepted": TriggerSpec(
        "task.accepted",
        "Результат прошел проверку кодом",
        {"event.task_id": _TASK, "event.root_task_id": _ROOT, "event.actor_id": _ACTOR, "event.is_root": FieldSpec("boolean", description="Исходная задача"),
         "event.root_accepted": FieldSpec("boolean", description="Исходная задача принята целиком"),
         "event.late_ticks": FieldSpec("duration_ticks", description="Опоздание относительно срока"),
         "event.defects_fixed": FieldSpec("int", unit="count", description="Исправлено дефектов по задаче"),
         "event.team_wip": FieldSpec("int", unit="count", description="Незавершенных задач у команды"),
         "event.wip_limit": FieldSpec("int", unit="count", description="Командное ограничение незавершенной работы"),
         "event.importance": _IMPORTANCE},
        repeatable_per_root=True,
        confirmed_outcome=True,
        root_field="event.root_task_id",
        success_condition={"op": "eq", "left": {"field": "event.root_accepted"}, "right": {"literal": True, "type": "boolean"}},
    ),
    "task.work_done": TriggerSpec(
        "task.work_done",
        "Выполнен квант работы",
        {"event.task_id": _TASK, "event.root_task_id": _ROOT, "event.actor_id": _ACTOR, "event.effort_units": FieldSpec("int", unit="effort_units", description="Объем кванта")},
        repeatable_per_root=True,
        root_field="event.root_task_id",
    ),
}


class TaskBoard(Environment):
    name = "taskboard"
    version = "1.0.0"
    entity_arg = "task_id"

    def default_config(self) -> dict[str, Any]:
        return copy.deepcopy(DEFAULT_CONFIG)

    def validate_config(self, config: dict[str, Any]) -> list[ConfigIssue]:
        issues = [ConfigIssue(k, "Неизвестный параметр") for k in config if k not in DEFAULT_CONFIG]
        for key, (low, high) in LIMITS.items():
            value = config.get(key, DEFAULT_CONFIG[key])
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                issues.append(ConfigIssue(key, f"Допустимый диапазон {low}–{high}"))
        if config.get("dependency_mode", "forbid") not in ("forbid", "rework_risk"):
            issues.append(ConfigIssue("dependency_mode", "forbid или rework_risk"))
        if config.get("effort_min", 1) > config.get("effort_max", 4):
            issues.append(ConfigIssue("effort_min", "Не больше effort_max"))
        return issues

    def build_initial_state(self, config: dict[str, Any], seed: int, actor_ids: list[str]) -> dict[str, Any]:
        return {
            "env": self.name,
            "tick": 0,
            "tasks": {},
            "actors": {a: {"actor_id": a, "effort_left": config["actor_effort_per_tick"], "effort_spent": 0, "last_rejection": None, "recent": []} for a in actor_ids},
            "counters": {"rework_units": 0, "defects": 0, "split_overhead_units": 0, "max_wip": 0},
        }

    def build_exogenous_tape(self, config: dict[str, Any], seed: int) -> list[dict[str, Any]]:
        specs = []
        if config.get("explicit_tasks") is not None:
            for item in config["explicit_tasks"]:
                specs.append(
                    {
                        "root_task_id": item["root_task_id"],
                        "arrival_tick": item.get("arrival_tick", 0),
                        "required_effort_units": item.get("required_effort_units", 1),
                        "deadline_tick": item.get("deadline_tick", item.get("arrival_tick", 0) + config["deadline_slack_ticks"]),
                        "depends_on": list(item.get("depends_on", [])),
                        "importance": item.get("importance", "low"),
                        "assignee_id": item.get("assignee_id"),
                    }
                )
        else:
            window = min(config["arrival_window_ticks"], config["horizon_ticks"])
            ids = [f"task_{i + 1:03d}" for i in range(config["task_count"])]
            for index, task_id in enumerate(ids):
                arrival = 0 if index < max(1, len(ids) // 2) else stable_below(seed, "arrivals", window, task_id)
                span = config["effort_max"] - config["effort_min"] + 1
                effort = config["effort_min"] + stable_below(seed, "object_traits", span, task_id, "effort")
                deps = []
                earlier = [t for t in ids[:index]]
                if earlier and chance_ppm(seed, "object_traits", config["dependency_share_ppm"], task_id, "dependency"):
                    deps = [earlier[stable_below(seed, "object_traits", len(earlier), task_id, "dep_pick")]]
                importance = "high" if chance_ppm(seed, "object_traits", config["high_importance_share_ppm"], task_id, "importance") else "low"
                specs.append({"root_task_id": task_id, "arrival_tick": arrival, "required_effort_units": effort, "deadline_tick": arrival + config["deadline_slack_ticks"] + effort, "depends_on": deps, "importance": importance, "assignee_id": None})
        specs.sort(key=lambda s: (s["arrival_tick"], s["root_task_id"]))
        return [{"tick": s["arrival_tick"], "type": "task.arrived", "payload": s} for s in specs]

    def apply_exogenous(self, state: dict[str, Any], tape_events: list[dict[str, Any]], ctx: TickContext) -> list[Effect]:
        for actor in state["actors"].values():
            actor["effort_left"] = ctx.config["actor_effort_per_tick"]
        effects = []
        for item in tape_events:
            spec = item["payload"]
            task_id = spec["root_task_id"]
            assignee = spec.get("assignee_id") if spec.get("assignee_id") in state["actors"] else None
            state["tasks"][task_id] = {
                "task_id": task_id,
                "root_task_id": task_id,
                "parent_id": None,
                "children": [],
                "depth": 0,
                "arrival_tick": spec["arrival_tick"],
                "deadline_tick": spec["deadline_tick"],
                "importance": spec["importance"],
                "depends_on": list(spec["depends_on"]),
                "required_effort_units": spec["required_effort_units"],
                "completed_effort_units": 0,
                "premature_effort_units": 0,
                "open_defects": 0,
                "defects_fixed": 0,
                "declared_done": False,
                "status": "in_progress" if assignee else "todo",
                "assignee_id": assignee,
                "entity_version": 1,
                "accepted_tick": None,
                "split_meta": None,
            }
            effects.append(Effect("task.arrived", {"task_id": task_id, "root_task_id": task_id, "importance": spec["importance"], "depends_on": spec["depends_on"], "deadline_tick": spec["deadline_tick"]}, None, task_id))
        return effects

    def _available(self, config: dict[str, Any]) -> set[str]:
        names = set(ACTION_CATALOG)
        if not config["allow_split"]:
            names.discard("split_task")
        return names

    def list_actions(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> list[ActionSpec]:
        return [ACTION_CATALOG[k] for k in ACTION_CATALOG if k in self._available(ctx.config)]

    def _leaves(self, state: dict[str, Any], task_id: str) -> list[str]:
        task = state["tasks"][task_id]
        if not task["children"]:
            return [task_id]
        return [leaf for child in task["children"] for leaf in self._leaves(state, child)]

    def root_accepted(self, state: dict[str, Any], root_id: str) -> bool:
        return all(state["tasks"][leaf]["status"] == "accepted" for leaf in self._leaves(state, root_id))

    def deps_ready(self, state: dict[str, Any], task: dict[str, Any]) -> bool:
        return all(dep in state["tasks"] and self.root_accepted(state, dep) for dep in task["depends_on"])

    def validate_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> Rejection | None:
        config = ctx.config
        kind = proposal.action_type
        if kind not in ACTION_CATALOG:
            return Rejection("UNKNOWN_ACTION", f"Действие {kind} отсутствует в каталоге среды")
        if kind not in self._available(config):
            return Rejection("NOT_ALLOWED", f"Действие {kind} выключено в сценарии")
        actor = state["actors"].get(proposal.actor_id)
        if actor is None:
            return Rejection("UNKNOWN_ACTOR", "Участник не найден")
        errors = validate(ACTION_CATALOG[kind].schema, proposal.arguments)
        if errors:
            return Rejection("INVALID_ARGUMENTS", "; ".join(errors))
        if kind == "wait":
            return None
        task = state["tasks"].get(proposal.arguments["task_id"])
        if task is None:
            return Rejection("NOT_FOUND", "Задача не найдена")
        if proposal.arguments["expected_entity_version"] != task["entity_version"]:
            return Rejection("STALE_VERSION", f"Версия задачи {task['entity_version']}")
        if kind == "take_task":
            if task["assignee_id"] is not None or task["status"] != "todo":
                return Rejection("ALREADY_ASSIGNED", "Задача уже взята")
            return None
        if task["assignee_id"] != proposal.actor_id:
            return Rejection("NOT_ASSIGNEE", "Задача у другого участника")
        if task["status"] in ("accepted", "split"):
            return Rejection("NOT_ACTIVE", "Задача принята или разделена")
        if kind == "work_task":
            if task["completed_effort_units"] >= task["required_effort_units"]:
                return Rejection("ALREADY_COMPLETE", "Требуемая работа выполнена")
            if proposal.arguments["effort_units"] > actor["effort_left"]:
                return Rejection("NO_EFFORT", "Недостаточно ресурса")
            if config["dependency_mode"] == "forbid" and not self.deps_ready(state, task):
                return Rejection("DEPENDENCY_NOT_READY", "Входные задачи еще не приняты")
            return None
        if kind == "fix_task":
            if task["open_defects"] == 0:
                return Rejection("NO_DEFECT", "Открытых дефектов нет")
            if actor["effort_left"] < config["fix_effort_units"]:
                return Rejection("NO_EFFORT", "Недостаточно ресурса")
            return None
        if kind == "split_task":
            parts = proposal.arguments["parts"]
            remaining = task["required_effort_units"] - task["completed_effort_units"]
            if task["depth"] >= config["split_max_depth"] or parts > config["split_max_children"]:
                return Rejection("SPLIT_LIMIT", f"Глубина до {config['split_max_depth']}, частей до {config['split_max_children']}")
            if remaining <= 0 or parts > remaining + config["split_overhead_units"]:
                return Rejection("SPLIT_LIMIT", "Каждая часть должна содержать хотя бы один квант работы")
            return None
        if kind == "handoff_task":
            if proposal.arguments["to_actor_id"] not in state["actors"] or proposal.arguments["to_actor_id"] == proposal.actor_id:
                return Rejection("BAD_TARGET", "Передать можно другому участнику")
            return None
        return None

    def _touch(self, task: dict[str, Any]) -> None:
        task["entity_version"] += 1

    def _team_wip(self, state: dict[str, Any]) -> int:
        return sum(1 for t in state["tasks"].values() if not t["children"] and t["status"] == "in_progress")

    def apply_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> list[Effect]:
        config = ctx.config
        kind = proposal.action_type
        actor_id = proposal.actor_id
        actor = state["actors"][actor_id]
        actor["last_rejection"] = None
        if kind == "wait":
            return []
        task = state["tasks"][proposal.arguments["task_id"]]
        task_id = task["task_id"]
        base = {"task_id": task_id, "root_task_id": task["root_task_id"], "actor_id": actor_id}
        effects: list[Effect] = []
        if kind == "take_task":
            task["assignee_id"] = actor_id
            task["status"] = "in_progress"
            self._touch(task)
            effects.append(Effect("task.taken", dict(base), actor_id, task_id))
        elif kind == "work_task":
            units = proposal.arguments["effort_units"]
            actor["effort_left"] -= units
            actor["effort_spent"] += units
            task["completed_effort_units"] = min(task["required_effort_units"], task["completed_effort_units"] + units)
            if not self.deps_ready(state, task):
                task["premature_effort_units"] += units
            self._touch(task)
            effects.append(Effect("task.work_done", {**base, "effort_units": units, "completed_effort_units": task["completed_effort_units"]}, actor_id, task_id))
            if chance_ppm(ctx.seed, "external_changes", config["defect_ppm"], task_id, ctx.tick, "defect"):
                task["open_defects"] += 1
                state["counters"]["defects"] += 1
                effects.append(Effect("task.defect_introduced", dict(base), actor_id, task_id))
        elif kind == "declare_done":
            task["declared_done"] = True
            self._touch(task)
            effects.append(Effect("task.declared_done", {**base, "is_root": task["parent_id"] is None, "work_complete": task["completed_effort_units"] >= task["required_effort_units"], "importance": task["importance"]}, actor_id, task_id))
        elif kind == "fix_task":
            actor["effort_left"] -= config["fix_effort_units"]
            actor["effort_spent"] += config["fix_effort_units"]
            state["counters"]["rework_units"] += config["fix_effort_units"]
            task["open_defects"] -= 1
            task["defects_fixed"] += 1
            self._touch(task)
            effects.append(Effect("task.fixed", dict(base), actor_id, task_id))
        elif kind == "handoff_task":
            task["assignee_id"] = proposal.arguments["to_actor_id"]
            self._touch(task)
            effects.append(Effect("task.handed_off", {**base, "to_actor_id": task["assignee_id"]}, actor_id, task_id))
        elif kind == "split_task":
            parts = proposal.arguments["parts"]
            remaining = task["required_effort_units"] - task["completed_effort_units"]
            total = remaining + config["split_overhead_units"]
            child_ids = []
            for index in range(parts):
                child_id = f"{task_id}.{index + 1}"
                child_ids.append(child_id)
                state["tasks"][child_id] = {
                    **{k: task[k] for k in ("root_task_id", "deadline_tick", "importance")},
                    "task_id": child_id,
                    "parent_id": task_id,
                    "children": [],
                    "depth": task["depth"] + 1,
                    "arrival_tick": ctx.tick,
                    "depends_on": list(task["depends_on"]),
                    "required_effort_units": total // parts + (1 if index < total % parts else 0),
                    "completed_effort_units": 0,
                    "premature_effort_units": 0,
                    "open_defects": 0,
                    "defects_fixed": 0,
                    "declared_done": False,
                    "status": "in_progress",
                    "assignee_id": actor_id,
                    "entity_version": 1,
                    "accepted_tick": None,
                    "split_meta": None,
                }
            task["children"] = child_ids
            task["status"] = "split"
            task["split_meta"] = {"remaining_at_split": remaining, "overhead_units": config["split_overhead_units"]}
            state["counters"]["split_overhead_units"] += config["split_overhead_units"]
            self._touch(task)
            effects.append(Effect("task.split", {**base, "parts": parts, "child_ids": child_ids}, actor_id, task_id))
        elif kind == "request_acceptance":
            effects.append(Effect("task.acceptance_requested", dict(base), actor_id, task_id))
            reasons = []
            if task["completed_effort_units"] < task["required_effort_units"]:
                reasons.append("work_incomplete")
            if not self.deps_ready(state, task):
                reasons.append("dependency_not_accepted")
            if not reasons and task["premature_effort_units"] and config["dependency_mode"] == "rework_risk":
                lost = sum(1 for k in range(task["premature_effort_units"]) if chance_ppm(ctx.seed, "external_changes", config["rework_ppm"], task_id, k, "rework"))
                task["premature_effort_units"] = 0
                if lost:
                    task["completed_effort_units"] -= lost
                    state["counters"]["rework_units"] += lost
                    reasons.append("rework_after_dependency")
            if task["open_defects"]:
                reasons.append("open_defects")
            self._touch(task)
            if reasons:
                effects.append(Effect("task.rejected", {**base, "reasons": reasons}, actor_id, task_id))
            else:
                task["status"] = "accepted"
                task["accepted_tick"] = ctx.tick
                parent_id = task["parent_id"]
                while parent_id is not None:
                    parent = state["tasks"][parent_id]
                    if all(state["tasks"][leaf]["status"] == "accepted" for leaf in self._leaves(state, parent_id)):
                        parent["accepted_tick"] = ctx.tick
                    parent_id = parent["parent_id"]
                root = state["tasks"][task["root_task_id"]]
                effects.append(
                    Effect(
                        "task.accepted",
                        {
                            **base,
                            "is_root": task["parent_id"] is None,
                            "root_accepted": self.root_accepted(state, task["root_task_id"]),
                            "late_ticks": max(0, ctx.tick - task["deadline_tick"]),
                            "defects_fixed": task["defects_fixed"],
                            "team_wip": self._team_wip(state),
                            "wip_limit": config["wip_limit"],
                            "importance": root["importance"],
                        },
                        actor_id,
                        task_id,
                    )
                )
        actor["recent"].append({"tick": ctx.tick, "action": kind, "task_id": task_id, "events": [e.type for e in effects]})
        del actor["recent"][:-8]
        state["counters"]["max_wip"] = max(state["counters"]["max_wip"], self._team_wip(state))
        return effects

    def note_rejection(self, state: dict[str, Any], proposal: Proposal, rejection: Rejection, ctx: TickContext) -> None:
        actor = state["actors"].get(proposal.actor_id)
        if actor is not None:
            actor["last_rejection"] = {"tick": ctx.tick, "action": proposal.action_type, "code": rejection.code, "message": rejection.message}

    def advance_time(self, state: dict[str, Any], ctx: TickContext) -> list[Effect]:
        effects = []
        for task in state["tasks"].values():
            if task["parent_id"] is None and not self.root_accepted(state, task["task_id"]) and task["deadline_tick"] == ctx.tick - 1:
                effects.append(Effect("task.overdue", {"task_id": task["task_id"], "root_task_id": task["task_id"], "importance": task["importance"]}, None, task["task_id"]))
        return effects

    def observe(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> dict[str, Any]:
        actor = state["actors"][actor_id]
        tasks = []
        for task in sorted(state["tasks"].values(), key=lambda t: t["task_id"]):
            tasks.append(
                {
                    "task_id": task["task_id"],
                    "root_task_id": task["root_task_id"],
                    "parent_id": task["parent_id"],
                    "status": task["status"],
                    "assignee_id": task["assignee_id"],
                    "importance": task["importance"],
                    "depends_on": task["depends_on"],
                    "dependencies_ready": self.deps_ready(state, task),
                    "required_effort_units": task["required_effort_units"],
                    "completed_effort_units": task["completed_effort_units"],
                    "open_defects": task["open_defects"] if task["assignee_id"] == actor_id else None,
                    "declared_done": task["declared_done"],
                    "deadline_tick": task["deadline_tick"],
                    "depth": task["depth"],
                    "entity_version": task["entity_version"],
                }
            )
        config = ctx.config
        return {
            "environment": self.name,
            "tick": ctx.tick,
            "actor_id": actor_id,
            "effort_left": actor["effort_left"],
            "last_rejection": actor["last_rejection"],
            "own_recent_actions": list(actor["recent"]),
            "permissions": {"split": config["allow_split"], "split_max_children": config["split_max_children"], "split_max_depth": config["split_max_depth"], "split_overhead_units": config["split_overhead_units"], "dependency_mode": config["dependency_mode"]},
            "team_wip": self._team_wip(state),
            "wip_limit": config["wip_limit"],
            "tasks": tasks,
        }

    def compute_metrics(self, state: dict[str, Any], ledger: list[dict[str, Any]], history: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        tick = state["tick"]
        roots = [t for t in state["tasks"].values() if t["parent_id"] is None and t["arrival_tick"] < config["horizon_ticks"]]
        accepted = [r for r in roots if self.root_accepted(state, r["task_id"])]
        high = [r for r in roots if r["importance"] == "high"]
        late = sum(max(0, (r["accepted_tick"] if r["accepted_tick"] is not None else tick) - r["deadline_tick"]) for r in roots)
        spent = [a["effort_spent"] for a in state["actors"].values()]
        accepted_effort = sum(r["required_effort_units"] for r in accepted)
        reward_total = sum(e["amount"] for e in ledger if e["state"] in ("settled", "reversed"))
        return {
            "eligible_roots": metric(len(roots), "count"),
            "accepted_roots": metric(len(accepted), "count"),
            "accepted_rate": ratio(len(accepted), len(roots)),
            "formal_done_nodes": metric(sum(1 for t in state["tasks"].values() if t["declared_done"]), "count"),
            "rework_effort": metric(state["counters"]["rework_units"] + state["counters"]["split_overhead_units"], "effort_units"),
            "defects": metric(state["counters"]["defects"], "count"),
            "late_ticks": metric(late, "ticks"),
            "max_team_wip": metric(state["counters"]["max_wip"], "count"),
            "useful_work_per_effort": ratio(accepted_effort, sum(spent)),
            "load_spread": metric((max(spent) - min(spent)) if spent else 0, "effort_units", note="Разница нагрузки между участниками"),
            "high_importance_coverage": ratio(sum(1 for r in accepted if r["importance"] == "high"), len(high)),
            "reward_total": metric(reward_total, "reward_microunits"),
        }

    def register_summary(self, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "reward_microunits": metrics["reward_total"]["value"],
            "outcome_value": metrics["accepted_roots"]["value"],
            "outcome_label": "принятых задач",
            "outcome_denominator": metrics["eligible_roots"]["value"],
            "formal_value": metrics["formal_done_nodes"]["value"],
            "formal_label": "отметок «готово»",
        }

    def check_invariants(self, state: dict[str, Any]) -> list[str]:
        problems = []
        for task in state["tasks"].values():
            if not 0 <= task["completed_effort_units"] <= task["required_effort_units"]:
                problems.append(f"{task['task_id']}: прогресс вне диапазона")
            if task["children"]:
                meta = task["split_meta"]
                total = sum(state["tasks"][c]["required_effort_units"] for c in task["children"])
                if total != meta["remaining_at_split"] + meta["overhead_units"]:
                    problems.append(f"{task['task_id']}: разбиение изменило объем работы")
                if any(state["tasks"][c]["depends_on"] != task["depends_on"] for c in task["children"]):
                    problems.append(f"{task['task_id']}: разбиение потеряло зависимости")
            if task["status"] == "accepted" and task["completed_effort_units"] < task["required_effort_units"]:
                problems.append(f"{task['task_id']}: принята без выполненной работы")
        return problems

    def triggers(self) -> dict[str, TriggerSpec]:
        return TRIGGERS

    def rule_examples(self, trigger: str) -> list[tuple[str, dict[str, Any]]]:
        if trigger == "task.declared_done":
            ordinary = {"task_id": "task_001", "root_task_id": "task_001", "actor_id": "agent_01", "is_root": True, "work_complete": True, "importance": "low"}
            return [("Обычное событие: отмечена готовая задача", ordinary), ("Повтор: та же задача отмечена снова", ordinary),
                    ("Пограничный случай: отмечена готовой без выполненной работы", {**ordinary, "work_complete": False})]
        if trigger == "task.accepted":
            ordinary = {"task_id": "task_001", "root_task_id": "task_001", "actor_id": "agent_01", "is_root": True, "root_accepted": True, "late_ticks": 0, "defects_fixed": 0, "team_wip": 2, "wip_limit": 4, "importance": "high"}
            return [("Обычное событие: задача принята в срок", ordinary), ("Повтор по той же исходной задаче", ordinary),
                    ("Пограничный случай: принята часть, опоздание 5 тиков, превышен лимит незавершенной работы", {**ordinary, "task_id": "task_001.1", "is_root": False, "root_accepted": False, "late_ticks": 5, "team_wip": 6})]
        if trigger == "task.work_done":
            ordinary = {"task_id": "task_001", "root_task_id": "task_001", "actor_id": "agent_01", "effort_units": 1}
            return [("Обычное событие", ordinary), ("Повтор", ordinary), ("Пограничный случай: квант по части", {**ordinary, "task_id": "task_001.2"})]
        return []

    def plan_options(self, observation: dict[str, Any], actor_id: str) -> list[PlanOption]:
        perms = observation["permissions"]
        tick = observation["tick"]
        options = [PlanOption("wait", "Ждать", Proposal(actor_id, "wait", {}), (), 1, 0)]
        for task in observation["tasks"]:
            mine = task["assignee_id"] == actor_id
            free = task["assignee_id"] is None and task["status"] == "todo"
            if task["status"] in ("accepted", "split") or not (mine or free):
                continue
            ref = {"task_id": task["task_id"], "expected_entity_version": task["entity_version"]}
            remaining = task["required_effort_units"] - task["completed_effort_units"]
            offset = 0 if mine else 1
            blocked = not task["dependencies_ready"] and perms["dependency_mode"] == "forbid"
            view = {"task_id": task["task_id"], "root_task_id": task["root_task_id"], "actor_id": actor_id, "is_root": task["parent_id"] is None, "importance": task["importance"]}
            value = 10 + (10 if task["importance"] == "high" else 0) + max(0, 10 - (task["deadline_tick"] - tick))
            if free:
                first = Proposal(actor_id, "take_task", dict(ref))
            elif (task.get("open_defects") or 0) > 0:
                first = Proposal(actor_id, "fix_task", dict(ref))
            elif remaining > 0:
                first = Proposal(actor_id, "work_task", {**ref, "effort_units": 1})
            else:
                first = Proposal(actor_id, "request_acceptance", dict(ref))
            if not blocked:
                accept_at = offset + remaining
                steps = [PlanStep("task.work_done", {**view, "effort_units": 1}, offset + k) for k in range(remaining)]
                steps.append(PlanStep("task.accepted", {**view, "root_accepted": view["is_root"], "late_ticks": max(0, tick + accept_at - task["deadline_tick"]), "defects_fixed": 0, "team_wip": observation["team_wip"], "wip_limit": observation["wip_limit"]}, accept_at))
                options.append(PlanOption(f"deliver:{task['task_id']}", f"Сделать {task['task_id']}", first, tuple(steps), accept_at + 1, value))
            if mine and not task["declared_done"]:
                steps = (PlanStep("task.declared_done", {**view, "work_complete": remaining <= 0}, 0),)
                options.append(PlanOption(f"declare:{task['task_id']}", f"Отметить {task['task_id']} готовой", Proposal(actor_id, "declare_done", dict(ref)), steps, 1, -value if remaining > 0 else 1, harms_business=remaining > 0))
            if mine and perms["split"] and remaining > 0 and task["depth"] < perms["split_max_depth"]:
                parts = min(perms["split_max_children"], remaining + perms["split_overhead_units"])
                if parts >= 2:
                    steps = tuple(PlanStep("task.declared_done", {**view, "task_id": f"{task['task_id']}.{k + 1}", "is_root": False, "work_complete": False}, 1 + k) for k in range(parts))
                    options.append(PlanOption(f"split_declare:{task['task_id']}", f"Разбить {task['task_id']} и отмечать части", Proposal(actor_id, "split_task", {**ref, "parts": parts}), steps, parts + 1, -value, harms_business=True))
        return options
