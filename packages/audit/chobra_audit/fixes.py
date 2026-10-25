"""Fix candidates for a verified counterexample (spec section 15 "Предложения исправления").

Candidates are built from what the environment declares about its events (which event is a
confirmed outcome, what success means, which event reverses a result), not from knowledge
of a particular rule. Every candidate passes the same validator and stays a candidate until
a person accepts it. A candidate is not a proven fix: it has to be tested.
"""
from __future__ import annotations

import copy
from typing import Any

from chobra_engine.contract import Environment
from chobra_engine.rules import validate_rule

from .minimize import run_candidate
from .recipe import RunRecipe

TRUE = {"literal": True, "type": "boolean"}


def _recipient_field(env: Environment, trigger: str) -> str | None:
    spec = env.triggers()[trigger]
    for name in ("event.responsible_actor_id", "event.actor_id"):
        if name in spec.fields and spec.fields[name].unit == "actor":
            return name
    return None


def _confirmed_trigger(env: Environment, current: str) -> str | None:
    current_spec = env.triggers()[current]
    shared = [k for k in current_spec.fields if k.endswith("_id")]
    for name, spec in env.triggers().items():
        if name != current and spec.confirmed_outcome and spec.success_condition and any(k in spec.fields for k in shared):
            return name
    return None


def _pay_confirmed(rule: dict[str, Any], env: Environment) -> dict[str, Any] | None:
    target = _confirmed_trigger(env, rule["trigger"])
    if target is None:
        return None
    spec = env.triggers()[target]
    tree = copy.deepcopy(rule)
    tree["trigger"] = target
    tree["condition"] = copy.deepcopy(spec.success_condition)
    tree["recipient"] = {"field": _recipient_field(env, target)}
    tree["deduplication"] = {"mode": "once_per_root", "key_fields": [spec.root_field]} if spec.root_field else {"mode": "once_per_entity", "key_fields": []}
    tree["settlement"] = {"mode": "immediate_after_trigger"}
    return {
        "key": "pay_confirmed_outcome",
        "title": "Платить за подтвержденный результат",
        "explanation": f"Начисление переносится с события «{env.triggers()[rule['trigger']].description}» на «{spec.description}» с условием успешного результата; одна выплата на исходный объект.",
        "tradeoff": "Выплата приходит позже; участники с низкой терпимостью к задержке могут предпочитать быстрые простые задачи.",
        "tree": tree,
    }


def _hold(rule: dict[str, Any], env: Environment) -> dict[str, Any] | None:
    target = _confirmed_trigger(env, rule["trigger"])
    if target is None:
        return None
    current = env.triggers()[rule["trigger"]]
    spec = env.triggers()[target]
    match = next((k for k in ("event.issue_id", "event.task_id") if k in current.fields and k in spec.fields), None)
    if match is None:
        return None
    tree = copy.deepcopy(rule)
    tree["settlement"] = {"mode": "hold_until_confirmation", "confirm_event": target, "match_field": match, "confirm_condition": copy.deepcopy(spec.success_condition)}
    return {
        "key": "hold_until_confirmation",
        "title": "Удерживать выплату до подтверждения",
        "explanation": f"Событие по-прежнему создает начисление, но оно остается в статусе pending до «{spec.description}» с успешным результатом.",
        "tradeoff": "Единица учета не меняется: повторные события по одной проблеме по-прежнему могут создавать отдельные начисления.",
        "tree": tree,
    }


def _clawback(rule: dict[str, Any], env: Environment) -> dict[str, Any] | None:
    current = env.triggers()[rule["trigger"]]
    for name, spec in env.triggers().items():
        if spec.reverses:
            match = next((k for k in ("event.issue_id", "event.task_id") if k in current.fields and k in spec.fields), None)
            if match:
                tree = copy.deepcopy(rule)
                tree["settlement"] = {"mode": "immediate_after_trigger", "clawback": {"event": name, "match_field": match}}
                return {
                    "key": "clawback_on_reversal",
                    "title": "Возвращать выплату при отмене результата",
                    "explanation": f"Выплата начисляется сразу, но событие «{spec.description}» создает компенсирующую запись.",
                    "tradeoff": "Участник временно получает награду за нерешенную проблему; при отсутствии ответа клиента возврата не будет.",
                    "tree": tree,
                }
    return None


def _once_per_root(rule: dict[str, Any], env: Environment) -> dict[str, Any] | None:
    spec = env.triggers()[rule["trigger"]]
    if not spec.root_field or rule["deduplication"]["mode"] == "once_per_root":
        return None
    tree = copy.deepcopy(rule)
    tree["deduplication"] = {"mode": "once_per_root", "key_fields": [spec.root_field]}
    return {
        "key": "once_per_root",
        "title": "Одна выплата на исходный объект",
        "explanation": "Единица учета меняется с отдельного события на исходный объект; дробление и повторные закрытия перестают умножать выплату.",
        "tradeoff": "Работа над объемной исходной задачей оплачивается так же, как над простой.",
        "tree": tree,
    }


