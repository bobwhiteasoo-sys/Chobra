"""Text-to-rule candidates and field-level rule diffs (spec sections 10 and 21).

`compile_text` never publishes anything. Without a model provider it uses a transparent
phrase matcher over the starting schemes and always lists the ambiguities that need an
explicit choice (unit of account, source of complexity, confirmation).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from chobra_envs.rules_catalog import starting_rules

POINT = 1_000_000

PATTERNS = {
    "supportdesk": [
        (r"сложн", "SD-P3"),
        (r"подтвер|решен", "SD-P2"),
        (r"закры", "SD-P1"),
    ],
    "taskboard": [
        (r"срок|дефект|лимит", "TB-P3"),
        (r"принят|приемк", "TB-P2"),
        (r"готов", "TB-P1"),
    ],
    "resourcecommons": [
        (r"остат|запас|минимум", "RC-P3"),
        (r"квот|штраф", "RC-P2"),
        (r"получ|единиц|изъят", "RC-P1"),
    ],
}


def _points(text: str) -> int | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:очк|балл|point)", text)
    if not match:
        return None
    value = match.group(1).replace(",", ".")
    whole, _, frac = value.partition(".")
    return int(whole) * POINT + (int((frac + "000000")[:6]) if frac else 0)


def compile_text(environment: str, text: str) -> dict[str, Any]:
    lowered = text.lower()
    rules = starting_rules(environment)
    key = next((k for pattern, k in PATTERNS.get(environment, []) if re.search(pattern, lowered)), None)
    if key is None:
        return {
            "candidate": None,
            "understanding": "Не удалось сопоставить описание с поддерживаемыми событиями среды. Соберите правило в конструкторе.",
            "ambiguities": [],
            "source": "phrase_matcher",
            "published": False,
        }
    tree = copy.deepcopy(rules[key]["tree"])
    amount = _points(lowered)
    if amount is not None and tree["amount"].get("literal") is not None:
        tree["amount"] = {"literal": amount, "type": "int", "unit": "reward_microunits"}
    ambiguities = []
    once = re.search(r"один раз|однократ|не больше одного|за проблему|за задачу", lowered)
    every = re.search(r"кажд", lowered)
    has_root = environment in ("supportdesk", "taskboard")
    if not once and not every and has_root:
        ambiguities.append({"field": "deduplication.mode", "question": "Платить за каждое событие или один раз за исходный объект?", "options": ["per_event", "once_per_root"]})
    elif once and environment != "resourcecommons":
        root = {"supportdesk": "event.root_issue_id", "taskboard": "event.root_task_id"}[environment]
        tree["deduplication"] = {"mode": "once_per_root", "key_fields": [root]}
    elif every and tree["deduplication"]["mode"] != "once_per_actor_per_tick":
        tree["deduplication"] = {"mode": "per_event", "key_fields": []}
    if key == "SD-P3":
        ambiguities.append({"field": "amount.args[0].cond.left", "question": "Откуда брать сложность: истинная, установленная извне или заявленная участником?",
                            "options": ["event.true_complexity", "event.triage_complexity", "event.reported_complexity"]})
    if environment == "supportdesk" and key == "SD-P1" and "подтвер" not in lowered:
        ambiguities.append({"field": "settlement", "question": "Выплачивать сразу при закрытии или после проверки клиента?", "options": ["immediate_after_trigger", "hold_until_confirmation"]})
    understanding = f"Похоже на схему {key}: {rules[key]['description']}."
    if amount is not None:
        understanding += f" Сумма: {amount / POINT:g} очк."
    return {"candidate": tree, "template_key": key, "understanding": understanding, "ambiguities": ambiguities, "requires_choice": bool(ambiguities), "source": "phrase_matcher", "published": False}


def _fields(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {node["field"]} if isinstance(node.get("field"), str) else set()
        for value in node.values():
            found |= _fields(value)
        return found
    if isinstance(node, list):
        return set().union(*(_fields(v) for v in node)) if node else set()
    return set()


def _conditions(node: Any) -> list[str]:
    import json

    if isinstance(node, dict) and node.get("op") in ("and", "or"):
        return [json.dumps(a, ensure_ascii=False, sort_keys=True) for a in node.get("args", [])]
    return [json.dumps(node, ensure_ascii=False, sort_keys=True)]


def rule_diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    import json

    rows: list[dict[str, Any]] = []
    if old.get("trigger") != new.get("trigger"):
        rows.append({"kind": "trigger", "title": "Изменено событие начисления", "before": old.get("trigger"), "after": new.get("trigger"), "important": True})
    before, after = _conditions(old.get("condition")), _conditions(new.get("condition"))
    for item in before:
        if item not in after:
            rows.append({"kind": "condition_removed", "title": "Удалено условие", "before": item, "after": None, "important": True})
    for item in after:
        if item not in before:
            rows.append({"kind": "condition_added", "title": "Добавлено условие", "before": None, "after": item, "important": False})
    if json.dumps(old.get("amount"), sort_keys=True) != json.dumps(new.get("amount"), sort_keys=True):
        rows.append({"kind": "amount", "title": "Изменена формула суммы", "before": old.get("amount"), "after": new.get("amount"), "important": False})
    if old.get("deduplication") != new.get("deduplication"):
        rows.append({"kind": "unit_of_account", "title": "Изменена единица учета", "before": old.get("deduplication"), "after": new.get("deduplication"), "important": True})
    if old.get("settlement") != new.get("settlement"):
        rows.append({"kind": "settlement", "title": "Изменен момент подтверждения выплаты", "before": old.get("settlement"), "after": new.get("settlement"), "important": True})
    if old.get("recipient") != new.get("recipient"):
        rows.append({"kind": "recipient", "title": "Изменен получатель", "before": old.get("recipient"), "after": new.get("recipient"), "important": False})
    removed, added = _fields(old) - _fields(new), _fields(new) - _fields(old)
    if removed or added:
        rows.append({"kind": "data_source", "title": "Изменен источник данных", "before": sorted(removed), "after": sorted(added), "important": True})
    return rows
