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

CATALOG: dict[str, dict[str, dict[str, Any]]] = {"supportdesk": SUPPORTDESK}


def starting_rules(environment: str) -> dict[str, dict[str, Any]]:
    rules = copy.deepcopy(CATALOG.get(environment, {}))
    for key, rule in rules.items():
        rule["key"] = key
    return rules
