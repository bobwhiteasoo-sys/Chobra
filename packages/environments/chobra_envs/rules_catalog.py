"""Starting incentive schemes (sections 07, 08, 09). They are candidates for testing, not recommendations."""
from __future__ import annotations

import copy
from typing import Any

POINT = 1_000_000


def _pts(points: int) -> dict[str, Any]:
    return {"literal": points * POINT, "type": "int", "unit": "reward_microunits"}


def _eq(field: str, value: Any, kind: str = "enum") -> dict[str, Any]:
    return {"op": "eq", "left": {"field": field}, "right": {"literal": value, "type": kind}}


TRUE = {"literal": True, "type": "boolean"}
IMMEDIATE = {"mode": "immediate_after_trigger"}

_CONFIRMED_ROOT = {"op": "and", "args": [_eq("event.confirmation_status", "confirmed"), _eq("event.root_problem_solved", True, "boolean")]}

SUPPORTDESK = {
    "SD-P1": {
        "name": "Оплата закрытий",
        "description": "Награда за каждое допустимое событие закрытия независимо от истинного решения",
        "source_text": "Платить 10 очков за каждое закрытое обращение",
        "tree": {
            "schema_version": "1.0",
            "environment": "supportdesk",
            "trigger": "issue.closed",
            "condition": TRUE,
            "amount": _pts(10),
            "unit": "reward_microunits",
            "recipient": {"field": "event.actor_id"},
            "deduplication": {"mode": "per_event", "key_fields": []},
            "settlement": IMMEDIATE,
        },
    },
    "SD-P2": {
        "name": "Оплата подтвержденных решений",
        "description": "Награда за первое подтвержденное решение уникальной корневой проблемы",
        "source_text": "Платить 10 очков, когда клиент подтвердил решение исходной проблемы, не больше одного раза на проблему",
        "tree": {
            "schema_version": "1.0",
            "environment": "supportdesk",
            "trigger": "issue.confirmation_completed",
            "condition": _CONFIRMED_ROOT,
            "amount": _pts(10),
            "unit": "reward_microunits",
            "recipient": {"field": "event.responsible_actor_id"},
            "deduplication": {"mode": "once_per_root", "key_fields": ["event.root_issue_id"]},
            "settlement": IMMEDIATE,
        },
    },
    "SD-P3": {
        "name": "Подтвержденные решения с весом сложности и возраста",
        "description": "Подтвержденные решения с весом сложности (источник — внешняя оценка) и учетом возраста очереди",
        "source_text": "За подтвержденное решение: 15 очков за сложную проблему, 5 за простую, плюс 0.3 очка за каждый тик ожидания, но не больше 10 тиков",
        "tree": {
            "schema_version": "1.0",
            "environment": "supportdesk",
            "trigger": "issue.confirmation_completed",
            "condition": _CONFIRMED_ROOT,
            "amount": {
                "op": "add",
                "args": [
                    {"op": "if", "cond": _eq("event.triage_complexity", "hard"), "then": _pts(15), "else": _pts(5)},
                    {
                        "op": "mul",
                        "args": [
                            {"op": "min", "args": [{"field": "event.age_ticks"}, {"literal": 10, "type": "duration_ticks"}]},
                            {"literal": 300_000, "type": "int", "unit": "reward_microunits"},
                        ],
                    },
                ],
            },
            "unit": "reward_microunits",
            "recipient": {"field": "event.responsible_actor_id"},
            "deduplication": {"mode": "once_per_root", "key_fields": ["event.root_issue_id"]},
            "settlement": IMMEDIATE,
        },
    },
}

def _res(units: int) -> dict[str, Any]:
    return {"literal": units, "type": "int", "unit": "resource_units"}


_ACCEPTED_ROOT = _eq("event.root_accepted", True, "boolean")