def _independent_field(rule: dict[str, Any], env: Environment) -> dict[str, Any] | None:
    spec = env.triggers()[rule["trigger"]]
    mutable = [k for k, f in spec.fields.items() if f.mutable_by_actor]
    text = repr(rule)
    used = [k for k in mutable if f"'{k}'" in text]
    if not used:
        return None
    field = used[0]
    replacement = next((k for k, f in spec.fields.items() if not f.mutable_by_actor and f.type == spec.fields[field].type and f.enum_values == spec.fields[field].enum_values and "triage" in k), None)
    replacement = replacement or next((k for k, f in spec.fields.items() if not f.mutable_by_actor and f.type == spec.fields[field].type and f.enum_values == spec.fields[field].enum_values and k != field), None)
    if replacement is None:
        return None
    tree = replace_field(copy.deepcopy(rule), field, replacement)
    return {
        "key": "independent_source",
        "title": "Брать значение из независимого источника",
        "explanation": f"Поле {field} изменяет участник; правило переводится на {replacement}.",
        "tradeoff": "Внешняя оценка может ошибаться; ошибка теперь не зависит от участника.",
        "tree": tree,
    }


def replace_field(node: Any, old: str, new: str) -> Any:
    if isinstance(node, dict):
        return {k: (new if k == "field" and v == old else replace_field(v, old, new)) for k, v in node.items()}
    if isinstance(node, list):
        return [replace_field(v, old, new) for v in node]
    return node


def _keep_minimum(rule: dict[str, Any], env: Environment, config: dict[str, Any]) -> dict[str, Any] | None:
    spec = env.triggers()[rule["trigger"]]
    if "event.stock_after" not in spec.fields:
        return None
    tree = copy.deepcopy(rule)
    guard = {"op": "ge", "left": {"field": "event.stock_after"}, "right": {"literal": config.get("min_stock", 30), "type": "int", "unit": "resource_units"}}
    tree["condition"] = {"op": "and", "args": [tree["condition"], guard]}
    return {
        "key": "keep_minimum_stock",
        "title": "Платить только при сохранении минимального запаса",
        "explanation": "Начисление происходит, только если после распределения общий запас не ниже минимума.",
        "tradeoff": "Индивидуальная награда становится зависимой от поведения других участников.",
        "tree": tree,
    }


ORDER = {
    "false_closure_v1": ["pay_confirmed_outcome", "hold_until_confirmation", "clawback_on_reversal"],
    "rewarded_rejected_resolution_v1": ["pay_confirmed_outcome", "hold_until_confirmation", "clawback_on_reversal"],
    "unsolved_paid_v1": ["pay_confirmed_outcome", "hold_until_confirmation", "clawback_on_reversal"],
    "duplicate_root_reward_v1": ["once_per_root", "pay_confirmed_outcome"],
    "split_anomaly_v1": ["once_per_root", "pay_confirmed_outcome"],
    "complexity_inflation_v1": ["independent_source"],
    "tb_done_without_work_v1": ["pay_confirmed_outcome", "hold_until_confirmation", "once_per_root"],
    "tb_split_for_counter_v1": ["pay_confirmed_outcome", "once_per_root"],
    "tb_duplicate_reward_v1": ["once_per_root"],
    "rc_depletion_v1": ["keep_minimum_stock"],
    "rc_below_min_stock_v1": ["keep_minimum_stock"],
}


def propose_fixes(rule: dict[str, Any], finding: dict[str, Any], env: Environment, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    builders = {
        "pay_confirmed_outcome": lambda: _pay_confirmed(rule, env),
        "hold_until_confirmation": lambda: _hold(rule, env),
        "clawback_on_reversal": lambda: _clawback(rule, env),
        "once_per_root": lambda: _once_per_root(rule, env),
        "independent_source": lambda: _independent_field(rule, env),
        "keep_minimum_stock": lambda: _keep_minimum(rule, env, config or {}),
    }
    out = []
    for key in ORDER.get(finding["check_id"], ["pay_confirmed_outcome", "once_per_root"]):
        candidate = builders[key]()
        if candidate is None:
            continue
        validation = validate_rule(candidate["tree"], env)
        candidate["validation"] = validation.to_dict()
        candidate["status"] = "candidate"
        if validation.ok:
            out.append(candidate)
        if len(out) == 3:
            break
    return out


def check_fix_on_counterexample(recipe: RunRecipe, events: list[dict[str, Any]], tree: dict[str, Any], *, check_id: str) -> dict[str, Any]:
    """Run the original counterexample's actions under the candidate rule (section 14 "Дополнительная проверка")."""
    from .minimize import _units

    units = _units(events)
    reproduced, session = run_candidate(recipe, units, check_id, rule=tree)
    if not reproduced:
        session_fails = any(e.type == "check.failed" and e.payload["check_id"] == check_id for e in session.log.events)
        reproduced = session_fails
    return {"reproduced": reproduced, "checks": {r["check_id"]: r["status"] for r in (session.audit or {}).get("checks", [])}, "metrics": (session.audit or {}).get("metrics", {})}
