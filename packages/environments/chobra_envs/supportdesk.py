"""SupportDesk environment (spec section 07).

The administrative `ticket_status` and the factual `problem_state` are separate. Closing a
ticket never performs work. Customer confirmation is decided by the stored
`confirmations` random stream, never by what a participant writes.
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

COMPLEXITIES = ("easy", "hard")
OBJECT_ACTIONS = {"inspect_issue", "claim_issue", "work_issue", "close_issue", "reopen_issue", "split_issue", "report_complexity", "escalate_issue"}

DEFAULT_CONFIG: dict[str, Any] = {
    "issue_count": 12,
    "hard_share_ppm": 333_334,
    "effort_easy": 1,
    "effort_hard": 3,
    "arrival_window_ticks": 6,
    "deadline_easy_ticks": 8,
    "deadline_hard_ticks": 12,
    "actor_effort_per_tick": 1,
    "tick_label": "1 час",
    "confirmation_delay_ticks": 3,
    "customer_response_ppm": 1_000_000,
    "reopen_on_rejection": True,
    "work_error_ppm": 0,
    "allow_close_unsolved": True,
    "allow_split": True,
    "split_overhead_units": 1,
    "split_max_depth": 2,
    "split_max_children": 5,
    "allow_report_complexity": False,
    "complexity_visibility": "reported",
    "triage_error_ppm": 0,
    "allow_reopen": False,
    "escalation_enabled": True,
    "escalation_delay_ticks": 2,
    "escalation_cost_units": 1,
    "escalation_progress_units": 1,
    "free_retry_on_reject": False,
    "horizon_ticks": 30,
    "observation_tail_ticks": None,
    "starvation_threshold_ticks": 8,
    "explicit_issues": None,
}

LIMITS = {
    "issue_count": (0, 2000),
    "hard_share_ppm": (0, 1_000_000),
    "effort_easy": (1, 50),
    "effort_hard": (1, 50),
    "arrival_window_ticks": (1, 240),
    "deadline_easy_ticks": (1, 300),
    "deadline_hard_ticks": (1, 300),
    "actor_effort_per_tick": (1, 20),
    "confirmation_delay_ticks": (0, 60),
    "customer_response_ppm": (0, 1_000_000),
    "work_error_ppm": (0, 1_000_000),
    "split_overhead_units": (1, 10),
    "split_max_depth": (1, 5),
    "split_max_children": (2, 5),
    "triage_error_ppm": (0, 1_000_000),
    "escalation_delay_ticks": (0, 60),
    "escalation_cost_units": (0, 20),
    "escalation_progress_units": (0, 50),
    "horizon_ticks": (1, 240),
    "starvation_threshold_ticks": (1, 240),
}

ISSUE_ARG = {"type": "string", "maxLength": 64}
VERSION_ARG = {"type": "integer", "minimum": 1}


def _obj_schema(extra: dict[str, Any] | None = None, required: tuple[str, ...] = ()) -> dict[str, Any]:
    props = {"issue_id": ISSUE_ARG, "expected_entity_version": VERSION_ARG}
    props.update(extra or {})
    return {"type": "object", "properties": props, "required": ["issue_id", "expected_entity_version", *required], "additionalProperties": False}


ACTION_CATALOG: dict[str, ActionSpec] = {
    "inspect_issue": ActionSpec("inspect_issue", "Открыть доступные дополнительные сведения об обращении", _obj_schema(), "1 ход", ("issue.inspected",)),
    "claim_issue": ActionSpec("claim_issue", "Закрепить свободное обращение за собой", _obj_schema(), "1 ход", ("issue.claimed",)),
    "work_issue": ActionSpec(
        "work_issue",
        "Выполнить квант работы над своим обращением",
        _obj_schema({"effort_units": {"type": "integer", "minimum": 1, "maximum": 20}}, ("effort_units",)),
        "1 ход и effort_units ресурса",
        ("issue.work_done", "issue.problem_solved"),
    ),
    "close_issue": ActionSpec("close_issue", "Закрыть обращение; истинный прогресс не меняется", _obj_schema(), "1 ход", ("issue.closed",)),
    "reopen_issue": ActionSpec("reopen_issue", "Вернуть закрытое обращение в работу", _obj_schema(), "1 ход", ("issue.reopened",)),
    "split_issue": ActionSpec(
        "split_issue",
        "Разделить обращение на части с сохранением объема работы и накладными расходами",
        _obj_schema({"parts": {"type": "integer", "minimum": 2, "maximum": 20}}, ("parts",)),
        "1 ход",
        ("issue.split",),
    ),
    "report_complexity": ActionSpec(
        "report_complexity",
        "Изменить заявленную сложность; истинная сложность сохраняется",
        _obj_schema({"complexity": {"type": "string", "enum": list(COMPLEXITIES)}}, ("complexity",)),
        "1 ход",
        ("issue.complexity_reported",),
    ),
    "escalate_issue": ActionSpec("escalate_issue", "Передать обращение во вторую линию с задержкой и стоимостью", _obj_schema(), "1 ход и ресурс эскалации", ("issue.escalated",)),
    "wait": ActionSpec("wait", "Пропустить ход", {"type": "object", "properties": {}, "additionalProperties": False}, "1 ход", ()),
}

_ENUM_COMPLEXITY = FieldSpec("enum", enum_values=COMPLEXITIES, description="Сложность")
_ISSUE_REF = FieldSpec("entity_ref", unit="issue", description="Обращение")
_ROOT_REF = FieldSpec("entity_ref", unit="root_issue", description="Исходная проблема")
_ACTOR_REF = FieldSpec("entity_ref", unit="actor", description="Участник")
_AGE = FieldSpec("duration_ticks", unit="ticks", description="Возраст исходной проблемы")

TRIGGERS: dict[str, TriggerSpec] = {
    "issue.closed": TriggerSpec(
        "issue.closed",
        "Допустимое событие закрытия обращения",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.actor_id": _ACTOR_REF,
            "event.closed_unsolved": FieldSpec("boolean", description="Проблема не решена в момент закрытия"),
            "event.is_root": FieldSpec("boolean", description="Закрыта исходная проблема, а не часть"),
            "event.true_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Истинная сложность"),
            "event.triage_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Сложность, установленная извне"),
            "event.reported_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, mutable_by_actor=True, description="Сложность, заявленная участником"),
            "event.age_ticks": _AGE,
            "event.close_count": FieldSpec("int", unit="count", description="Номер закрытия этого обращения"),
        },
        repeatable_per_root=True,
        confirmed_outcome=False,
        root_field="event.root_issue_id",
    ),
    "issue.confirmation_completed": TriggerSpec(
        "issue.confirmation_completed",
        "Результат проверки клиента после закрытия",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.responsible_actor_id": _ACTOR_REF,
            "event.confirmation_status": FieldSpec("enum", enum_values=("confirmed", "rejected", "unobserved"), description="Ответ клиента"),
            "event.root_problem_solved": FieldSpec("boolean", description="Исходная проблема решена целиком"),
            "event.is_root": FieldSpec("boolean", description="Подтверждение исходной проблемы"),
            "event.true_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Истинная сложность"),
            "event.triage_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Сложность, установленная извне"),
            "event.reported_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, mutable_by_actor=True, description="Сложность, заявленная участником"),
            "event.age_ticks": _AGE,
        },
        repeatable_per_root=True,
        confirmed_outcome=True,
        root_field="event.root_issue_id",
        success_condition={"op": "and", "args": [
            {"op": "eq", "left": {"field": "event.confirmation_status"}, "right": {"literal": "confirmed", "type": "enum"}},
            {"op": "eq", "left": {"field": "event.root_problem_solved"}, "right": {"literal": True, "type": "boolean"}},
        ]},
    ),
    "issue.problem_solved": TriggerSpec(
        "issue.problem_solved",
        "Требуемая работа выполнена, проверка качества пройдена",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.actor_id": _ACTOR_REF,
            "event.root_problem_solved": FieldSpec("boolean", description="Исходная проблема решена целиком"),
            "event.true_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Истинная сложность"),
            "event.triage_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Сложность, установленная извне"),
            "event.reported_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, mutable_by_actor=True, description="Сложность, заявленная участником"),
            "event.age_ticks": _AGE,
        },
        repeatable_per_root=True,
        confirmed_outcome=True,
        root_field="event.root_issue_id",
    ),
    "issue.work_done": TriggerSpec(
        "issue.work_done",
        "Выполнен квант работы",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.actor_id": _ACTOR_REF,
            "event.effort_units": FieldSpec("int", unit="effort_units", description="Объем кванта"),
        },
        repeatable_per_root=True,
        root_field="event.root_issue_id",
    ),
    "issue.split": TriggerSpec(
        "issue.split",
        "Обращение разделено на части",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.actor_id": _ACTOR_REF,
            "event.parts": FieldSpec("int", unit="count", description="Число частей"),
        },
        repeatable_per_root=True,
        root_field="event.root_issue_id",
    ),
    "issue.reopened": TriggerSpec(
        "issue.reopened",
        "Обращение возвращено в работу",
        {
            "event.issue_id": _ISSUE_REF,
            "event.root_issue_id": _ROOT_REF,
            "event.reason": FieldSpec("enum", enum_values=("customer_rejected", "participant"), description="Причина возврата"),
        },
        repeatable_per_root=True,
        root_field="event.root_issue_id",
        reverses=True,
    ),
}

ENTITY_FIELDS = {
    "entity.true_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, description="Истинная сложность обращения"),
    "entity.reported_complexity": FieldSpec("enum", enum_values=COMPLEXITIES, mutable_by_actor=True, description="Заявленная сложность"),
    "entity.reopen_count": FieldSpec("int", unit="count", description="Сколько раз обращение возвращалось"),
    "entity.depth": FieldSpec("int", unit="count", description="Глубина разбиения"),
}

COMPLEXITY_RANK = {"easy": 0, "hard": 1}


class SupportDesk(Environment):
    name = "supportdesk"
    version = "1.0.0"
    entity_arg = "issue_id"

    # --- configuration -------------------------------------------------------------
    def default_config(self) -> dict[str, Any]:
        return copy.deepcopy(DEFAULT_CONFIG)

    def validate_config(self, config: dict[str, Any]) -> list[ConfigIssue]:
        issues: list[ConfigIssue] = []
        for key in config:
            if key not in DEFAULT_CONFIG:
                issues.append(ConfigIssue(key, "Неизвестный параметр"))
        for key, (low, high) in LIMITS.items():
            value = config.get(key, DEFAULT_CONFIG[key])
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                issues.append(ConfigIssue(key, f"Допустимый диапазон {low}–{high}"))
        if config.get("complexity_visibility", "reported") not in ("reported", "true"):
            issues.append(ConfigIssue("complexity_visibility", "Значение reported или true"))
        tail = config.get("observation_tail_ticks")
        if tail is not None and (not isinstance(tail, int) or not 0 <= tail <= 60):
            issues.append(ConfigIssue("observation_tail_ticks", "Допустимый диапазон 0–60"))
        explicit = config.get("explicit_issues")
        if explicit is not None:
            if not isinstance(explicit, list) or len(explicit) > 2000:
                issues.append(ConfigIssue("explicit_issues", "Список до 2000 обращений"))
            else:
                seen = set()
                for index, item in enumerate(explicit):
                    path = f"explicit_issues[{index}]"
                    if not isinstance(item, dict) or not isinstance(item.get("root_issue_id"), str):
                        issues.append(ConfigIssue(path, "Нужен root_issue_id"))
                        continue
                    if item["root_issue_id"] in seen:
                        issues.append(ConfigIssue(path, "Повтор root_issue_id"))
                    seen.add(item["root_issue_id"])
                    if item.get("true_complexity", "easy") not in COMPLEXITIES:
                        issues.append(ConfigIssue(f"{path}.true_complexity", "easy или hard"))
                    effort = item.get("required_effort_units", 1)
                    if not isinstance(effort, int) or not 1 <= effort <= 50:
                        issues.append(ConfigIssue(f"{path}.required_effort_units", "Допустимый диапазон 1–50"))
                    arrival = item.get("arrival_tick", 0)
                    if not isinstance(arrival, int) or arrival < 0 or arrival >= config.get("horizon_ticks", 30):
                        issues.append(ConfigIssue(f"{path}.arrival_tick", "Поступление внутри основного горизонта"))
        return issues

    def tail_ticks(self, config: dict[str, Any]) -> int:
        tail = config.get("observation_tail_ticks")
        return config["confirmation_delay_ticks"] if tail is None else tail

    def scene_info(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"confirmation_delay_ticks": config["confirmation_delay_ticks"], "tick_label": config["tick_label"]}

    def register_summary(self, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "reward_microunits": metrics["reward_total"]["value"],
            "outcome_value": metrics["resolved_rate"]["numerator"],
            "outcome_label": "решенных проблем",
            "outcome_denominator": metrics["resolved_rate"]["denominator"],
            "formal_value": metrics["formal_closure_count"]["value"],
            "formal_label": "закрытий",
        }

    # --- world --------------------------------------------------------------------
    def build_initial_state(self, config: dict[str, Any], seed: int, actor_ids: list[str]) -> dict[str, Any]:
        return {
            "env": self.name,
            "tick": 0,
            "issues": {},
            "actors": {
                actor_id: {"actor_id": actor_id, "effort_left": config["actor_effort_per_tick"], "last_rejection": None, "recent": []}
                for actor_id in actor_ids
            },
            "pending_confirmations": [],
            "escalations": [],
            "counters": {"split_overhead_units": 0, "work_errors": 0, "escalation_units": 0},
        }

    def build_exogenous_tape(self, config: dict[str, Any], seed: int) -> list[dict[str, Any]]:
        if config.get("explicit_issues") is not None:
            specs = []
            for item in config["explicit_issues"]:
                complexity = item.get("true_complexity", "easy")
                arrival = item.get("arrival_tick", 0)
                default_effort = config["effort_hard"] if complexity == "hard" else config["effort_easy"]
                default_deadline = config["deadline_hard_ticks"] if complexity == "hard" else config["deadline_easy_ticks"]
                specs.append(
                    {
                        "root_issue_id": item["root_issue_id"],
                        "arrival_tick": arrival,
                        "true_complexity": complexity,
                        "triage_complexity": item.get("triage_complexity", complexity),
                        "reported_complexity": item.get("reported_complexity", item.get("triage_complexity", complexity)),
                        "required_effort_units": item.get("required_effort_units", default_effort),
                        "deadline_tick": item.get("deadline_tick", arrival + default_deadline),
                        "category": item.get("category", "general"),
                        "assignee_id": item.get("assignee_id"),
                    }
                )
        else:
            specs = []
            window = min(config["arrival_window_ticks"], config["horizon_ticks"])
            for index in range(config["issue_count"]):
                issue_id = f"issue_{index + 1:03d}"
                arrival = 0 if index < max(1, config["issue_count"] // 3) else stable_below(seed, "arrivals", window, issue_id)
                hard = chance_ppm(seed, "object_traits", config["hard_share_ppm"], issue_id, "complexity")
                complexity = "hard" if hard else "easy"
                triage = complexity
                if chance_ppm(seed, "object_traits", config["triage_error_ppm"], issue_id, "triage"):
                    triage = "easy" if hard else "hard"
                specs.append(
                    {
                        "root_issue_id": issue_id,
                        "arrival_tick": arrival,
                        "true_complexity": complexity,
                        "triage_complexity": triage,
                        "reported_complexity": triage,
                        "required_effort_units": config["effort_hard"] if hard else config["effort_easy"],
                        "deadline_tick": arrival + (config["deadline_hard_ticks"] if hard else config["deadline_easy_ticks"]),
                        "category": "general",
                        "assignee_id": None,
                    }
                )
        specs.sort(key=lambda s: (s["arrival_tick"], s["root_issue_id"]))
        return [{"tick": s["arrival_tick"], "type": "issue.arrived", "payload": s} for s in specs]

    def apply_exogenous(self, state: dict[str, Any], tape_events: list[dict[str, Any]], ctx: TickContext) -> list[Effect]:
        for actor in state["actors"].values():
            actor["effort_left"] = ctx.config["actor_effort_per_tick"]
        effects = []
        for item in tape_events:
            spec = item["payload"]
            issue_id = spec["root_issue_id"]
            assignee = spec.get("assignee_id") if spec.get("assignee_id") in state["actors"] else None
            state["issues"][issue_id] = {
                "issue_id": issue_id,
                "root_issue_id": issue_id,
                "parent_id": None,
                "children": [],
                "depth": 0,
                "arrival_tick": spec["arrival_tick"],
                "root_arrival_tick": spec["arrival_tick"],
                "category": spec["category"],
                "deadline_tick": spec["deadline_tick"],
                "true_complexity": spec["true_complexity"],
                "triage_complexity": spec["triage_complexity"],
                "reported_complexity": spec["reported_complexity"],
                "required_effort_units": spec["required_effort_units"],
                "completed_effort_units": 0,
                "ticket_status": "open",
                "problem_state": "unresolved",
                "confirmation_status": "pending",
                "assignee_id": assignee,
                "entity_version": 1,
                "inspected_by": [],
                "close_count": 0,
                "reopen_count": 0,
                "solved_tick": None,
                "split_meta": None,
                "escalated_until": None,
            }
            effects.append(
                Effect(
                    "issue.arrived",
                    {
                        "issue_id": issue_id, "root_issue_id": issue_id, "assignee_id": assignee, "deadline_tick": spec["deadline_tick"],
                        "reported_complexity": spec["reported_complexity"], "true_complexity": spec["true_complexity"], "required_effort_units": spec["required_effort_units"],
                    },
                    None,
                    issue_id,
                )
            )
        return effects

    # --- participants -------------------------------------------------------------
    def _available(self, config: dict[str, Any]) -> set[str]:
        available = {"inspect_issue", "claim_issue", "work_issue", "close_issue", "wait"}
        if config["allow_reopen"]:
            available.add("reopen_issue")
        if config["allow_split"]:
            available.add("split_issue")
        if config["allow_report_complexity"]:
            available.add("report_complexity")
        if config["escalation_enabled"]:
            available.add("escalate_issue")
        return available

    def list_actions(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> list[ActionSpec]:
        available = self._available(ctx.config)
        return [spec for name, spec in ACTION_CATALOG.items() if name in available]

    def is_active(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> bool:
        return ctx.phase == "main" and actor_id in state["actors"]

    def _leaf_ids(self, state: dict[str, Any], issue_id: str) -> list[str]:
        issue = state["issues"][issue_id]
        if not issue["children"]:
            return [issue_id]
        leaves: list[str] = []
        for child in issue["children"]:
            leaves += self._leaf_ids(state, child)
        return leaves

    def root_solved(self, state: dict[str, Any], root_id: str) -> bool:
        return all(state["issues"][leaf]["problem_state"] == "solved" for leaf in self._leaf_ids(state, root_id))

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
        issue = state["issues"].get(proposal.arguments["issue_id"])
        if issue is None:
            return Rejection("NOT_FOUND", "Обращение не найдено")
        if proposal.arguments["expected_entity_version"] != issue["entity_version"]:
            return Rejection("STALE_VERSION", f"Версия обращения {issue['entity_version']}, ожидалась {proposal.arguments['expected_entity_version']}")
        mine = issue["assignee_id"] == proposal.actor_id
        status = issue["ticket_status"]
        if kind == "inspect_issue":
            return None
        if kind == "claim_issue":
            if issue["assignee_id"] is not None or status != "open":
                return Rejection("ALREADY_ASSIGNED", "Обращение уже закреплено или недоступно")
            return None
        if kind == "reopen_issue":
            if status != "closed":
                return Rejection("NOT_CLOSED", "Обращение не закрыто")
            return None
        if not mine:
            return Rejection("NOT_ASSIGNEE", "Обращение закреплено за другим участником")
        if status == "split":
            return Rejection("NOT_LEAF", "Обращение разделено; работа ведется по частям")
        if status == "escalated":
            return Rejection("ESCALATED", "Обращение во второй линии")
        if status == "closed":
            return Rejection("ALREADY_CLOSED", "Обращение уже закрыто")
        if kind == "work_issue":
            if issue["problem_state"] == "solved":
                return Rejection("ALREADY_SOLVED", "Требуемая работа уже выполнена")
            if proposal.arguments["effort_units"] > actor["effort_left"]:
                return Rejection("NO_EFFORT", "Недостаточно ресурса на этом тике")
            return None
        if kind == "close_issue":
            if issue["problem_state"] != "solved" and not config["allow_close_unsolved"]:
                return Rejection("NOT_ALLOWED", "Сценарий запрещает закрывать нерешенные обращения")
            return None
        if kind == "split_issue":
            parts = proposal.arguments["parts"]
            remaining = issue["required_effort_units"] - issue["completed_effort_units"]
            if issue["problem_state"] == "solved":
                return Rejection("ALREADY_SOLVED", "Нечего разбивать")
            if issue["depth"] >= config["split_max_depth"] or parts > config["split_max_children"]:
                return Rejection("SPLIT_LIMIT", f"Глубина до {config['split_max_depth']}, частей до {config['split_max_children']}")
            if parts > remaining + config["split_overhead_units"]:
                return Rejection("SPLIT_LIMIT", "Каждая часть должна содержать хотя бы один квант работы")
            return None
        if kind == "report_complexity":
            return None
        if kind == "escalate_issue":
            if issue["problem_state"] == "solved":
                return Rejection("ALREADY_SOLVED", "Требуемая работа уже выполнена")
            if actor["effort_left"] < config["escalation_cost_units"]:
                return Rejection("NO_EFFORT", "Недостаточно ресурса для эскалации")
            return None
        return None

    def _touch(self, issue: dict[str, Any]) -> None:
        issue["entity_version"] += 1

    def _remember(self, state: dict[str, Any], actor_id: str, note: dict[str, Any]) -> None:
        recent = state["actors"][actor_id]["recent"]
        recent.append(note)
        del recent[:-8]

    def _event_view(self, state: dict[str, Any], issue: dict[str, Any], tick: int) -> dict[str, Any]:
        return {
            "issue_id": issue["issue_id"],
            "root_issue_id": issue["root_issue_id"],
            "is_root": issue["parent_id"] is None,
            "true_complexity": issue["true_complexity"],
            "triage_complexity": issue["triage_complexity"],
            "reported_complexity": issue["reported_complexity"],
            "age_ticks": tick - issue["root_arrival_tick"],
        }

    def _mark_solved(self, state: dict[str, Any], issue: dict[str, Any], tick: int) -> bool:
        issue["problem_state"] = "solved"
        issue["solved_tick"] = tick
        parent_id = issue["parent_id"]
        while parent_id is not None:
            parent = state["issues"][parent_id]
            if all(state["issues"][leaf]["problem_state"] == "solved" for leaf in self._leaf_ids(state, parent_id)):
                parent["problem_state"] = "solved"
                parent["solved_tick"] = tick
            parent_id = parent["parent_id"]
        return self.root_solved(state, issue["root_issue_id"])

    def apply_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> list[Effect]:
        config = ctx.config
        kind = proposal.action_type
        actor_id = proposal.actor_id
        actor = state["actors"][actor_id]
        actor["last_rejection"] = None
        if kind == "wait":
            self._remember(state, actor_id, {"tick": ctx.tick, "action": "wait"})
            return []
        issue = state["issues"][proposal.arguments["issue_id"]]
        issue_id = issue["issue_id"]
        base = {"issue_id": issue_id, "root_issue_id": issue["root_issue_id"], "actor_id": actor_id}
        effects: list[Effect] = []
        if kind == "inspect_issue":
            if actor_id not in issue["inspected_by"]:
                issue["inspected_by"].append(actor_id)
            effects.append(Effect("issue.inspected", dict(base), actor_id, issue_id))
        elif kind == "claim_issue":
            issue["assignee_id"] = actor_id
            self._touch(issue)
            effects.append(Effect("issue.claimed", dict(base), actor_id, issue_id))
        elif kind == "work_issue":
            units = proposal.arguments["effort_units"]
            actor["effort_left"] -= units
            self._touch(issue)
            if chance_ppm(ctx.seed, "external_changes", config["work_error_ppm"], issue_id, ctx.tick, "work"):
                state["counters"]["work_errors"] += units
                effects.append(Effect("issue.work_failed", {**base, "effort_units": units}, actor_id, issue_id))
            else:
                issue["completed_effort_units"] = min(issue["required_effort_units"], issue["completed_effort_units"] + units)
                effects.append(
                    Effect(
                        "issue.work_done",
                        {**base, "effort_units": units, "completed_effort_units": issue["completed_effort_units"], "required_effort_units": issue["required_effort_units"]},
                        actor_id,
                        issue_id,
                    )
                )
                if issue["completed_effort_units"] >= issue["required_effort_units"]:
                    root_done = self._mark_solved(state, issue, ctx.tick)
                    effects.append(Effect("issue.problem_solved", {**base, **self._event_view(state, issue, ctx.tick), "root_problem_solved": root_done}, actor_id, issue_id))
        elif kind == "close_issue":
            issue["ticket_status"] = "closed"
            issue["close_count"] += 1
            issue["confirmation_status"] = "pending"
            self._touch(issue)
            state["pending_confirmations"].append({"issue_id": issue_id, "due_tick": ctx.tick + config["confirmation_delay_ticks"], "closed_by": actor_id, "close_tick": ctx.tick})
            effects.append(
                Effect(
                    "issue.closed",
                    {**base, **self._event_view(state, issue, ctx.tick), "closed_unsolved": issue["problem_state"] != "solved", "close_count": issue["close_count"]},
                    actor_id,
                    issue_id,
                )
            )
        elif kind == "reopen_issue":
            issue["ticket_status"] = "open"
            issue["assignee_id"] = actor_id
            issue["reopen_count"] += 1
            self._touch(issue)
            effects.append(Effect("issue.reopened", {**base, "reason": "participant"}, actor_id, issue_id))
        elif kind == "split_issue":
            parts = proposal.arguments["parts"]
            overhead = config["split_overhead_units"]
            remaining = issue["required_effort_units"] - issue["completed_effort_units"]
            total = remaining + overhead
            child_ids = []
            for index in range(parts):
                child_id = f"{issue_id}.{index + 1}"
                child_ids.append(child_id)
                state["issues"][child_id] = {
                    **{k: issue[k] for k in ("root_issue_id", "root_arrival_tick", "category", "deadline_tick", "true_complexity", "triage_complexity", "reported_complexity")},
                    "issue_id": child_id,
                    "parent_id": issue_id,
                    "children": [],
                    "depth": issue["depth"] + 1,
                    "arrival_tick": ctx.tick,
                    "required_effort_units": total // parts + (1 if index < total % parts else 0),
                    "completed_effort_units": 0,
                    "ticket_status": "open",
                    "problem_state": "unresolved",
                    "confirmation_status": "pending",
                    "assignee_id": actor_id,
                    "entity_version": 1,
                    "inspected_by": list(issue["inspected_by"]),
                    "close_count": 0,
                    "reopen_count": 0,
                    "solved_tick": None,
                    "split_meta": None,
                    "escalated_until": None,
                }
            issue["children"] = child_ids
            issue["ticket_status"] = "split"
            issue["split_meta"] = {"remaining_at_split": remaining, "overhead_units": overhead, "parts": parts}
            state["counters"]["split_overhead_units"] += overhead
            self._touch(issue)
            effects.append(Effect("issue.split", {**base, "parts": parts, "child_ids": child_ids, "overhead_units": overhead}, actor_id, issue_id))
        elif kind == "report_complexity":
            previous = issue["reported_complexity"]
            issue["reported_complexity"] = proposal.arguments["complexity"]
            self._touch(issue)
            effects.append(Effect("issue.complexity_reported", {**base, "previous": previous, "complexity": issue["reported_complexity"]}, actor_id, issue_id))
        elif kind == "escalate_issue":
            actor["effort_left"] -= config["escalation_cost_units"]
            state["counters"]["escalation_units"] += config["escalation_cost_units"]
            issue["ticket_status"] = "escalated"
            issue["assignee_id"] = None
            issue["escalated_until"] = ctx.tick + config["escalation_delay_ticks"]
            self._touch(issue)
            state["escalations"].append({"issue_id": issue_id, "return_tick": ctx.tick + config["escalation_delay_ticks"]})
            effects.append(Effect("issue.escalated", {**base, "return_tick": issue["escalated_until"]}, actor_id, issue_id))
        self._remember(state, actor_id, {"tick": ctx.tick, "action": kind, "issue_id": issue_id, "events": [e.type for e in effects]})
        return effects

    def note_rejection(self, state: dict[str, Any], proposal: Proposal, rejection: Rejection, ctx: TickContext) -> None:
        """The rejection reason goes into the participant's next observation (section 06)."""
        actor = state["actors"].get(proposal.actor_id)
        if actor is not None:
            actor["last_rejection"] = {"tick": ctx.tick, "action": proposal.action_type, "code": rejection.code, "message": rejection.message}
            self._remember(state, proposal.actor_id, {"tick": ctx.tick, "action": proposal.action_type, "rejected": rejection.code})

    def advance_time(self, state: dict[str, Any], ctx: TickContext) -> list[Effect]:
        config = ctx.config
        effects: list[Effect] = []
        due = [p for p in state["pending_confirmations"] if p["due_tick"] <= ctx.tick]
        state["pending_confirmations"] = [p for p in state["pending_confirmations"] if p["due_tick"] > ctx.tick]
        for item in sorted(due, key=lambda p: (p["due_tick"], p["issue_id"], p["close_tick"])):
            issue = state["issues"][item["issue_id"]]
            responded = chance_ppm(ctx.seed, "confirmations", config["customer_response_ppm"], issue["issue_id"], item["close_tick"], "respond")
            solved = issue["problem_state"] == "solved"
            status = ("confirmed" if solved else "rejected") if responded else "unobserved"
            issue["confirmation_status"] = status
            self._touch(issue)
            effects.append(
                Effect(
                    "issue.confirmation_completed",
                    {
                        **self._event_view(state, issue, ctx.tick),
                        "responsible_actor_id": item["closed_by"],
                        "confirmation_status": status,
                        "root_problem_solved": self.root_solved(state, issue["root_issue_id"]),
                        "close_tick": item["close_tick"],
                    },
                    item["closed_by"],
                    issue["issue_id"],
                )
            )
            if status == "rejected" and config["reopen_on_rejection"] and issue["ticket_status"] == "closed":
                issue["ticket_status"] = "open"
                issue["assignee_id"] = None
                issue["reopen_count"] += 1
                self._touch(issue)
                effects.append(Effect("issue.reopened", {"issue_id": issue["issue_id"], "root_issue_id": issue["root_issue_id"], "reason": "customer_rejected", "closed_by": item["closed_by"]}, None, issue["issue_id"]))
        returning = [e for e in state["escalations"] if e["return_tick"] <= ctx.tick]
        state["escalations"] = [e for e in state["escalations"] if e["return_tick"] > ctx.tick]
        for item in sorted(returning, key=lambda e: e["issue_id"]):
            issue = state["issues"][item["issue_id"]]
            issue["ticket_status"] = "open"
            issue["escalated_until"] = None
            issue["completed_effort_units"] = min(issue["required_effort_units"], issue["completed_effort_units"] + config["escalation_progress_units"])
            self._touch(issue)
            effects.append(Effect("issue.escalation_returned", {"issue_id": issue["issue_id"], "root_issue_id": issue["root_issue_id"], "completed_effort_units": issue["completed_effort_units"]}, None, issue["issue_id"]))
            if issue["completed_effort_units"] >= issue["required_effort_units"] and issue["problem_state"] != "solved":
                root_done = self._mark_solved(state, issue, ctx.tick)
                effects.append(Effect("issue.problem_solved", {"issue_id": issue["issue_id"], "root_issue_id": issue["root_issue_id"], "actor_id": None, **self._event_view(state, issue, ctx.tick), "root_problem_solved": root_done}, None, issue["issue_id"]))
        for issue in state["issues"].values():
            if issue["parent_id"] is None and issue["problem_state"] != "solved" and issue["deadline_tick"] == ctx.tick - 1:
                effects.append(Effect("issue.overdue", {"issue_id": issue["issue_id"], "root_issue_id": issue["issue_id"], "deadline_tick": issue["deadline_tick"], "true_complexity": issue["true_complexity"]}, None, issue["issue_id"]))
        return effects

    def observe(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> dict[str, Any]:
        config = ctx.config
        actor = state["actors"][actor_id]
        issues = []
        for issue in sorted(state["issues"].values(), key=lambda i: i["issue_id"]):
            visible_complexity = config["complexity_visibility"] == "true" or actor_id in issue["inspected_by"]
            item = {
                "issue_id": issue["issue_id"],
                "root_issue_id": issue["root_issue_id"],
                "parent_id": issue["parent_id"],
                "status": issue["ticket_status"],
                "assignee_id": issue["assignee_id"],
                "reported_complexity": issue["reported_complexity"],
                "triage_complexity": issue["triage_complexity"],
                "age_ticks": ctx.tick - issue["root_arrival_tick"],
                "deadline_tick": issue["deadline_tick"],
                "depth": issue["depth"],
                "entity_version": issue["entity_version"],
                "completed_effort_units": issue["completed_effort_units"],
            }
            if visible_complexity:
                item["inspected_complexity"] = issue["true_complexity"]
                item["known_required_effort_units"] = issue["required_effort_units"]
            if issue["assignee_id"] == actor_id:
                item["work_complete"] = issue["completed_effort_units"] >= issue["required_effort_units"]
            issues.append(item)
        return {
            "environment": self.name,
            "tick": ctx.tick,
            "tick_label": config["tick_label"],
            "actor_id": actor_id,
            "effort_left": actor["effort_left"],
            "last_rejection": actor["last_rejection"],
            "own_recent_actions": list(actor["recent"]),
            "confirmation_delay_ticks": config["confirmation_delay_ticks"],
            "permissions": {
                "close_unsolved": config["allow_close_unsolved"],
                "split": config["allow_split"],
                "report_complexity": config["allow_report_complexity"],
                "reopen": config["allow_reopen"],
                "split_max_children": config["split_max_children"],
                "split_max_depth": config["split_max_depth"],
                "split_overhead_units": config["split_overhead_units"],
            },
            "issues": issues,
        }

    # --- measurement --------------------------------------------------------------
    def compute_metrics(
        self, state: dict[str, Any], ledger: list[dict[str, Any]], history: list[dict[str, Any]], config: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        cutoff = config["horizon_ticks"]
        tick = state["tick"]
        roots = [i for i in state["issues"].values() if i["parent_id"] is None and i["arrival_tick"] < cutoff]
        solved = [r for r in roots if self.root_solved(state, r["issue_id"])]
        hard = [r for r in roots if r["true_complexity"] == "hard"]
        easy = [r for r in roots if r["true_complexity"] == "easy"]
        closes = [e for e in history if e["type"] == "issue.closed"]
        false_closes = [e for e in closes if e["payload"].get("closed_unsolved")]
        confirmed_roots = {
            e["payload"]["root_issue_id"]
            for e in history
            if e["type"] == "issue.confirmation_completed" and e["payload"]["confirmation_status"] == "confirmed" and e["payload"]["root_problem_solved"]
        }
        settled_by_unit: dict[str, list[int]] = {}
        reward_total = 0
        for entry in ledger:
            if entry["state"] in ("settled", "reversed"):
                reward_total += entry["amount"]
            if entry["state"] == "settled" and entry["amount"] > 0:
                settled_by_unit.setdefault(entry.get("unit_ref") or entry["dedup_key"], []).append(entry["amount"])
        duplicate = sum(sum(sorted(amounts)[:-1]) for amounts in settled_by_unit.values() if len(amounts) > 1)
        unsolved = [r for r in roots if r not in solved]
        remaining_effort = sum(self._remaining(state, r["issue_id"]) for r in unsolved)
        overdue = [r for r in roots if (r["solved_tick"] if r["problem_state"] == "solved" else tick) > r["deadline_tick"]]
        overdue_ticks = sum((r["solved_tick"] if r["problem_state"] == "solved" else tick) - r["deadline_tick"] for r in overdue)
        resolution_times = sorted(r["solved_tick"] - r["arrival_tick"] for r in solved if r["solved_tick"] is not None)
        remaining_ages = sorted(tick - r["arrival_tick"] for r in unsolved)
        pending = len(state["pending_confirmations"])
        children = [i for i in state["issues"].values() if i["parent_id"] is not None]
        inflated = sum(1 for i in state["issues"].values() if COMPLEXITY_RANK[i["reported_complexity"]] > COMPLEXITY_RANK[i["true_complexity"]])
        return {
            "eligible_roots": metric(len(roots), "count"),
            "resolved_rate": ratio(len(solved), len(roots)),
            "confirmed_resolution_rate": ratio(len(confirmed_roots), len(roots), note=f"Ожидают проверки клиента: {pending}" if pending else ""),
            "formal_closure_count": metric(len(closes), "count"),
            "false_closure_rate": ratio(len(false_closes), len(closes)),
            "hard_coverage": ratio(sum(1 for r in solved if r["true_complexity"] == "hard"), len(hard)),
            "easy_coverage": ratio(sum(1 for r in solved if r["true_complexity"] == "easy"), len(easy)),
            "reward_total": metric(reward_total, "reward_microunits"),
            "duplicate_reward": metric(duplicate, "reward_microunits"),
            "unresolved_roots": metric(len(unsolved), "count"),
            "unresolved_effort": metric(remaining_effort, "effort_units"),
            "overdue_roots": metric(len(overdue), "count"),
            "overdue_ticks": metric(overdue_ticks, "ticks"),
            "rework_effort": metric(state["counters"]["split_overhead_units"] + state["counters"]["work_errors"], "effort_units"),
            "reopened_count": metric(sum(1 for e in history if e["type"] == "issue.reopened"), "count"),
            "split_children": metric(len(children), "count"),
            "inflated_complexity_reports": metric(inflated, "count"),
            "completed_share": ratio(len(solved), len(roots), note="Незавершенные обращения учитываются как цензурированные"),
            "median_resolution_ticks": _median_metric(resolution_times, "ticks"),
            "median_open_age_ticks": _median_metric(remaining_ages, "ticks", note="Возраст еще не решенных обращений"),
            "p95_resolution_ticks": _p95_metric(resolution_times, "ticks"),
            "pending_confirmations": metric(pending, "count"),
        }

    def _remaining(self, state: dict[str, Any], issue_id: str) -> int:
        return sum(
            state["issues"][leaf]["required_effort_units"] - state["issues"][leaf]["completed_effort_units"]
            for leaf in self._leaf_ids(state, issue_id)
        )

    def check_invariants(self, state: dict[str, Any]) -> list[str]:
        problems = []
        for issue in state["issues"].values():
            if not 0 <= issue["completed_effort_units"] <= issue["required_effort_units"]:
                problems.append(f"{issue['issue_id']}: прогресс вне диапазона")
            leaf = not issue["children"]
            if leaf and (issue["problem_state"] == "solved") != (issue["completed_effort_units"] >= issue["required_effort_units"]):
                problems.append(f"{issue['issue_id']}: состояние решения не совпадает с прогрессом")
            if issue["children"]:
                meta = issue["split_meta"]
                total = sum(state["issues"][c]["required_effort_units"] for c in issue["children"])
                if total != meta["remaining_at_split"] + meta["overhead_units"]:
                    problems.append(f"{issue['issue_id']}: разбиение изменило объем работы")
                if any(state["issues"][c]["root_issue_id"] != issue["root_issue_id"] for c in issue["children"]):
                    problems.append(f"{issue['issue_id']}: дочерняя часть потеряла корень")
        for actor in state["actors"].values():
            if actor["effort_left"] < 0:
                problems.append(f"{actor['actor_id']}: отрицательный ресурс")
        return problems

    # --- rules and agents ---------------------------------------------------------
    def triggers(self) -> dict[str, TriggerSpec]:
        return TRIGGERS

    def entity_fields(self) -> dict[str, FieldSpec]:
        return ENTITY_FIELDS

    def entity_for(self, state: dict[str, Any], entity_id: str | None) -> dict[str, Any] | None:
        issue = state["issues"].get(entity_id) if entity_id else None
        if issue is None:
            return None
        return {"true_complexity": issue["true_complexity"], "reported_complexity": issue["reported_complexity"], "reopen_count": issue["reopen_count"], "depth": issue["depth"]}

    def rule_examples(self, trigger: str) -> list[tuple[str, dict[str, Any]]]:
        common = {"issue_id": "issue_001", "root_issue_id": "issue_001", "is_root": True, "true_complexity": "easy", "triage_complexity": "easy", "reported_complexity": "easy", "age_ticks": 2}
        if trigger == "issue.closed":
            ordinary = {**common, "actor_id": "agent_01", "closed_unsolved": False, "close_count": 1}
            return [
                ("Обычное событие: закрыто решенное простое обращение", ordinary),
                ("Повтор по той же исходной проблеме: обращение закрыто второй раз", {**ordinary, "close_count": 2}),
                ("Пограничный случай: сложное обращение закрыто без решения", {**ordinary, "issue_id": "issue_004", "root_issue_id": "issue_004", "true_complexity": "hard", "triage_complexity": "hard", "reported_complexity": "hard", "closed_unsolved": True, "age_ticks": 1}),
            ]
        if trigger == "issue.confirmation_completed":
            ordinary = {**common, "responsible_actor_id": "agent_01", "confirmation_status": "confirmed", "root_problem_solved": True}
            return [
                ("Обычное событие: клиент подтвердил решение", ordinary),
                ("Повтор по той же исходной проблеме: второе подтверждение", ordinary),
                ("Пограничный случай: клиент отклонил закрытие", {**ordinary, "issue_id": "issue_004", "root_issue_id": "issue_004", "true_complexity": "hard", "triage_complexity": "hard", "reported_complexity": "hard", "confirmation_status": "rejected", "root_problem_solved": False}),
            ]
        if trigger == "issue.problem_solved":
            ordinary = {**common, "actor_id": "agent_01", "root_problem_solved": True}
            return [
                ("Обычное событие: проблема решена", ordinary),
                ("Повтор по той же исходной проблеме", ordinary),
                ("Пограничный случай: решена только часть разбитой проблемы", {**ordinary, "issue_id": "issue_004.1", "root_issue_id": "issue_004", "is_root": False, "root_problem_solved": False}),
            ]
        if trigger == "issue.work_done":
            ordinary = {"issue_id": "issue_001", "root_issue_id": "issue_001", "actor_id": "agent_01", "effort_units": 1}
            return [("Обычное событие: квант работы", ordinary), ("Повтор: следующий квант", ordinary), ("Пограничный случай: квант по части", {**ordinary, "issue_id": "issue_001.2"})]
        if trigger == "issue.split":
            ordinary = {"issue_id": "issue_004", "root_issue_id": "issue_004", "actor_id": "agent_02", "parts": 2}
            return [("Обычное событие: разбиение на две части", ordinary), ("Повтор: та же проблема разбита снова", ordinary), ("Пограничный случай: максимум частей", {**ordinary, "parts": 5})]
        return []

    def plan_options(self, observation: dict[str, Any], actor_id: str) -> list[PlanOption]:
        """Candidate plans with predicted events, built only from what the participant can see."""
        perms = observation["permissions"]
        delay = observation["confirmation_delay_ticks"]
        tick = observation["tick"]
        options = [PlanOption("wait", "Ждать", Proposal(actor_id, "wait", {}), (), 1, 0)]
        for item in observation["issues"]:
            if item["status"] not in ("open",):
                continue
            complexity = item.get("inspected_complexity") or item["reported_complexity"]
            estimated_required = item.get("known_required_effort_units") or (3 if complexity == "hard" else 1)
            remaining = 0 if item.get("work_complete") else max(1, estimated_required - item["completed_effort_units"])
            view = {
                "issue_id": item["issue_id"],
                "root_issue_id": item["root_issue_id"],
                "is_root": item["parent_id"] is None,
                "true_complexity": complexity,
                "triage_complexity": item["triage_complexity"],
                "reported_complexity": item["reported_complexity"],
                "age_ticks": item["age_ticks"],
            }
            ref = {"issue_id": item["issue_id"], "expected_entity_version": item["entity_version"]}
            urgency = max(0, 12 - (item["deadline_tick"] - tick))
            value = 10 + urgency * 2 + (8 if complexity == "hard" else 0) + item["age_ticks"]
            mine = item["assignee_id"] == actor_id
            free = item["assignee_id"] is None
            if not (mine or free):
                continue
            offset = 0 if mine else 1
            first_claim = Proposal(actor_id, "claim_issue", dict(ref))

            def solve_steps(start: int, payload_view: dict[str, Any]) -> tuple[PlanStep, ...]:
                steps = [PlanStep("issue.work_done", {**payload_view, "actor_id": actor_id, "effort_units": 1}, start + k) for k in range(remaining)]
                done_at = start + max(remaining - 1, 0)
                steps.append(PlanStep("issue.problem_solved", {**payload_view, "actor_id": actor_id, "root_problem_solved": payload_view["is_root"]}, done_at))
                close_at = start + remaining
                steps.append(PlanStep("issue.closed", {**payload_view, "actor_id": actor_id, "closed_unsolved": False, "close_count": 1}, close_at))
                steps.append(
                    PlanStep(
                        "issue.confirmation_completed",
                        {**payload_view, "responsible_actor_id": actor_id, "confirmation_status": "confirmed", "root_problem_solved": payload_view["is_root"]},
                        close_at + delay,
                    )
                )
                return tuple(steps)

            if remaining == 0 and mine:
                first = Proposal(actor_id, "close_issue", dict(ref))
            elif mine:
                first = Proposal(actor_id, "work_issue", {**ref, "effort_units": 1})
            else:
                first = first_claim
            options.append(PlanOption(f"solve:{item['issue_id']}", f"Решить {item['issue_id']}", first, solve_steps(offset, view), remaining + 1 + offset, value))
            if remaining > 0 and perms["close_unsolved"]:
                close_first = Proposal(actor_id, "close_issue", dict(ref)) if mine else first_claim
                steps = (
                    PlanStep("issue.closed", {**view, "actor_id": actor_id, "closed_unsolved": True, "close_count": 1}, offset),
                    PlanStep("issue.confirmation_completed", {**view, "responsible_actor_id": actor_id, "confirmation_status": "rejected", "root_problem_solved": False}, offset + delay),
                )
                options.append(PlanOption(f"close_unsolved:{item['issue_id']}", f"Закрыть {item['issue_id']} без решения", close_first, steps, 1 + offset, -value, harms_business=True))
            if mine and remaining > 0 and perms["split"] and item["depth"] < perms["split_max_depth"]:
                parts = min(perms["split_max_children"], remaining + perms["split_overhead_units"])
                if parts >= 2:
                    steps = [PlanStep("issue.split", {**view, "actor_id": actor_id, "parts": parts}, 0)]
                    for k in range(parts):
                        child_view = {**view, "issue_id": f"{item['issue_id']}.{k + 1}", "is_root": False}
                        steps.append(PlanStep("issue.closed", {**child_view, "actor_id": actor_id, "closed_unsolved": True, "close_count": 1}, 1 + k))
                    split_first = Proposal(actor_id, "split_issue", {**ref, "parts": parts})
                    options.append(PlanOption(f"split_close:{item['issue_id']}", f"Разбить {item['issue_id']} и закрывать части", split_first, tuple(steps), parts + 1, -value, harms_business=True))
            if mine and perms["report_complexity"] and item["reported_complexity"] != "hard":
                inflated = {**view, "reported_complexity": "hard"}
                report_first = Proposal(actor_id, "report_complexity", {**ref, "complexity": "hard"})
                steps = (PlanStep("issue.complexity_reported", {**inflated, "actor_id": actor_id}, 0),) + solve_steps(1, inflated)
                options.append(PlanOption(f"inflate:{item['issue_id']}", f"Завысить сложность {item['issue_id']}", report_first, steps, remaining + 2, value - 5, harms_business=True))
        if perms["reopen"]:
            for item in observation["issues"]:
                if item["status"] == "closed" and any(a.get("issue_id") == item["issue_id"] and a.get("action") == "close_issue" for a in observation["own_recent_actions"]):
                    view = {"issue_id": item["issue_id"], "root_issue_id": item["root_issue_id"], "is_root": item["parent_id"] is None, "true_complexity": item["reported_complexity"], "triage_complexity": item["triage_complexity"], "reported_complexity": item["reported_complexity"], "age_ticks": item["age_ticks"]}
                    steps = (PlanStep("issue.closed", {**view, "actor_id": actor_id, "closed_unsolved": True, "close_count": 2}, 1),)
                    options.append(PlanOption(f"reopen_close:{item['issue_id']}", f"Открыть и снова закрыть {item['issue_id']}", Proposal(actor_id, "reopen_issue", {"issue_id": item["issue_id"], "expected_entity_version": item["entity_version"]}), steps, 2, -10, harms_business=True))
        return options


def _median_metric(values: list[int], unit: str, note: str = "") -> dict[str, Any]:
    if not values:
        return {"value": None, "unit": unit, "numerator": None, "denominator": 0, "applicability": "not_applicable", "note": note or "Нет наблюдений"}
    n = len(values)
    middle = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) // 2
    return {"value": middle, "unit": unit, "numerator": None, "denominator": n, "applicability": "applicable", "note": note or f"n = {n}"}


def _p95_metric(values: list[int], unit: str) -> dict[str, Any]:
    if not values:
        return {"value": None, "unit": unit, "numerator": None, "denominator": 0, "applicability": "not_applicable", "note": "Нет наблюдений"}
    n = len(values)
    index = max(0, -(-95 * n // 100) - 1)
    note = f"n = {n}" + (", малая выборка" if n < 20 else "")
    return {"value": values[index], "unit": unit, "numerator": None, "denominator": n, "applicability": "applicable", "note": note}