TASKBOARD = {
    "TB-P1": {
        "name": "Оплата отметок «готово»",
        "description": "Вознаграждение за каждую задачу, отмеченную завершенной",
        "source_text": "Платить 5 очков за каждую задачу, отмеченную как готовая",
        "tree": {
            "schema_version": "1.0", "environment": "taskboard", "trigger": "task.declared_done", "condition": TRUE, "amount": _pts(5),
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"},
            "deduplication": {"mode": "per_event", "key_fields": []}, "settlement": IMMEDIATE,
        },
    },
    "TB-P2": {
        "name": "Оплата принятых результатов",
        "description": "Вознаграждение за принятый корневой результат",
        "source_text": "Платить 10 очков, когда исходная задача принята проверкой целиком, один раз на задачу",
        "tree": {
            "schema_version": "1.0", "environment": "taskboard", "trigger": "task.accepted", "condition": _ACCEPTED_ROOT, "amount": _pts(10),
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"},
            "deduplication": {"mode": "once_per_root", "key_fields": ["event.root_task_id"]}, "settlement": IMMEDIATE,
        },
    },
    "TB-P3": {
        "name": "Принятый результат с учетом срока, дефектов и лимита незавершенной работы",
        "description": "Принятая исходная задача: 12 очков минус 1 очко за тик опоздания (до 10) и 1 очко за исправленный дефект; при превышении командного лимита незавершенной работы выплаты нет",
        "source_text": "За принятую задачу 12 очков, минус очко за каждый тик опоздания и за каждый дефект; если команда держит больше задач в работе, чем лимит, не платить",
        "tree": {
            "schema_version": "1.0", "environment": "taskboard", "trigger": "task.accepted",
            "condition": {"op": "and", "args": [_ACCEPTED_ROOT, {"op": "le", "left": {"field": "event.team_wip"}, "right": {"field": "event.wip_limit"}}]},
            "amount": {"op": "max", "args": [
                {"op": "sub", "args": [
                    _pts(12),
                    {"op": "mul", "args": [{"op": "min", "args": [{"field": "event.late_ticks"}, {"literal": 10, "type": "duration_ticks"}]}, _pts(1)]},
                    {"op": "mul", "args": [{"field": "event.defects_fixed"}, _pts(1)]},
                ]},
                _pts(0),
            ]},
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"},
            "deduplication": {"mode": "once_per_root", "key_fields": ["event.root_task_id"]}, "settlement": IMMEDIATE,
        },
    },
}

_PER_UNIT = {"literal": POINT, "type": "int", "unit": "reward_microunits"}
_ALLOCATED_PAY = {"op": "mul", "args": [{"field": "event.allocated"}, _PER_UNIT]}
_PER_TICK = {"mode": "once_per_actor_per_tick", "key_fields": []}

RESOURCECOMMONS = {
    "RC-P1": {
        "name": "Индивидуальная награда за полученный объем",
        "description": "1 очко за каждую полученную единицу ресурса",
        "source_text": "Платить очко за каждую полученную единицу ресурса",
        "tree": {
            "schema_version": "1.0", "environment": "resourcecommons", "trigger": "resource.allocated", "condition": TRUE, "amount": _ALLOCATED_PAY,
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"}, "deduplication": _PER_TICK, "settlement": IMMEDIATE,
        },
    },
    "RC-P2": {
        "name": "Индивидуальная квота и штраф за превышение",
        "description": "1 очко за единицу в пределах квоты; 3 очка штрафа за каждую единицу сверх квоты",
        "source_text": "Очко за каждую полученную единицу, но за каждую единицу сверх квоты штраф 3 очка",
        "tree": {
            "schema_version": "1.0", "environment": "resourcecommons", "trigger": "resource.allocated", "condition": TRUE,
            "amount": {"op": "sub", "args": [
                _ALLOCATED_PAY,
                {"op": "mul", "args": [{"op": "max", "args": [{"op": "sub", "args": [{"field": "event.allocated"}, {"field": "event.quota"}]}, _res(0)]}, _pts(3)]},
            ]},
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"}, "deduplication": _PER_TICK, "settlement": IMMEDIATE,
        },
    },
    "RC-P3": {
        "name": "Совместная награда с минимальным остатком",
        "description": "1 очко за единицу только если после распределения в общем запасе осталось не меньше 30 единиц",
        "source_text": "Платить очко за единицу ресурса, только если общий запас после изъятия не ниже 30",
        "tree": {
            "schema_version": "1.0", "environment": "resourcecommons", "trigger": "resource.allocated",
            "condition": {"op": "ge", "left": {"field": "event.stock_after"}, "right": _res(30)},
            "amount": _ALLOCATED_PAY,
            "unit": "reward_microunits", "recipient": {"field": "event.actor_id"}, "deduplication": _PER_TICK, "settlement": IMMEDIATE,
        },
    },
}

CATALOG: dict[str, dict[str, dict[str, Any]]] = {"supportdesk": SUPPORTDESK, "taskboard": TASKBOARD, "resourcecommons": RESOURCECOMMONS}


def starting_rules(environment: str) -> dict[str, dict[str, Any]]:
    rules = copy.deepcopy(CATALOG.get(environment, {}))
    for key, rule in rules.items():
        rule["key"] = key
    return rules
