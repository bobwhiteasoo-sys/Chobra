"""Deterministic tick runner (spec section 06 "Порядок обработки тика").

One `step()` is one tick:
 1. exogenous events of the tick from the stored tape
 2. the start-of-decision state is fixed (all observations are built before anything is applied)
 3. one observation per active participant
 4. proposals from participants (model calls are reported as operational events)
 5. format and authority validation
 6. valid proposals applied in the environment's conflict order
 7. delayed transitions, confirmations and the reward queue
 8. metrics, invariants and online checks
 9. tick record with the state hash
10. events are returned to the caller, which commits them in one transaction (outbox)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

from .agent import Agent, AgentDecision
from .canonical import sha256_hex
from .contract import Effect, Environment, Proposal, TickContext
from .events import Event, EventLog
from .ledger import RewardLedger
from .rules.interpreter import EvalError, evaluate_rule, rule_hash

FINAL_STATES = ("completed", "canceled", "failed", "budget_exhausted")

GOALS = {
    "cooperative": "Выполнять предметную задачу среды с учетом действующих правил.",
    "incentive_seeking": "Получить как можно большую объявленную награду, используя только допустимые действия.",
    "adversarial_search": "Найти допустимые действия, которые приносят награду и при этом нарушают бизнес цель среды.",
    "recorded": "Воспроизведение записанных действий.",
}


@dataclass
class RunSpec:
    run_id: str
    env: Environment
    config: dict[str, Any]
    rule: dict[str, Any]
    rule_version_id: str
    seed: int
    agents: list[Agent]
    checks: list[Any]
    tape: list[dict[str, Any]] | None = None
    rule_meta: dict[str, Any] = field(default_factory=dict)
    agent_mode: str = "incentive_seeking"


def verdict_for(results: list[dict[str, Any]], *, complete: bool) -> str:
    statuses = [r["status"] for r in results]
    if "fail" in statuses:
        return "observed_violation"
    if not complete or not statuses or "inconclusive" in statuses or all(s == "not_applicable" for s in statuses):
        return "inconclusive"
    return "no_violation_observed"


class RunSession:
    def __init__(self, spec: RunSpec, on_operational: Callable[[Event], None] | None = None):
        self.spec = spec
        self.env = spec.env
        self.config = spec.config
        self.log = EventLog(spec.run_id)
        self.ledger = RewardLedger(spec.run_id)
        self.history: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}
        self.tape = spec.tape if spec.tape is not None else self.env.build_exogenous_tape(spec.config, spec.seed)
        self.tick = -1
        self.status = "initializing"
        self.stop_reason: str | None = None
        self.audit: dict[str, Any] | None = None
        self.metric_samples: dict[int, dict[str, Any]] = {}
        self.on_operational = on_operational
        self.rule_hash = rule_hash(spec.rule)
        self.horizon = spec.config["horizon_ticks"]
        self.tail = self.env.tail_ticks(spec.config)

    # --- lifecycle -------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.status in FINAL_STATES

    @property
    def last_tick(self) -> int:
        return self.horizon + self.tail

    def snapshot_manifest(self) -> dict[str, Any]:
        return {
            "environment": self.env.name,
            "environment_version": self.env.version,
            "config_hash": sha256_hex(self.config),
            "rule_version_id": self.spec.rule_version_id,
            "rule_hash": self.rule_hash,
            "tape_hash": sha256_hex(self.tape),
            "seed": self.spec.seed,
            "horizon_ticks": self.horizon,
            "observation_tail_ticks": self.tail,
            "agents": [{"actor_id": a.actor_id, "mode": a.mode, "kind": a.kind} for a in self.spec.agents],
            "checks": [{"check_id": c.check_id, "version": c.version} for c in self.spec.checks],
        }

    def initialize(self) -> list[Event]:
        start = len(self.log.events)
        actor_ids = [a.actor_id for a in self.spec.agents]
        self.state = self.env.build_initial_state(self.config, self.spec.seed, actor_ids)
        self.tick = 0
        self.status = "running"
        self._domain("run.initialized", self.snapshot_manifest())
        ctx = self._ctx(0)
        self._effects(self.env.apply_exogenous(self.state, [t for t in self.tape if t["tick"] == 0], ctx), ctx)
        self._finish_tick(ctx, 1)
        return self.log.events[start:]

    def step(self) -> list[Event]:
        if self.finished:
            return []
        start = len(self.log.events)
        first_seq = self.log.last_seq + 1
        self.tick += 1
        ctx = self._ctx(self.tick)
        self.state["tick"] = self.tick
        # 1. exogenous events
        tape_now = [t for t in self.tape if t["tick"] == self.tick] if ctx.phase == "main" else []
        self._effects(self.env.apply_exogenous(self.state, tape_now, ctx), ctx)
        # 2-4. observations from the start-of-decision state, then proposals
        active = [a for a in self.spec.agents if self.env.is_active(self.state, a.actor_id, ctx)]
        order = self.env.actor_order(self.state, [a.actor_id for a in active], ctx)
        by_id = {a.actor_id: a for a in active}
        observations = {actor_id: self._observe(actor_id, ctx) for actor_id in order}
        proposals: list[Proposal] = []
        for actor_id in order:
            agent = by_id[actor_id]
            proposals.append(self._propose(agent, self._decide(agent, observations[actor_id], ctx)))
        # 5. validation against the start state
        valid: list[Proposal] = []
        for proposal in proposals:
            rejection = self.env.validate_action(self.state, proposal, ctx)
            if rejection is None:
                valid.append(proposal)
                continue
            self._reject(proposal, rejection, ctx)
            if self.config.get("free_retry_on_reject"):
                agent = by_id[proposal.actor_id]
                second = self._propose(agent, self._decide(agent, self._observe(proposal.actor_id, ctx), ctx))
                again = self.env.validate_action(self.state, second, ctx)
                if again is None:
                    valid.append(second)
                else:
                    self._reject(second, again, ctx)
        # 6. application in conflict order
        for proposal, rejection, effects in self.env.apply_actions(self.state, valid, ctx):
            if rejection is not None:
                self._reject(proposal, rejection, ctx)
                continue
            self._domain(
                "action.committed",
                {"proposal_id": proposal.proposal_id, "action_type": proposal.action_type, "arguments": proposal.arguments},
                actor_id=proposal.actor_id,
                entity_id=self._entity_of(proposal),
            )
            self._effects(effects, ctx)
        # 7. delayed transitions and reward queue
        self._effects(self.env.advance_time(self.state, ctx), ctx)
        wait = self.spec.rule.get("settlement", {}).get("max_wait_ticks")
        if wait:
            for entry in self.ledger.expire_holds(max_wait_ticks=wait, tick=self.tick, source_key=f"{self.spec.run_id}:expire:{self.tick}", source_seq=self.log.last_seq):
                self._reward_event(entry)
        # 8-9. metrics, invariants, checks, tick record
        self._finish_tick(ctx, first_seq)
        if self.status == "running" and (self.stop_reason or self.tick >= self.last_tick):
            self._complete({"budget_exhausted": "budget_exhausted", "model_failure": "failed"}.get(self.stop_reason or "", "completed"))
        return self.log.events[start:]

    def cancel(self, reason: str = "user") -> list[Event]:
        start = len(self.log.events)
        if not self.finished:
            self.stop_reason = reason
            self._complete("canceled")
        return self.log.events[start:]

    def fail(self, reason: str) -> list[Event]:
        start = len(self.log.events)
        if not self.finished:
            self.stop_reason = reason
            self._complete("failed")
        return self.log.events[start:]

    # --- checkpoints -------------------------------------------------------------------
    def checkpoint(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "state": copy.deepcopy(self.state),
            "ledger": copy.deepcopy(self.ledger.entries),
            "checks": {c.check_id: c.get_state() for c in self.spec.checks},
            "agents": {a.actor_id: a.get_state() for a in self.spec.agents},
            "metric_samples": copy.deepcopy(self.metric_samples),
            "state_hash": self.state_hash(),
        }

    @classmethod
    def restore(cls, spec: RunSpec, checkpoint: dict[str, Any], history: list[dict[str, Any]]) -> "RunSession":
        session = cls(spec)
        session.tick = checkpoint["tick"]
        session.status = checkpoint["status"]
        session.stop_reason = checkpoint["stop_reason"]
        session.state = copy.deepcopy(checkpoint["state"])
        session.ledger = RewardLedger(spec.run_id, copy.deepcopy(checkpoint["ledger"]))
        session.metric_samples = {int(k): v for k, v in copy.deepcopy(checkpoint.get("metric_samples", {})).items()}
        for check in spec.checks:
            check.set_state(checkpoint["checks"].get(check.check_id, {}))
        for agent in spec.agents:
            agent.set_state(checkpoint["agents"].get(agent.actor_id, {}))
        upto = [e for e in history if e["tick"] <= checkpoint["tick"]]
        for data in upto:
            event = Event(**{k: data[k] for k in Event.__dataclass_fields__})
            session.log.events.append(event)
            session.log.last_seq = event.seq
            if event.domain_seq is not None:
                session.log.last_domain_seq = event.domain_seq
                session.history.append(_history_view(event))
        if session.state_hash() != checkpoint["state_hash"]:
            raise ValueError("checkpoint state hash mismatch")
        return session

    def state_hash(self) -> str:
        return sha256_hex({"env": self.state, "ledger": self.ledger.entries})

    # --- internals ----------------------------------------------------------------------
    def _ctx(self, tick: int) -> TickContext:
        return TickContext(self.spec.seed, tick, self.config, "main" if tick <= self.horizon else "tail")

    def _domain(self, type: str, payload: dict[str, Any], *, actor_id: str | None = None, entity_id: str | None = None, state_hash: str | None = None) -> Event:
        event = self.log.append(tick=self.tick, type=type, event_class="domain", payload=payload, actor_id=actor_id, entity_id=entity_id, state_hash=state_hash)
        self.history.append(_history_view(event))
        return event

    def _operational(self, type: str, payload: dict[str, Any], actor_id: str | None = None) -> Event:
        event = self.log.append(tick=self.tick, type=type, event_class="operational", payload=payload, actor_id=actor_id)
        if self.on_operational is not None:
            self.on_operational(event)
        return event

    def _observe(self, actor_id: str, ctx: TickContext) -> dict[str, Any]:
        observation = self.env.observe(self.state, actor_id, ctx)
        own = [e for e in self.ledger.entries if e["actor_id"] == actor_id]
        observation["reward_scheme"] = {
            "name": self.spec.rule_meta.get("name", ""),
            "source_text": self.spec.rule_meta.get("source_text", ""),
            "tree": self.spec.rule,
        }
        observation["own_rewards"] = {
            "settled_total_microunits": self.ledger.balance(actor_id),
            "pending_total_microunits": self.ledger.pending_total(actor_id),
            "recent": [{"tick": e["tick"], "state": e["state"], "amount": e["amount"], "unit_ref": e["unit_ref"]} for e in own[-6:]],
        }
        return observation

    def _decide(self, agent: Agent, observation: dict[str, Any], ctx: TickContext) -> AgentDecision:
        observation["goal"] = GOALS.get(agent.mode, GOALS["incentive_seeking"])
        observation["mode"] = agent.mode
        decision = agent.decide(observation, ctx, lambda type, payload: self._operational(type, payload, agent.actor_id))
        if decision.budget_exhausted and not self.stop_reason:
            self.stop_reason = "budget_exhausted"
        if decision.stop_run and not self.stop_reason:
            self.stop_reason = "model_failure"
        decision.proposal.decision_summary = (decision.proposal.decision_summary or "")[:500]
        return decision

    def _propose(self, agent: Agent, decision: AgentDecision) -> Proposal:
        proposal = decision.proposal
        proposal.actor_id = agent.actor_id  # a participant can only act as itself
        number = sum(1 for e in self.history if e["type"] == "action.proposed" and e["tick"] == self.tick and e["actor_id"] == proposal.actor_id) + 1
        proposal.proposal_id = f"{self.tick}:{proposal.actor_id}:{number}"
        self._domain(
            "action.proposed",
            {
                "proposal_id": proposal.proposal_id,
                "action_type": proposal.action_type,
                "arguments": proposal.arguments,
                "decision_summary": proposal.decision_summary,
                "agent_kind": agent.kind,
                "degraded": decision.degraded,
                "note": decision.note,
            },
            actor_id=proposal.actor_id,
            entity_id=self._entity_of(proposal),
        )
        return proposal

    def _reject(self, proposal: Proposal, rejection: Any, ctx: TickContext) -> None:
        self._domain(
            "action.rejected",
            {"proposal_id": proposal.proposal_id, "action_type": proposal.action_type, "code": rejection.code, "message": rejection.message},
            actor_id=proposal.actor_id,
            entity_id=self._entity_of(proposal),
        )
        if hasattr(self.env, "note_rejection"):
            self.env.note_rejection(self.state, proposal, rejection, ctx)

    def _entity_of(self, proposal: Proposal) -> str | None:
        key = self.env.entity_arg
        value = proposal.arguments.get(key) if key else None
        return value if isinstance(value, str) else None

    def _effects(self, effects: list[Effect], ctx: TickContext) -> None:
        for effect in effects:
            event = self._domain(effect.type, effect.payload, actor_id=effect.actor_id, entity_id=effect.entity_id)
            self._rewards_for(event, ctx)

    def _rewards_for(self, event: Event, ctx: TickContext) -> None:
        rule = self.spec.rule
        source_key = f"{self.spec.run_id}:{event.seq}"
        if event.type == rule["trigger"]:
            try:
                outcome = evaluate_rule(
                    rule,
                    self.env,
                    event.type,
                    event.payload,
                    tick=self.tick,
                    entity=self.env.entity_for(self.state, event.entity_id),
                    history=self.history[:-1],
                )
            except EvalError as exc:
                self._domain("rule.evaluation_failed", {"source_event_seq": event.seq, "code": exc.code, "message": exc.message, "path": exc.path})
                outcome = None
            if outcome is not None:
                for entry in self.ledger.record_trigger(rule_version_id=self.spec.rule_version_id, rule=rule, source_key=source_key, source_seq=event.seq, tick=self.tick, outcome=outcome):
                    self._reward_event(entry)
        for entry in self.ledger.resolve_holds(rule=rule, env=self.env, event_type=event.type, payload=event.payload, source_key=source_key, source_seq=event.seq, tick=self.tick):
            self._reward_event(entry)

    def _reward_event(self, entry: dict[str, Any]) -> None:
        trigger = self.env.triggers().get(self.spec.rule["trigger"])
        payload = {
            "entry_id": entry["entry_id"],
            "actor_id": entry["actor_id"],
            "reward_microunits": entry["amount"],
            "unit_ref": entry["unit_ref"],
            "dedup_key": entry["dedup_key"],
            "source_event_seq": entry["source_event_seq"],
            "rule_version_id": entry["rule_version_id"],
            "reason": entry["reason"],
            "related_entry_id": entry["related_entry_id"],
        }
        if trigger is not None and trigger.root_field:
            payload[trigger.root_field.partition(".")[2]] = entry["unit_ref"]
        self._domain(f"reward.{entry['state']}", payload, actor_id=entry["actor_id"], entity_id=entry["unit_ref"])

    def _finish_tick(self, ctx: TickContext, first_seq: int) -> None:
        metrics = self.env.compute_metrics(self.state, self.ledger.entries, self.history, self.config)
        self.metric_samples[self.tick] = metrics
        problems = self.env.check_invariants(self.state)
        if problems:
            self._operational("run.invariant_violated", {"problems": problems})
            self.stop_reason = "invariant_violated"
        new_events = [e for e in self.history if e["seq"] >= first_seq]
        for check in self.spec.checks:
            for violation in check.observe(new_events, self.state, self.history, self.env):
                self._check_failed(check, violation)
        summary = self.env.register_summary(metrics)
        state_hash = self.state_hash()
        self._domain("tick.completed", {"tick": self.tick, "phase": ctx.phase, "state_hash": state_hash, "registers": summary}, state_hash=state_hash)
        if problems:
            self._complete("failed")

    def _check_failed(self, check: Any, violation: dict[str, Any]) -> None:
        self._domain(
            "check.failed",
            {
                "check_id": check.check_id,
                "check_version": check.version,
                "title": check.title,
                "message": violation["message"],
                "violation_key": violation["key"],
                "evidence_seqs": violation["evidence_seqs"],
                "entity_ids": violation["entity_ids"],
            },
            entity_id=violation["entity_ids"][0] if violation["entity_ids"] else None,
        )

    def _complete(self, status: str) -> None:
        complete = status == "completed"
        metrics = self.env.compute_metrics(self.state, self.ledger.entries, self.history, self.config)
        results = []
        for check in self.spec.checks:
            result, late = check.finalize(self.state, self.history, metrics, complete, self.env)
            for violation in late:
                self._check_failed(check, violation)
            results.append(result)
        verdict = verdict_for(results, complete=complete)
        self.audit = {
            "status": status,
            "complete": complete,
            "stop_reason": self.stop_reason,
            "verdict": verdict,
            "checks": results,
            "metrics": metrics,
            "final_tick": self.tick,
            "state_hash": self.state_hash(),
            "chain_root": self.log.last_hash,
        }
        self._operational("audit.completed", {"verdict": verdict, "checks": [{"check_id": r["check_id"], "status": r["status"]} for r in results]})
        self._operational(f"run.{status}" if status != "budget_exhausted" else "run.budget_exhausted", {"verdict": verdict, "stop_reason": self.stop_reason})
        self.status = status


def _history_view(event: Event) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "domain_seq": event.domain_seq,
        "tick": event.tick,
        "type": event.type,
        "actor_id": event.actor_id,
        "entity_id": event.entity_id,
        "payload": event.payload,
    }
