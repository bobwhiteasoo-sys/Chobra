"""Types and units of the rule language (spec section 10)."""
from __future__ import annotations

from dataclasses import dataclass

from ..contract import FieldSpec

KINDS = ("boolean", "int", "decimal", "enum", "duration_ticks", "entity_ref", "event_ref", "set")
NUMERIC = frozenset({"int", "decimal", "duration_ticks"})
INT_UNITS = ("none", "count", "reward_microunits", "effort_units", "resource_units", "ticks")
DEDUP_MODES = ("per_event", "once_per_entity", "once_per_root", "once_per_actor_per_tick")
SETTLEMENT_MODES = ("immediate_after_trigger", "hold_until_confirmation")
ROUND_MODES = ("half_even", "floor", "ceil")
MAX_DEPTH = 12
MAX_NODES = 500
MAX_BYTES = 256 * 1024
MAX_SET = 64

UNIT_LABELS = {
    "reward_microunits": "очки",
    "duration_ticks": "длительность",
    "effort_units": "работу",
    "resource_units": "ресурс",
    "count": "количество",
    "ticks": "тики",
    "none": "число",
}


@dataclass(frozen=True)
class Ty:
    kind: str
    unit: str = "none"
    enum_values: tuple[str, ...] = ()
    mutable: bool = False

    @property
    def numeric(self) -> bool:
        return self.kind in NUMERIC

    @property
    def scalar_unit(self) -> bool:
        """Dimensionless numbers adopt the unit of the other operand."""
        return self.kind != "duration_ticks" and self.unit in ("none", "count")


def ty_from_field(spec: FieldSpec) -> Ty:
    if spec.type == "duration_ticks":
        return Ty("duration_ticks", "duration_ticks", mutable=spec.mutable_by_actor)
    return Ty(spec.type, spec.unit, tuple(spec.enum_values), spec.mutable_by_actor)


def unit_of(ty: Ty) -> str:
    return "duration_ticks" if ty.kind == "duration_ticks" else ty.unit


def label(ty: Ty) -> str:
    return UNIT_LABELS.get(unit_of(ty), unit_of(ty))
