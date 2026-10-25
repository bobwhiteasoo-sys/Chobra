"""Participant protocol used by the runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .contract import Proposal, TickContext

Notify = Callable[[str, dict[str, Any]], None]


@dataclass
class AgentDecision:
    proposal: Proposal
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    degraded: bool = False
    budget_exhausted: bool = False
    stop_run: bool = False
    note: str = ""


class Agent(Protocol):
    actor_id: str
    mode: str
    kind: str  # "scripted", "model" or "replay"

    def decide(self, observation: dict[str, Any], ctx: TickContext, notify: Notify) -> AgentDecision: ...

    def get_state(self) -> dict[str, Any]: ...

    def set_state(self, state: dict[str, Any]) -> None: ...
