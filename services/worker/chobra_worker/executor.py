"""Job handlers. A run advances one committed tick at a time (spec section 16 "Гарантии записи")."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chobra_agents.budget import PRICES, BudgetExhausted
from chobra_audit.comparison import compare_runs
from chobra_audit.findings import build_findings
from chobra_audit.minimize import minimize_counterexample
from chobra_engine.canonical import sha256_hex
from chobra_engine.events import Event
from chobra_engine.runner import RunSession

from chobra_api.db import SessionLocal, set_tenant
from chobra_api.models import (
    BudgetReservation,
    Comparison,
    ExperimentBatch,
    Finding,
    MetricSample,
    ModelCall,
    Outbox,
    Report,
    RewardLedgerEntry,
    Run,
    RunEvent,
    StateCheckpoint,
)
from chobra_api.objects import get_json, put_json
from chobra_api.run_loader import ModelKeyMissing, build_agents, recipe_for_run
from chobra_api.services import FINAL_RUN_STATES, enqueue, utcnow

from .jobs import Lease, extend

log = logging.getLogger("chobra.worker")


class LeaseLost(Exception):
    pass


def tenant_session(workspace_id: uuid.UUID) -> Session:
    db = SessionLocal()
    set_tenant(db, None, [workspace_id])
    return db


# --- budget ----------------------------------------------------------------------------

class DbBudget:
    """Batch budget with reservations committed under a row lock on the batch (AC-037)."""

    def __init__(self, batch_id: uuid.UUID, run_id: uuid.UUID, workspace_id: uuid.UUID):
        self.batch_id = batch_id
        self.run_id = run_id
        self.workspace_id = workspace_id

    def reserve(self, *, input_tokens: int, output_tokens: int) -> str:
        db = tenant_session(self.workspace_id)
        try:
            batch = db.get(ExperimentBatch, self.batch_id, with_for_update=True)
            used = dict(batch.budget_used)
            limits = batch.budget
            if used.get("calls", 0) + 1 > limits.get("max_model_calls", 0):
                raise BudgetExhausted("calls")
            money = limits.get("money_limit_microusd")
            plan = batch.immutable_plan
            model = next((v["model"] for v in plan["variants"] if v["kind"] == "model"), None)
            price = PRICES.get(model) if model else None
            if money is not None and price is not None:
                spent = price.cost_microusd(used.get("input_tokens", 0) + used.get("reserved_input", 0) + input_tokens, used.get("output_tokens", 0) + used.get("reserved_output", 0) + output_tokens)
                if spent > money:
                    raise BudgetExhausted("money")
            used["calls"] = used.get("calls", 0) + 1
            used["reserved_input"] = used.get("reserved_input", 0) + input_tokens
            used["reserved_output"] = used.get("reserved_output", 0) + output_tokens
            batch.budget_used = used
            reservation = BudgetReservation(workspace_id=self.workspace_id, batch_id=self.batch_id, run_id=self.run_id, reserved={"input_tokens": input_tokens, "output_tokens": output_tokens})
            db.add(reservation)
            db.commit()
            return str(reservation.id)
        finally:
            db.close()

    def settle(self, token: str, usage: dict[str, int] | None) -> None:
        db = tenant_session(self.workspace_id)
        try:
            batch = db.get(ExperimentBatch, self.batch_id, with_for_update=True)
            reservation = db.get(BudgetReservation, uuid.UUID(token))
            if reservation is None or reservation.state != "reserved":
                db.rollback()
                return
            used = dict(batch.budget_used)
            used["reserved_input"] = used.get("reserved_input", 0) - reservation.reserved["input_tokens"]
            used["reserved_output"] = used.get("reserved_output", 0) - reservation.reserved["output_tokens"]
            if usage is None:
                # Unknown usage keeps the reserved upper bound as spent, pending reconciliation.
                used["unknown_usage_calls"] = used.get("unknown_usage_calls", 0) + 1
                used["input_tokens"] = used.get("input_tokens", 0) + reservation.reserved["input_tokens"]
                used["output_tokens"] = used.get("output_tokens", 0) + reservation.reserved["output_tokens"]
                reservation.state = "awaiting_reconciliation"
            else:
                used["input_tokens"] = used.get("input_tokens", 0) + usage.get("input_tokens", 0)
                used["output_tokens"] = used.get("output_tokens", 0) + usage.get("output_tokens", 0)
                reservation.state = "settled"
                reservation.actual = usage
            batch.budget_used = used
            db.commit()
        finally:
            db.close()


# --- persistence of one tick -----------------------------------------------------------

def _event_row(run: Run, event: Event) -> RunEvent:
    return RunEvent(workspace_id=run.workspace_id, run_id=run.id, seq=event.seq, domain_seq=event.domain_seq, event_class=event.event_class, tick=event.tick, type=event.type,
                    actor_id=event.actor_id, entity_id=event.entity_id, payload=event.payload, prev_hash=event.prev_hash, event_hash=event.event_hash, state_hash=event.state_hash)


def _history(db: Session, run: Run) -> list[dict[str, Any]]:
    rows = db.execute(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)).scalars().all()
    return [{"run_id": str(run.id), "seq": r.seq, "domain_seq": r.domain_seq, "event_class": r.event_class, "tick": r.tick, "type": r.type, "actor_id": r.actor_id,
             "entity_id": r.entity_id, "payload": r.payload, "prev_hash": r.prev_hash, "event_hash": r.event_hash, "state_hash": r.state_hash, "schema_version": "1.0"} for r in rows]


def commit_tick(run_id: uuid.UUID, workspace_id: uuid.UUID, generation: int, session: RunSession, events: list[Event], persisted_ledger: int) -> int:
    db = tenant_session(workspace_id)
    try:
        run = db.get(Run, run_id, with_for_update=True)
        if run.lease_generation != generation:
            raise LeaseLost(f"run {run_id}: lease generation {run.lease_generation} != {generation}")
        # Operational events of this tick may already be stored by record_operational.
        known = set(db.execute(select(RunEvent.seq).where(RunEvent.run_id == run.id, RunEvent.seq.in_([e.seq for e in events]))).scalars())
        for event in events:
            if event.seq not in known:
                db.add(_event_row(run, event))
        checkpoint = session.checkpoint()
        key = f"{workspace_id}/runs/{run_id}/checkpoints/{session.tick:05d}.json"
        stored = put_json(key, {"state": checkpoint["state"], "ledger": checkpoint["ledger"], "checks": checkpoint["checks"], "agents": checkpoint["agents"],
                                "metric_samples": {str(session.tick): checkpoint["metric_samples"].get(session.tick, {})}, "status": checkpoint["status"], "stop_reason": checkpoint["stop_reason"],
                                "tick": checkpoint["tick"], "state_hash": checkpoint["state_hash"]})
        db.add(StateCheckpoint(workspace_id=workspace_id, run_id=run.id, tick=session.tick, seq=session.log.last_seq, state_hash=checkpoint["state_hash"], object_key=key, size_bytes=stored["size"]))
        for entry in session.ledger.entries[persisted_ledger:]:
            db.add(RewardLedgerEntry(workspace_id=workspace_id, run_id=run.id, entry_id=entry["entry_id"], rule_version_id=entry["rule_version_id"], source_event_key=entry["source_event_key"],
                                     source_event_seq=entry["source_event_seq"], actor_id=entry["actor_id"], unit_ref=entry["unit_ref"], dedup_key=entry["dedup_key"], amount=entry["amount"],
                                     state=entry["state"], reason=entry["reason"], related_entry_id=entry["related_entry_id"], tick=entry["tick"]))
        for metric_id, sample in session.metric_samples.get(session.tick, {}).items():
            value = sample.get("value")
            db.add(MetricSample(workspace_id=workspace_id, run_id=run.id, tick=session.tick, metric_id=metric_id, value=None if value is None else str(value),
                                numerator=sample.get("numerator"), denominator=sample.get("denominator"), applicability=sample["applicability"], unit=sample["unit"]))
        if events:
            db.add(Outbox(workspace_id=workspace_id, aggregate_id=run.id, event_type="run.events_committed", payload={"from_seq": events[0].seq, "to_seq": events[-1].seq, "tick": session.tick}))
        run.last_seq = session.log.last_seq
        run.current_tick = session.tick
        run.chain_root = session.log.last_hash
        if session.finished:
            run.status = session.status
            run.stop_reason = session.stop_reason
            run.verdict = session.audit["verdict"]
            run.audit = session.audit
            run.finished_at = utcnow()
        elif run.status in ("initializing", "queued", "resume_requested"):
            run.status = "running"
        db.commit()
        return len(session.ledger.entries)
    finally:
        db.close()


def record_operational(run_id: uuid.UUID, workspace_id: uuid.UUID, generation: int, event: Event) -> None:
    """Model waits are committed right away in their own short transaction (event_class=operational)."""
    db = tenant_session(workspace_id)
    try:
        run = db.get(Run, run_id, with_for_update=True)
        if run.lease_generation != generation:
            raise LeaseLost("lease lost while waiting for the model")
        db.add(_event_row(run, event))
        payload = event.payload
        if event.type == "model_call.started":
            db.add(ModelCall(id=uuid.UUID(payload["model_call_id"]), workspace_id=workspace_id, run_id=run_id, actor_id=event.actor_id or "", tick=event.tick, status="started",
                             provider=payload["provider"], model=payload["model"], request_hash=payload["request_hash"], lease_generation=generation, started_at=utcnow()))
        elif event.type in ("model_call.completed", "model_call.failed"):
            call = db.get(ModelCall, uuid.UUID(payload["model_call_id"]))
            if call is not None:
                call.status = "completed" if event.type == "model_call.completed" else "failed"
                call.usage = payload.get("usage")
                call.response_id = payload.get("response_id")
                call.error_kind = payload.get("error_kind")
                call.finished_at = utcnow()
        run.last_seq = max(run.last_seq, event.seq)
        db.commit()
    finally:
        db.close()


# --- run execution -----------------------------------------------------------------------

def execute_run(lease: Lease, worker_db: Session) -> None:
    db = tenant_session(lease.workspace_id)
    try:
        run = db.get(Run, lease.target_id, with_for_update=True)
        if run is None or run.status in FINAL_RUN_STATES or run.status == "paused":
            db.commit()
            return
        run.lease_generation = lease.generation
        if run.started_at is None:
            run.started_at = utcnow()
        resuming_cancel = run.status == "cancel_requested"
        if run.status not in ("cancel_requested", "pause_requested"):
            run.status = "initializing" if run.current_tick < 0 else "running"
        db.commit()
        recipe = recipe_for_run(db, run)
        budget = DbBudget(run.batch_id, run.id, run.workspace_id)
        try:
            agents = build_agents(db, run, recipe, budget)
        except ModelKeyMissing as exc:
            run = db.get(Run, lease.target_id, with_for_update=True)
            run.status, run.stop_reason, run.verdict, run.finished_at = "failed", "model_key_missing", "inconclusive", utcnow()
            run.audit = {"status": "failed", "complete": False, "stop_reason": "model_key_missing", "verdict": "inconclusive", "checks": [], "metrics": {}, "message": str(exc)}
            db.commit()
            _maybe_finalize_batch(db, run)
            return
        spec = recipe.spec(agents)
        latest = db.execute(select(StateCheckpoint).where(StateCheckpoint.run_id == run.id).order_by(StateCheckpoint.tick.desc()).limit(1)).scalar_one_or_none()
        generation = lease.generation
        session = None

        def on_operational(event: Event) -> None:
            record_operational(run.id, run.workspace_id, generation, event)

        if latest is None:
            session = RunSession(spec, on_operational=on_operational)
            events = session.initialize()
            persisted = commit_tick(run.id, run.workspace_id, generation, session, events, 0)
        else:
            data = get_json(latest.object_key)
            checkpoint = {"tick": data["tick"], "status": data["status"], "stop_reason": data["stop_reason"], "state": data["state"], "ledger": data["ledger"], "checks": data["checks"],
                          "agents": data["agents"], "metric_samples": data["metric_samples"], "state_hash": data["state_hash"]}
            session = RunSession.restore(spec, checkpoint, _history(db, run))
            session.on_operational = on_operational
            persisted = len(session.ledger.entries)
        db.close()
        while not session.finished:
            control = tenant_session(run.workspace_id)
            try:
                current = control.get(Run, run.id)
                status = current.status
                if current.lease_generation != generation:
                    raise LeaseLost("lease taken over")
                if status == "pause_requested":
                    current.status = "paused"
                    event = session.log.append(tick=session.tick, type="run.paused", event_class="operational", payload={"tick": session.tick})
                    control.add(_event_row(current, event))
                    current.last_seq = event.seq
                    control.commit()
                    return
                control.commit()
            finally:
                control.close()
            if status == "cancel_requested" or resuming_cancel:
                events = session.cancel("user")
            else:
                events = session.step()
            persisted = commit_tick(run.id, run.workspace_id, generation, session, events, persisted)
            extend(worker_db, lease)
        final = tenant_session(run.workspace_id)
        try:
            done = final.get(Run, run.id)
            _store_findings(final, done, session)
            final.commit()
            _maybe_finalize_batch(final, done)
        finally:
            final.close()
    finally:
        db.close()


def _store_findings(db: Session, run: Run, session: RunSession) -> None:
    recipe = recipe_for_run(db, run)
    events = [e.to_dict() for e in session.log.events]
    for card in build_findings(recipe, events, session.audit):
        exists = db.execute(select(Finding).where(Finding.run_id == run.id, Finding.check_id == card["check_id"])).scalar_one_or_none()
        if exists is None:
            db.add(Finding(workspace_id=run.workspace_id, project_id=run.project_id, run_id=run.id, check_id=card["check_id"], card=card,
                           evidence_range={"seqs": card["evidence_seqs"], "tick": card["violation_tick"], "check_failed_seq": card["check_failed_seq"]}))


def _maybe_finalize_batch(db: Session, run: Run) -> None:
    pending = db.execute(select(func.count()).select_from(Run).where(Run.batch_id == run.batch_id, Run.status.not_in(list(FINAL_RUN_STATES)))).scalar()
    if pending == 0:
        enqueue(db, run.workspace_id, "batch.finalize", run.batch_id)
        db.commit()


# --- batch finalization: comparison --------------------------------------------------------

def finalize_batch(lease: Lease) -> None:
    db = tenant_session(lease.workspace_id)
    try:
        batch = db.get(ExperimentBatch, lease.target_id, with_for_update=True)
        runs = db.execute(select(Run).where(Run.batch_id == batch.id)).scalars().all()
        existing = db.execute(select(Comparison).where(Comparison.batch_id == batch.id).order_by(Comparison.created_at.desc()).limit(1)).scalar_one_or_none()
        excluded = {item["run_id"] for item in (existing.excluded_runs if existing else [])}
        summaries = []
        for r in runs:
            if str(r.id) in excluded:
                continue
            audit = r.audit or {}
            summaries.append({"run_id": str(r.id), "variant": r.variant_label, "mode": r.agent_mode, "model": r.snapshot.get("agent_profile_id") if r.agent_kind == "model" else "scripted",
                              "seed": r.seed, "tape_hash": r.tape_hash, "status": r.status, "complete": r.status == "completed", "verdict": r.verdict,
                              "metrics": audit.get("metrics", {}), "checks": {c["check_id"]: c["status"] for c in audit.get("checks", [])},
                              "environment_version": r.snapshot.get("environment_version"), "config_hash": sha256_hex(r.snapshot.get("config", {}))})
        labels = [v["label"] for v in batch.immutable_plan["variants"]]
        environment = batch.immutable_plan["environment"]
        pairs = [compare_runs(summaries, baseline=labels[0], candidate=label, environment=environment) for label in labels[1:]]
        single = None
        if len(labels) == 1:
            single = compare_runs(summaries, baseline=labels[0], candidate=labels[0], environment=environment)
        result = {"variants": labels, "pairs": pairs, "primary": pairs[0] if pairs else single, "single_variant": len(labels) == 1}
        statuses = {r.status for r in runs}
        batch.status = "completed" if statuses == {"completed"} else ("canceled" if statuses <= {"canceled"} else "completed_with_incomplete")
        completeness = {"planned": batch.planned_runs, "completed": sum(1 for r in runs if r.status == "completed"), "incomplete": sum(1 for r in runs if r.status != "completed"),
                        "excluded": len(excluded)}
        if existing is not None and lease.args.get("comparison_id"):
            existing.result = result
            existing.completeness = completeness
            existing.settings_hash = sha256_hex({"excluded": sorted(excluded), "plan": batch.plan_hash})
        else:
            db.add(Comparison(workspace_id=batch.workspace_id, project_id=batch.project_id, batch_id=batch.id, result=result, completeness=completeness,
                              settings_hash=sha256_hex({"excluded": sorted(excluded), "plan": batch.plan_hash}), excluded_runs=existing.excluded_runs if existing else []))
        db.commit()
    finally:
        db.close()


# --- other jobs -------------------------------------------------------------------------------

def minimize_finding(lease: Lease) -> None:
    db = tenant_session(lease.workspace_id)
    try:
        finding = db.get(Finding, lease.target_id, with_for_update=True)
        run = db.get(Run, finding.run_id)
        finding.minimization = {"status": "running"}
        db.commit()
        events = _history(db, run)
        result = minimize_counterexample(recipe_for_run(db, run), events, check_id=finding.check_id)
        finding = db.get(Finding, lease.target_id, with_for_update=True)
        finding.minimization = {**result, "finished_at": datetime.now(timezone.utc).isoformat()}
        db.commit()
    finally:
        db.close()


def generate_report(lease: Lease) -> None:
    from chobra_reporting.build import build_report

    db = tenant_session(lease.workspace_id)
    try:
        report = db.get(Report, lease.target_id, with_for_update=True)
        try:
            object_key, snapshot = build_report(db, report)
            report.status, report.object_key, report.snapshot = "ready", object_key, snapshot
        except Exception as exc:  # noqa: BLE001 - the reason is stored and the export can be retried
            log.exception("report failed")
            report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        db.commit()
    finally:
        db.close()


HANDLERS = {
    "batch.finalize": finalize_batch,
    "finding.minimize": minimize_finding,
    "report.generate": generate_report,
}
