"""Environment contract (spec section 06).

States, observations and actions are plain JSON-compatible dicts so that they can be
hashed canonically, stored as checkpoints and sent to models without conversion.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Phase = Literal["main", "tail"]


@dataclass(frozen=True)
class ConfigIssue:
    path: str
    message: str


@dataclass(frozen=True)
class TickContext:
    seed: int
    tick: int
    config: dict[str, Any]
    phase: Phase = "main"


@dataclass(frozen=True)
class ActionSpec:
    type: str
    description: str
    schema: dict[str, Any]
    cost: str
    possible_events: tuple[str, ...]


@dataclass
class Proposal:
    actor_id: str
    action_type: str
    arguments: dict[str, Any] = field(default_factory=dict)
    decision_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "action_type": self.action_type,
            "arguments": self.arguments,
            "decision_summary": self.decision_summary,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Proposal":
        return Proposal(
            actor_id=data["actor_id"],
            action_type=data["action_type"],
            arguments=dict(data.get("arguments") or {}),
            decision_summary=data.get("decision_summary", ""),
        )


@dataclass(frozen=True)
class Rejection:
    code: str
    message: str


@dataclass
class Effect:
    """A domain change produced by the environment; the runner turns it into an event."""

    type: str
    payload: dict[str, Any]
    actor_id: str | None = None
    entity_id: str | None = None


@dataclass(frozen=True)
class FieldSpec:
    """A field that rules may read. `mutable_by_actor` marks values participants can change (RULE-001)."""

    type: str  # boolean, int, decimal, enum, duration_ticks, entity_ref, event_ref, set
    unit: str = "none"
    enum_values: tuple[str, ...] = ()
    mutable_by_actor: bool = False
    description: str = ""


@dataclass(frozen=True)
class TriggerSpec:
    event_type: str
    description: str
    fields: dict[str, FieldSpec]
    repeatable_per_root: bool = False
    confirmed_outcome: bool = False


@dataclass(frozen=True)
class PlanStep:
    """A predicted event of a candidate plan, `delay` ticks from now (used by scripted agents)."""

    event_type: str
    payload: dict[str, Any]
    delay: int


@dataclass(frozen=True)
class PlanOption:
    key: str
    label: str
    first_action: Proposal
    steps: tuple[PlanStep, ...]
    duration: int
    business_value: int  # environment's own estimate of useful work, used by cooperative agents
    harms_business: bool = False


class Environment(ABC):
    name: str
    version: str
    simultaneous: bool = False

    # --- configuration -------------------------------------------------------------
    @abstractmethod
    def default_config(self) -> dict[str, Any]: ...

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> list[ConfigIssue]: ...

    # --- world --------------------------------------------------------------------
    @abstractmethod
    def build_initial_state(self, config: dict[str, Any], seed: int, actor_ids: list[str]) -> dict[str, Any]: ...

    @abstractmethod
    def build_exogenous_tape(self, config: dict[str, Any], seed: int) -> list[dict[str, Any]]: ...

    @abstractmethod
    def apply_exogenous(self, state: dict[str, Any], tape_events: list[dict[str, Any]], ctx: TickContext) -> list[Effect]: ...

    # --- participants -------------------------------------------------------------
    @abstractmethod
    def observe(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> dict[str, Any]: ...

    @abstractmethod
    def list_actions(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> list[ActionSpec]: ...

    @abstractmethod
    def validate_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> Rejection | None: ...

    @abstractmethod
    def apply_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> list[Effect]: ...

    def apply_actions(
        self, state: dict[str, Any], proposals: list[Proposal], ctx: TickContext
    ) -> list[tuple[Proposal, Rejection | None, list[Effect]]]:
        """Apply proposals in the given (already conflict-ordered) order.

        Each proposal is re-validated against the current state, so a claim that lost to an
        earlier agent in the same tick is rejected as stale instead of being applied twice.
        """
        results = []
        for proposal in proposals:
            rejection = self.validate_action(state, proposal, ctx)
            if rejection is not None:
                results.append((proposal, rejection, []))
            else:
                results.append((proposal, None, self.apply_action(state, proposal, ctx)))
        return results

    def actor_order(self, state: dict[str, Any], actor_ids: list[str], ctx: TickContext) -> list[str]:
        from .rng import stable_order

        return stable_order(ctx.seed, "tiebreak", actor_ids, "initiative", ctx.tick)

    @abstractmethod
    def advance_time(self, state: dict[str, Any], ctx: TickContext) -> list[Effect]: ...

    # --- measurement --------------------------------------------------------------
    @abstractmethod
    def compute_metrics(
        self, state: dict[str, Any], ledger: list[dict[str, Any]], history: list[dict[str, Any]], config: dict[str, Any]
    ) -> dict[str, dict[str, Any]]: ...

    @abstractmethod
    def check_invariants(self, state: dict[str, Any]) -> list[str]: ...

    def snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(state)

    def restore(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return copy.deepcopy(snapshot)

    # --- rules and agents ---------------------------------------------------------
    @abstractmethod
    def triggers(self) -> dict[str, TriggerSpec]: ...

    def entity_fields(self) -> dict[str, FieldSpec]:
        return {}

    def entity_for(self, state: dict[str, Any], entity_id: str | None) -> dict[str, Any] | None:
        return None

    @abstractmethod
    def plan_options(self, observation: dict[str, Any], actor_id: str) -> list[PlanOption]: ...

    def rule_examples(self, trigger: str) -> list[tuple[str, dict[str, Any]]]:
        """(label, event payload) pairs: an ordinary event, its repeat and a boundary case (RULE-003)."""
        return []

    def is_active(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> bool:
        return ctx.phase == "main"


def metric(value: Any, unit: str, *, note: str = "") -> dict[str, Any]:
    return {"value": value, "unit": unit, "numerator": None, "denominator": None, "applicability": "applicable", "note": note}


def ratio(numerator: int, denominator: int, *, note: str = "") -> dict[str, Any]:
    """Rate metric. A zero denominator is `not_applicable`, never 0 (section 13, AC-059).

    The value is a decimal string with four digits so that no binary float enters hashes.
    """
    if denominator == 0:
        return {"value": None, "unit": "ratio", "numerator": numerator, "denominator": 0, "applicability": "not_applicable", "note": note or "Знаменатель равен нулю"}
    scaled = (numerator * 10_000 * 2 + denominator) // (2 * denominator)
    return {
        "value": f"{scaled // 10_000}.{scaled % 10_000:04d}",
        "unit": "ratio",
        "numerator": numerator,
        "denominator": denominator,
        "applicability": "applicable",
        "note": note,
    }
