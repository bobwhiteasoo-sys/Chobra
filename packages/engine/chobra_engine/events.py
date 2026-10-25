"""Run event log with seq, domain_seq, event classes and a hash chain (sections 16, 18, 36)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .canonical import CANONICALIZATION_VERSION, sha256_hex

EventClass = Literal["domain", "operational"]
GENESIS_HASH = "0" * 64


@dataclass
class Event:
    run_id: str
    seq: int
    domain_seq: int | None
    event_class: EventClass
    tick: int
    type: str
    actor_id: str | None
    entity_id: str | None
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str = ""
    state_hash: str | None = None
    schema_version: str = "1.0"

    def hash_material(self) -> dict[str, Any]:
        return {
            "c14n": CANONICALIZATION_VERSION,
            "run_id": self.run_id,
            "seq": self.seq,
            "domain_seq": self.domain_seq,
            "event_class": self.event_class,
            "tick": self.tick,
            "type": self.type,
            "actor_id": self.actor_id,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "state_hash": self.state_hash,
            "prev_hash": self.prev_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventLog:
    run_id: str
    events: list[Event] = field(default_factory=list)
    last_seq: int = 0
    last_domain_seq: int = 0

    @property
    def last_hash(self) -> str:
        return self.events[-1].event_hash if self.events else GENESIS_HASH

    def append(
        self,
        *,
        tick: int,
        type: str,
        event_class: EventClass,
        payload: dict[str, Any],
        actor_id: str | None = None,
        entity_id: str | None = None,
        state_hash: str | None = None,
    ) -> Event:
        self.last_seq += 1
        domain_seq = None
        if event_class == "domain":
            self.last_domain_seq += 1
            domain_seq = self.last_domain_seq
        event = Event(
            run_id=self.run_id,
            seq=self.last_seq,
            domain_seq=domain_seq,
            event_class=event_class,
            tick=tick,
            type=type,
            actor_id=actor_id,
            entity_id=entity_id,
            payload=payload,
            prev_hash=self.last_hash,
            state_hash=state_hash,
        )
        event.event_hash = sha256_hex(event.hash_material())
        self.events.append(event)
        return event

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for event in self.events:
            if event.prev_hash != prev or sha256_hex(event.hash_material()) != event.event_hash:
                return False
            prev = event.event_hash
        return True

    def domain_events(self) -> list[Event]:
        return [e for e in self.events if e.event_class == "domain"]
