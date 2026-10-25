"""Static checks of a rule tree before publication (RULE-001, RULE-002, RULE-004).

Errors block publication; warnings never change the rule (RULE-004).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ..canonical import canonical_dumps
from ..contract import Environment, FieldSpec, TriggerSpec
from .types import (
    DEDUP_MODES,
    INT_UNITS,
    KINDS,
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    MAX_SET,
    ROUND_MODES,
    SETTLEMENT_MODES,
    Ty,
    label,
    ty_from_field,
    unit_of,
)

TOP_KEYS = {"schema_version", "environment", "trigger", "condition", "amount", "unit", "recipient", "deduplication", "settlement", "name", "description", "source_text"}
OP_KEYS = {
    "add": {"args"}, "sub": {"args"}, "mul": {"args"}, "min": {"args"}, "max": {"args"}, "clamp": {"args"},
    "div": {"args", "on_zero"}, "round": {"arg", "mode"},
    "eq": {"left", "right"}, "ne": {"left", "right"}, "lt": {"left", "right"}, "le": {"left", "right"}, "gt": {"left", "right"}, "ge": {"left", "right"},
    "and": {"args"}, "or": {"args"}, "not": {"arg"}, "if": {"cond", "then", "else"}, "in": {"value", "set"},
    "count_events": {"event_type", "where", "window_ticks"}, "sum_events": {"event_type", "where", "window_ticks", "field"},
}
BOOL = Ty("boolean")


@dataclass(frozen=True)
class RuleIssue:
    code: str
    message: str
    path: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "path": self.path, "details": self.details}


@dataclass
class RuleValidation:
    errors: list[RuleIssue]
    warnings: list[RuleIssue]
    node_count: int
    depth: int
    mutable_fields: list[str]
    unit_of_account: str

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "node_count": self.node_count,
            "depth": self.depth,
            "mutable_fields": self.mutable_fields,
            "unit_of_account": self.unit_of_account,
        }


class _Checker:
    def __init__(self, triggers: dict[str, TriggerSpec], entity_fields: dict[str, FieldSpec]):
        self.triggers = triggers
        self.entity_fields = entity_fields
        self.errors: list[RuleIssue] = []
        self.warnings: list[RuleIssue] = []
        self.nodes = 0
        self.max_depth = 0
        self.depth_reported = False
        self.nodes_reported = False
        self.mutable: list[str] = []
        self.fields: dict[str, FieldSpec] = {}
        self.suppress_event_fields = False

    def error(self, code: str, message: str, path: str, **details: Any) -> None:
        self.errors.append(RuleIssue(code, message, path, details))

    def warn(self, code: str, message: str, path: str, **details: Any) -> None:
        self.warnings.append(RuleIssue(code, message, path, details))

    # --- expressions --------------------------------------------------------------
    def expr(self, node: Any, path: str, depth: int = 1) -> Ty | None:
        self.nodes += 1
        self.max_depth = max(self.max_depth, depth)
        if self.nodes > MAX_NODES and not self.nodes_reported:
            self.nodes_reported = True
            self.error("RULE_TOO_MANY_NODES", f"В правиле больше {MAX_NODES} узлов", path)
        if depth > MAX_DEPTH:
            if not self.depth_reported:
                self.depth_reported = True
                self.error("RULE_TOO_DEEP", f"Глубина дерева больше {MAX_DEPTH}", path)
            return None
        if not isinstance(node, dict):
            self.error("RULE_BAD_NODE", "Узел должен быть объектом", path)
            return None
        if "literal" in node:
            return self.literal(node, path)
        if "field" in node:
            extra = set(node) - {"field"}
            if extra:
                self.error("RULE_UNKNOWN_KEY", f"Лишние поля узла: {', '.join(sorted(extra))}", path)
            return self.field_ref(node["field"], path)
        if "op" in node:
            return self.op(node, path, depth)
        self.error("RULE_BAD_NODE", "Узел должен содержать literal, field или op", path)
        return None

    def literal(self, node: dict[str, Any], path: str) -> Ty | None:
        extra = set(node) - {"literal", "type", "unit"}
        if extra:
            self.error("RULE_UNKNOWN_KEY", f"Лишние поля узла: {', '.join(sorted(extra))}", path)
        kind, value, unit = node.get("type"), node["literal"], node.get("unit", "none")
        if kind not in KINDS:
            self.error("RULE_BAD_LITERAL", "Неизвестный тип значения", path)
            return None
        if isinstance(value, float):
            self.error("RULE_BAD_LITERAL", "Двоичные дробные числа запрещены; используйте decimal строкой", path)
            return None
        ok = {
            "boolean": isinstance(value, bool),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "decimal": isinstance(value, str) and _is_decimal(value),
            "enum": isinstance(value, str),
            "duration_ticks": isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            "entity_ref": isinstance(value, str),
            "event_ref": isinstance(value, int) and not isinstance(value, bool),
            "set": isinstance(value, list) and len(value) <= MAX_SET,
        }[kind]
        if not ok:
            self.error("RULE_BAD_LITERAL", f"Значение не соответствует типу {kind}", path)
            return None
        if kind in ("int", "decimal") and unit not in INT_UNITS:
            self.error("RULE_BAD_UNIT", f"Неизвестная единица {unit}", path)
            return None
        if kind == "duration_ticks":
            return Ty("duration_ticks", "duration_ticks")
        return Ty(kind, unit if kind in ("int", "decimal") else "none")

    def field_ref(self, name: Any, path: str) -> Ty | None:
        if not isinstance(name, str):
            self.error("RULE_UNKNOWN_FIELD", "Имя поля должно быть строкой", path)
            return None
        spec = self.fields.get(name) or self.entity_fields.get(name)
        if spec is None:
            if name.startswith("event.") and self.suppress_event_fields:
                return None
            self.error("RULE_UNKNOWN_FIELD", f"Поле {name} недоступно для этого события", path, field=name)
            return None
        if spec.mutable_by_actor:
            if name not in self.mutable:
                self.mutable.append(name)
            self.warn("RULE_WARN_MUTABLE_FIELD", f"Поле {name} может изменять участник; награда от него зависит", path, field=name)
        return ty_from_field(spec)

    def op(self, node: dict[str, Any], path: str, depth: int) -> Ty | None:
        name = node["op"]
        if name not in OP_KEYS:
            self.error("RULE_UNKNOWN_OP", f"Операция {name} не поддерживается", path)
            return None
        extra = set(node) - OP_KEYS[name] - {"op"}
        if extra:
            self.error("RULE_UNKNOWN_KEY", f"Лишние поля узла: {', '.join(sorted(extra))}", path)
        if name in ("add", "sub", "min", "max", "clamp"):
            return self.fold(node, path, depth, name)
        if name == "mul":
            return self.mul(node, path, depth)
        if name == "div":
            return self.div(node, path, depth)
        if name == "round":
            if node.get("mode", "half_even") not in ROUND_MODES:
                self.error("RULE_BAD_NODE", "Режим округления half_even, floor или ceil", f"{path}.mode")
            ty = self.expr(node.get("arg"), f"{path}.arg", depth + 1)
            if ty is None:
                return None
            if not ty.numeric:
                self.error("RULE_TYPE_MISMATCH", "Округлять можно только число", f"{path}.arg")
                return None
            return Ty("duration_ticks", "duration_ticks") if ty.kind == "duration_ticks" else Ty("int", ty.unit)
        if name in ("eq", "ne", "lt", "le", "gt", "ge"):
            return self.compare(node, path, depth, name)
        if name in ("and", "or"):
            args = self.args(node, path, 2)
            for index, arg in enumerate(args):
                ty = self.expr(arg, f"{path}.args[{index}]", depth + 1)
                if ty is not None and ty.kind != "boolean":
                    self.error("RULE_TYPE_MISMATCH", "Ожидалось логическое значение", f"{path}.args[{index}]")
            return BOOL
        if name == "not":
            ty = self.expr(node.get("arg"), f"{path}.arg", depth + 1)
            if ty is not None and ty.kind != "boolean":
                self.error("RULE_TYPE_MISMATCH", "Ожидалось логическое значение", f"{path}.arg")
            return BOOL
        if name == "if":
            cond = self.expr(node.get("cond"), f"{path}.cond", depth + 1)
            if cond is not None and cond.kind != "boolean":
                self.error("RULE_TYPE_MISMATCH", "Условие должно быть логическим", f"{path}.cond")
            then = self.expr(node.get("then"), f"{path}.then", depth + 1)
            other = self.expr(node.get("else"), f"{path}.else", depth + 1)
            if then is None or other is None:
                return None
            return self.unify(then, other, f"{path}.else", "выбрать между")
        if name == "in":
            ty = self.expr(node.get("value"), f"{path}.value", depth + 1)
            values = node.get("set")
            if not isinstance(values, list) or len(values) > MAX_SET or any(isinstance(v, (dict, list, float)) for v in values):
                self.error("RULE_BAD_LITERAL", f"set — список до {MAX_SET} простых значений", f"{path}.set")
            elif ty is not None and ty.kind == "enum" and ty.enum_values:
                for index, value in enumerate(values):
                    if value not in ty.enum_values:
                        self.error("RULE_ENUM_VALUE", f"Значение {value} не входит в {list(ty.enum_values)}", f"{path}.set[{index}]")
            return BOOL
        if name in ("count_events", "sum_events"):
            return self.aggregate(node, path, depth, name)
        return None

    def args(self, node: dict[str, Any], path: str, minimum: int, exact: int | None = None) -> list[Any]:
        args = node.get("args")
        if not isinstance(args, list) or len(args) < minimum or (exact is not None and len(args) != exact):
            need = exact if exact is not None else f"не меньше {minimum}"
            self.error("RULE_BAD_NODE", f"Нужно аргументов: {need}", f"{path}.args")
            return []
        return args

    def unify(self, left: Ty, right: Ty, path: str, verb: str) -> Ty | None:
        if not left.numeric or not right.numeric:
            if left.kind == right.kind and not left.numeric:
                return left
            self.error("RULE_TYPE_MISMATCH", f"Нельзя {verb} {label(right)} и {label(left)}", path, expected_unit=unit_of(left), actual_unit=unit_of(right))
            return None
        if left.kind == "duration_ticks" or right.kind == "duration_ticks":
            other = right if left.kind == "duration_ticks" else left
            if other.kind == "duration_ticks" or (other.kind == "int" and other.unit == "none"):
                return Ty("duration_ticks", "duration_ticks")
            self.error("RULE_TYPE_MISMATCH", f"Нельзя {verb} {label(right)} и {label(left)}", path, expected_unit=unit_of(left), actual_unit=unit_of(right))
            return None
        kind = "decimal" if "decimal" in (left.kind, right.kind) else "int"
        if left.unit == right.unit or right.scalar_unit:
            return Ty(kind, left.unit)
        if left.scalar_unit:
            return Ty(kind, right.unit)
        self.error("RULE_TYPE_MISMATCH", f"Нельзя {verb} {label(right)} и {label(left)}", path, expected_unit=left.unit, actual_unit=right.unit)
        return None

    def fold(self, node: dict[str, Any], path: str, depth: int, name: str) -> Ty | None:
        args = self.args(node, path, 3 if name == "clamp" else 2, 3 if name == "clamp" else None)
        verb = {"add": "сложить", "sub": "вычесть", "min": "сравнить", "max": "сравнить", "clamp": "ограничить"}[name]
        acc: Ty | None = None
        for index, arg in enumerate(args):
            ty = self.expr(arg, f"{path}.args[{index}]", depth + 1)
            if ty is None:
                return None
            if not ty.numeric:
                self.error("RULE_TYPE_MISMATCH", "Ожидалось число", f"{path}.args[{index}]")
                return None
            acc = ty if acc is None else self.unify(acc, ty, f"{path}.args[{index}]", verb)
            if acc is None:
                return None
        return acc

    def mul(self, node: dict[str, Any], path: str, depth: int) -> Ty | None:
        args = self.args(node, path, 2)
        acc: Ty | None = None
        for index, arg in enumerate(args):
            ty = self.expr(arg, f"{path}.args[{index}]", depth + 1)
            if ty is None:
                return None
            if not ty.numeric:
                self.error("RULE_TYPE_MISMATCH", "Ожидалось число", f"{path}.args[{index}]")
                return None
            if acc is None:
                acc = ty
                continue
            kind = "decimal" if "decimal" in (acc.kind, ty.kind) else "int"
            # A duration multiplied by a per-tick rate gives the rate's unit.
            a_unit = "none" if acc.kind == "duration_ticks" else acc.unit
            b_unit = "none" if ty.kind == "duration_ticks" else ty.unit
            if acc.kind == "duration_ticks" and ty.kind == "duration_ticks":
                self.error("RULE_TYPE_MISMATCH", "Нельзя перемножить две длительности", f"{path}.args[{index}]")
                return None
            if a_unit in ("none", "count"):
                unit = b_unit if b_unit not in ("none",) else a_unit
            elif b_unit in ("none", "count"):
                unit = a_unit
            else:
                self.error("RULE_TYPE_MISMATCH", f"Нельзя перемножить {label(ty)} и {label(acc)}", f"{path}.args[{index}]", expected_unit=a_unit, actual_unit=b_unit)
                return None
            if unit == "none" and (acc.kind == "duration_ticks" or ty.kind == "duration_ticks"):
                acc = Ty("duration_ticks", "duration_ticks")
            else:
                acc = Ty(kind, unit)
        return acc

    def div(self, node: dict[str, Any], path: str, depth: int) -> Ty | None:
        args = self.args(node, path, 2, 2)
        if len(args) != 2:
            return None
        num = self.expr(args[0], f"{path}.args[0]", depth + 1)
        den = self.expr(args[1], f"{path}.args[1]", depth + 1)
        if num is None or den is None:
            return None
        if not num.numeric or not den.numeric:
            self.error("RULE_TYPE_MISMATCH", "Делить можно только числа", path)
            return None
        num_unit = "none" if num.kind == "duration_ticks" else num.unit
        den_unit = "none" if den.kind == "duration_ticks" else den.unit
        if den_unit in ("none", "count"):
            result = Ty("decimal", num_unit)
        elif num_unit == den_unit:
            result = Ty("decimal", "none")
        else:
            self.error("RULE_TYPE_MISMATCH", f"Нельзя разделить {label(num)} на {label(den)}", f"{path}.args[1]", expected_unit=num_unit, actual_unit=den_unit)
            return None
        if "on_zero" not in node:
            self.error("RULE_DIV_NO_POLICY", "Для деления нужно правило on_zero: значение или error", path)
        elif node["on_zero"] != "error":
            zero = self.expr(node["on_zero"], f"{path}.on_zero", depth + 1)
            if zero is not None:
                self.unify(result, zero, f"{path}.on_zero", "подставить")
        return result

    def compare(self, node: dict[str, Any], path: str, depth: int, name: str) -> Ty:
        left_node, right_node = node.get("left"), node.get("right")
        left = self.expr(left_node, f"{path}.left", depth + 1)
        right = self.expr(right_node, f"{path}.right", depth + 1)
        if left is None or right is None:
            return BOOL
        if name in ("lt", "le", "gt", "ge"):
            if not left.numeric or not right.numeric:
                self.error("RULE_TYPE_MISMATCH", "Сравнивать по величине можно только числа", path)
            else:
                self.unify(left, right, f"{path}.right", "сравнить")
            return BOOL
        if left.numeric and right.numeric:
            self.unify(left, right, f"{path}.right", "сравнить")
            return BOOL
        if left.kind != right.kind:
            self.error("RULE_TYPE_MISMATCH", f"Нельзя сравнить {right.kind} и {left.kind}", f"{path}.right")
            return BOOL
        if left.kind == "enum":
            for spec, other, other_path in ((left, right_node, f"{path}.right"), (right, left_node, f"{path}.left")):
                if spec.enum_values and isinstance(other, dict) and "literal" in other and other["literal"] not in spec.enum_values:
                    self.error("RULE_ENUM_VALUE", f"Значение {other['literal']} не входит в {list(spec.enum_values)}", other_path)
        return BOOL

    def aggregate(self, node: dict[str, Any], path: str, depth: int, name: str) -> Ty | None:
        event_type = node.get("event_type")
        spec = self.triggers.get(event_type)
        if spec is None:
            self.error("RULE_UNKNOWN_TRIGGER", f"Событие {event_type} нельзя агрегировать", f"{path}.event_type")
            return None
        window = node.get("window_ticks")
        if window is not None and (not isinstance(window, int) or isinstance(window, bool) or window < 1 or window > 240):
            self.error("RULE_AGGREGATE_LIMIT", "Окно агрегата 1–240 тиков или null для всего запуска", f"{path}.window_ticks")
        where = node.get("where", {})
        if not isinstance(where, dict) or len(where) > 8:
            self.error("RULE_AGGREGATE_LIMIT", "where — объект до 8 условий равенства", f"{path}.where")
            where = {}
        for key, value in where.items():
            if key not in spec.fields:
                self.error("RULE_UNKNOWN_FIELD", f"Поле {key} отсутствует у события {event_type}", f"{path}.where.{key}")
                continue
            ty = self.expr(value, f"{path}.where.{key}", depth + 1)
            target = ty_from_field(spec.fields[key])
            if ty is not None and ty.kind != target.kind:
                self.error("RULE_TYPE_MISMATCH", f"Поле {key} имеет тип {target.kind}", f"{path}.where.{key}")
        if name == "count_events":
            return Ty("int", "count")
        field_name = node.get("field")
        field_spec = spec.fields.get(field_name) if isinstance(field_name, str) else None
        if field_spec is None or ty_from_field(field_spec).kind not in ("int", "duration_ticks"):
            self.error("RULE_UNKNOWN_FIELD", "sum_events суммирует целое поле этого события", f"{path}.field")
            return None
        return ty_from_field(field_spec)


def _is_decimal(value: str) -> bool:
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _unit_of_account(rule: dict[str, Any], trigger: TriggerSpec | None) -> str:
    dedup = rule.get("deduplication") or {}
    mode = dedup.get("mode")
    keys = ", ".join(dedup.get("key_fields") or [])
    event = trigger.description.lower() if trigger else str(rule.get("trigger"))
    return {
        "per_event": f"Каждое событие «{event}» оплачивается отдельно",
        "once_per_entity": f"Не более одной выплаты на объект ({keys})",
        "once_per_root": f"Не более одной выплаты на исходный объект ({keys})",
        "once_per_actor_per_tick": "Не более одной выплаты участнику за тик",
    }.get(mode, "Единица учета не задана")


def validate_rule(rule: Any, env: Environment) -> RuleValidation:
    triggers = env.triggers()
    checker = _Checker(triggers, env.entity_fields())
    if not isinstance(rule, dict):
        checker.error("RULE_BAD_NODE", "Правило должно быть объектом", "$")
        return RuleValidation(checker.errors, [], 0, 0, [], "")
    try:
        size = len(canonical_dumps(rule).encode("utf-8"))
    except TypeError as exc:
        checker.error("RULE_BAD_LITERAL", str(exc), "$")
        size = 0
    if size > MAX_BYTES:
        checker.error("RULE_TOO_LARGE", f"Размер правила больше {MAX_BYTES // 1024} КБ", "$")
    for key in sorted(set(rule) - TOP_KEYS):
        checker.error("RULE_UNKNOWN_KEY", f"Неизвестное поле правила: {key}", key)
    if rule.get("schema_version") != "1.0":
        checker.error("RULE_BAD_VERSION", "Поддерживается schema_version 1.0", "schema_version")
    if rule.get("environment") != env.name:
        checker.error("RULE_WRONG_ENVIRONMENT", f"Правило написано не для среды {env.name}", "environment")
    trigger = triggers.get(rule.get("trigger"))
    if trigger is None:
        checker.error("RULE_UNKNOWN_TRIGGER", f"Событие {rule.get('trigger')} не может запускать начисление", "trigger")
        checker.suppress_event_fields = True
    else:
        checker.fields = dict(trigger.fields)

    cond = checker.expr(rule.get("condition"), "condition")
    if cond is not None and cond.kind != "boolean":
        checker.error("RULE_TYPE_MISMATCH", "Условие должно быть логическим", "condition")
    amount = checker.expr(rule.get("amount"), "amount")
    if amount is not None and (amount.kind != "int" or amount.unit not in ("reward_microunits", "none")):
        hint = " — округлите через round" if amount.kind == "decimal" else ""
        checker.error("RULE_TYPE_MISMATCH", f"Сумма должна быть целым числом в reward_microunits{hint}", "amount", expected_unit="reward_microunits", actual_unit=unit_of(amount))
    if rule.get("unit") != "reward_microunits":
        checker.error("RULE_BAD_UNIT", "Единица начисления — reward_microunits", "unit")
    recipient = checker.expr(rule.get("recipient"), "recipient")
    if recipient is not None and not (recipient.kind == "entity_ref" and recipient.unit in ("actor", "none")):
        checker.error("RULE_BAD_RECIPIENT", "Получатель — ссылка на участника", "recipient")

    dedup = rule.get("deduplication")
    if not isinstance(dedup, dict) or dedup.get("mode") not in DEDUP_MODES:
        checker.error("RULE_BAD_DEDUP", f"Режим уникальности: {', '.join(DEDUP_MODES)}", "deduplication.mode")
    else:
        keys = dedup.get("key_fields", [])
        extra = set(dedup) - {"mode", "key_fields"}
        if extra:
            checker.error("RULE_UNKNOWN_KEY", f"Лишние поля: {', '.join(sorted(extra))}", "deduplication")
        if not isinstance(keys, list):
            checker.error("RULE_BAD_DEDUP", "key_fields — список полей события", "deduplication.key_fields")
            keys = []
        if dedup["mode"] in ("once_per_entity", "once_per_root") and not keys:
            checker.error("RULE_BAD_DEDUP", "Для этого режима нужен хотя бы один ключ", "deduplication.key_fields")
        for index, key in enumerate(keys):
            if trigger is not None and key not in trigger.fields:
                checker.error("RULE_BAD_DEDUP", f"Ключ {key} отсутствует у события", f"deduplication.key_fields[{index}]")
            elif trigger is not None and trigger.root_field and trigger.fields[key].unit not in ("root_issue", "root_task", "actor", "none") and dedup["mode"] == "once_per_root":
                checker.error("RULE_BAD_DEDUP", f"once_per_root требует ключ исходного объекта ({trigger.root_field})", f"deduplication.key_fields[{index}]")
        if trigger is not None and trigger.repeatable_per_root and dedup["mode"] == "per_event":
            checker.warn("RULE_WARN_REPEATABLE_PER_EVENT", "Событие может повторяться по одному исходному объекту; каждое будет оплачено", "deduplication.mode")
        if trigger is not None and trigger.root_field and dedup["mode"] == "once_per_entity" and any(trigger.fields[k].unit == "issue" for k in keys if k in trigger.fields):
            checker.warn("RULE_WARN_PART_UNIT", "Единица учета — отдельная часть; разбиение увеличит число выплат", "deduplication.key_fields")

    settlement = rule.get("settlement")
    if not isinstance(settlement, dict) or settlement.get("mode") not in SETTLEMENT_MODES:
        checker.error("RULE_BAD_SETTLEMENT", f"Режим расчета: {', '.join(SETTLEMENT_MODES)}", "settlement.mode")
    else:
        mode = settlement["mode"]
        allowed = {"mode", "clawback"} if mode == "immediate_after_trigger" else {"mode", "confirm_event", "match_field", "confirm_condition", "max_wait_ticks"}
        extra = set(settlement) - allowed
        if extra:
            checker.error("RULE_UNKNOWN_KEY", f"Лишние поля: {', '.join(sorted(extra))}", "settlement")
        if mode == "hold_until_confirmation":
            confirm = triggers.get(settlement.get("confirm_event"))
            if confirm is None or not confirm.confirmed_outcome:
                checker.error("RULE_BAD_SETTLEMENT", "confirm_event — событие с подтвержденным результатом", "settlement.confirm_event")
            match = settlement.get("match_field")
            if trigger is not None and confirm is not None and (match not in trigger.fields or match not in confirm.fields):
                checker.error("RULE_BAD_SETTLEMENT", "match_field должно быть у обоих событий", "settlement.match_field")
            if confirm is not None:
                saved = checker.fields
                checker.fields = dict(confirm.fields)
                ty = checker.expr(settlement.get("confirm_condition"), "settlement.confirm_condition")
                checker.fields = saved
                if ty is not None and ty.kind != "boolean":
                    checker.error("RULE_TYPE_MISMATCH", "Условие подтверждения должно быть логическим", "settlement.confirm_condition")
            wait = settlement.get("max_wait_ticks")
            if wait is not None and (not isinstance(wait, int) or not 1 <= wait <= 60):
                checker.error("RULE_BAD_SETTLEMENT", "max_wait_ticks 1–60", "settlement.max_wait_ticks")
        clawback = settlement.get("clawback")
        if clawback is not None:
            event = triggers.get(clawback.get("event")) if isinstance(clawback, dict) else None
            match = clawback.get("match_field") if isinstance(clawback, dict) else None
            if event is None or trigger is None or match not in trigger.fields or match not in event.fields:
                checker.error("RULE_BAD_SETTLEMENT", "clawback: событие среды и общее поле сопоставления", "settlement.clawback")
        if trigger is not None and not trigger.confirmed_outcome and mode == "immediate_after_trigger" and clawback is None:
            checker.warn("RULE_WARN_UNCONFIRMED_TRIGGER", "Награда начисляется до подтверждения фактического результата", "trigger")

    return RuleValidation(
        errors=checker.errors,
        warnings=checker.warnings,
        node_count=checker.nodes,
        depth=checker.max_depth,
        mutable_fields=checker.mutable,
        unit_of_account=_unit_of_account(rule, trigger),
    )
