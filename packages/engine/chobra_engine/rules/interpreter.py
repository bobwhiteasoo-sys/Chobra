"""Interpreter of validated rule trees. The same code computes editor examples and run payouts (RULE-003)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Any, Iterable

from ..canonical import sha256_hex
from ..contract import Environment

DECIMAL_STEP = Decimal("0.000001")
ROUNDING = {"half_even": ROUND_HALF_EVEN, "floor": ROUND_FLOOR, "ceil": ROUND_CEILING}


class EvalError(Exception):
    def __init__(self, code: str, message: str, path: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


@dataclass
class RuleOutcome:
    fired: bool
    amount: int | None = None
    recipient: str | None = None
    dedup_key: str | None = None
    unit_ref: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"fired": self.fired, "amount": self.amount, "recipient": self.recipient, "dedup_key": self.dedup_key, "unit_ref": self.unit_ref, "trace": self.trace}


@dataclass
class _Scope:
    payload: dict[str, Any]
    entity: dict[str, Any] | None
    tick: int
    history: list[dict[str, Any]]


def _num(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


def evaluate_expr(node: dict[str, Any], scope: _Scope, path: str) -> Any:
    if "literal" in node:
        kind = node.get("type")
        if kind == "decimal":
            return Decimal(node["literal"])
        return node["literal"]
    if "field" in node:
        name = node["field"]
        source, _, key = name.partition(".")
        if source == "event":
            if key not in scope.payload:
                raise EvalError("FIELD_MISSING", f"У события нет поля {key}", path)
            return scope.payload[key]
        if source == "entity":
            if scope.entity is None or key not in scope.entity:
                raise EvalError("FIELD_MISSING", f"Объект недоступен или не содержит {key}", path)
            return scope.entity[key]
        raise EvalError("FIELD_MISSING", f"Неизвестный источник поля {name}", path)
    op = node["op"]
    if op in ("add", "sub", "mul", "min", "max", "clamp"):
        values = [evaluate_expr(arg, scope, f"{path}.args[{i}]") for i, arg in enumerate(node["args"])]
        if op == "add":
            result = values[0]
            for value in values[1:]:
                result = result + value
            return result
        if op == "sub":
            result = values[0]
            for value in values[1:]:
                result = result - value
            return result
        if op == "mul":
            result = values[0]
            for value in values[1:]:
                result = result * value
            return result
        if op == "min":
            return min(values)
        if op == "max":
            return max(values)
        low, high = values[1], values[2]
        return max(low, min(values[0], high))
    if op == "div":
        num = evaluate_expr(node["args"][0], scope, f"{path}.args[0]")
        den = evaluate_expr(node["args"][1], scope, f"{path}.args[1]")
        if den == 0:
            policy = node.get("on_zero")
            if policy == "error" or policy is None:
                raise EvalError("DIVISION_BY_ZERO", "Деление на ноль; правило задает ошибку", path)
            return _num(evaluate_expr(policy, scope, f"{path}.on_zero"))
        return (_num(num) / _num(den)).quantize(DECIMAL_STEP, rounding=ROUND_HALF_EVEN)
    if op == "round":
        value = evaluate_expr(node["arg"], scope, f"{path}.arg")
        if isinstance(value, int):
            return value
        return int(_num(value).quantize(Decimal(1), rounding=ROUNDING[node.get("mode", "half_even")]))
    if op in ("eq", "ne", "lt", "le", "gt", "ge"):
        left = evaluate_expr(node["left"], scope, f"{path}.left")
        right = evaluate_expr(node["right"], scope, f"{path}.right")
        return {
            "eq": lambda: left == right,
            "ne": lambda: left != right,
            "lt": lambda: left < right,
            "le": lambda: left <= right,
            "gt": lambda: left > right,
            "ge": lambda: left >= right,
        }[op]()
    if op == "and":
        return all(evaluate_expr(arg, scope, f"{path}.args[{i}]") for i, arg in enumerate(node["args"]))
    if op == "or":
        return any(evaluate_expr(arg, scope, f"{path}.args[{i}]") for i, arg in enumerate(node["args"]))
    if op == "not":
        return not evaluate_expr(node["arg"], scope, f"{path}.arg")
    if op == "if":
        branch = "then" if evaluate_expr(node["cond"], scope, f"{path}.cond") else "else"
        return evaluate_expr(node[branch], scope, f"{path}.{branch}")
    if op == "in":
        return evaluate_expr(node["value"], scope, f"{path}.value") in node["set"]
    if op in ("count_events", "sum_events"):
        where = {key.partition(".")[2]: evaluate_expr(value, scope, f"{path}.where.{key}") for key, value in (node.get("where") or {}).items()}
        window = node.get("window_ticks")
        matched = [
            e for e in scope.history
            if e["type"] == node["event_type"]
            and (window is None or scope.tick - e["tick"] < window)
            and all(e["payload"].get(k) == v for k, v in where.items())
        ]
        if op == "count_events":
            return len(matched)
        key = node["field"].partition(".")[2]
        return sum(e["payload"].get(key, 0) for e in matched)
    raise EvalError("UNKNOWN_OP", f"Операция {op} не поддерживается", path)


def _dedup(rule: dict[str, Any], payload: dict[str, Any], recipient: str | None, tick: int, root_key: str | None) -> tuple[str | None, str | None]:
    dedup = rule["deduplication"]
    mode = dedup["mode"]
    values = [str(payload.get(k.partition(".")[2])) for k in dedup.get("key_fields", [])]
    unit_ref = payload.get(root_key) if root_key else None
    if mode == "per_event":
        return None, unit_ref if unit_ref is not None else None
    if mode == "once_per_actor_per_tick":
        return f"{mode}|{recipient}|{tick}|{'|'.join(values)}", unit_ref
    key = f"{mode}|{'|'.join(values)}"
    return key, unit_ref if unit_ref is not None else (values[0] if values else None)


def evaluate_rule(
    rule: dict[str, Any],
    env: Environment,
    event_type: str,
    payload: dict[str, Any],
    *,
    tick: int,
    entity: dict[str, Any] | None = None,
    history: Iterable[dict[str, Any]] = (),
) -> RuleOutcome:
    if event_type != rule["trigger"]:
        return RuleOutcome(False)
    scope = _Scope(payload, entity, tick, list(history))
    condition = bool(evaluate_expr(rule["condition"], scope, "condition"))
    trace = [{"part": "condition", "value": condition}]
    if not condition:
        return RuleOutcome(False, trace=trace, payload=payload)
    amount = evaluate_expr(rule["amount"], scope, "amount")
    if isinstance(amount, Decimal):
        if amount != amount.to_integral_value():
            raise EvalError("NOT_INTEGER", "Сумма не целая; используйте round", "amount")
        amount = int(amount)
    recipient = evaluate_expr(rule["recipient"], scope, "recipient")
    trigger = env.triggers().get(event_type)
    root_key = trigger.root_field.partition(".")[2] if trigger and trigger.root_field else None
    dedup_key, unit_ref = _dedup(rule, payload, recipient, tick, root_key)
    trace += [{"part": "amount", "value": amount}, {"part": "recipient", "value": recipient}]
    return RuleOutcome(True, amount, recipient, dedup_key, unit_ref, trace, payload)


def rule_hash(rule: dict[str, Any]) -> str:
    return sha256_hex(rule)
