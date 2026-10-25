"""Series, runs, live stream, evidence, comparisons and reports."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from chobra_audit.comparison import compare_runs
from chobra_audit.fixes import check_fix_on_counterexample, propose_fixes
from chobra_audit.replay_verify import verify_replay
from chobra_engine.canonical import sha256_hex
from chobra_engine.rules import validate_rule
from chobra_envs.registry import get_environment

from ..access import authenticate, load_roles
from ..db import SessionLocal, set_tenant
from ..deps import CtxDep
from ..errors import ApiError, conflict, not_found
from ..models import (
    Comparison,
    ExperimentBatch,
    Finding,
    IdempotencyKey,
    MetricSample,
    ModelCall,
    Project,
    Report,
    RewardLedgerEntry,
    RuleVersion,
    Run,
    RunEvent,
    StateCheckpoint,
)
from ..objects import file_path, get_json
from ..run_loader import recipe_for_run
from ..security import sign_link, verify_link
from ..services import RUN_COMMANDS, audit, create_batch, enqueue, expand_plan, next_version, run_command, utcnow

router = APIRouter()


# --- series ------------------------------------------------------------------------------

class PlanBody(BaseModel):
    project_id: uuid.UUID
    scenario_version_id: uuid.UUID
    variants: list[dict[str, Any]]
    conditions: dict[str, Any]
    agent_profile_id: uuid.UUID | None = None
    limits: dict[str, Any] = {}
    checks: list[str] | None = None
    failure_policy: str = Field(default="wait", pattern="^(wait|stop)$")
    title: str = ""


@router.post("/batches/estimate")
def estimate(payload: PlanBody, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "run")
    return expand_plan(ctx.db, project, json.loads(payload.model_dump_json()))


@router.post("/batches", status_code=202)
def start_batch(payload: PlanBody, ctx: CtxDep, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "run")
    body = json.loads(payload.model_dump_json())
    request_hash = sha256_hex(body)
    if idempotency_key:
        previous = ctx.db.execute(select(IdempotencyKey).where(IdempotencyKey.workspace_id == project.workspace_id, IdempotencyKey.user_id == ctx.user.id,
                                                              IdempotencyKey.operation == "batch.create", IdempotencyKey.key == idempotency_key)).scalar_one_or_none()
        if previous is not None:
            if previous.request_hash != request_hash:
                raise conflict("IDEMPOTENCY_MISMATCH", "Ключ Idempotency-Key уже использован с другим телом запроса")
            return previous.response
    expanded = expand_plan(ctx.db, project, body)
    batch = create_batch(ctx.db, project, ctx.user.id, expanded, payload.title)
    response = {"batch_id": str(batch.id), "status": batch.status, "planned_runs": batch.planned_runs, "plan_hash": f"sha256:{batch.plan_hash}",
                "links": {"status": f"/api/v1/batches/{batch.id}"}}
    if idempotency_key:
        ctx.db.add(IdempotencyKey(workspace_id=project.workspace_id, user_id=ctx.user.id, operation="batch.create", key=idempotency_key, request_hash=request_hash, response=response, status_code=202))
    ctx.db.commit()
    return response


def _run(r: Run) -> dict[str, Any]:
    return {"id": str(r.id), "batch_id": str(r.batch_id), "project_id": str(r.project_id), "variant_id": r.variant_id, "variant_label": r.variant_label, "seed": r.seed,
            "agent_mode": r.agent_mode, "agent_kind": r.agent_kind, "kind": r.kind, "status": r.status, "stop_reason": r.stop_reason, "verdict": r.verdict,
            "current_tick": r.current_tick, "horizon_ticks": r.horizon_ticks, "tail_ticks": r.tail_ticks, "last_seq": r.last_seq, "snapshot_hash": r.snapshot_hash,
            "tape_hash": r.tape_hash, "chain_root": r.chain_root, "allowed_commands": RUN_COMMANDS.get(r.status, []),
            "rule_version_id": str(r.rule_version_id), "scenario_version_id": str(r.scenario_version_id),
            "started_at": r.started_at.isoformat() if r.started_at else None, "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def _get_batch(ctx, batch_id: uuid.UUID) -> ExperimentBatch:
    batch = ctx.db.get(ExperimentBatch, batch_id)
    if batch is None:
        raise not_found("Серия")
    ctx.require_project(batch.project_id)
    return batch


@router.get("/batches/{batch_id}")
def get_batch(batch_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    batch = _get_batch(ctx, batch_id)
    runs = ctx.db.execute(select(Run).where(Run.batch_id == batch.id).order_by(Run.variant_label, Run.seed)).scalars().all()
    counts = {"planned": batch.planned_runs, "started": sum(1 for r in runs if r.started_at), "completed": sum(1 for r in runs if r.status == "completed"),
              "incomplete": sum(1 for r in runs if r.status in ("canceled", "failed", "budget_exhausted")), "in_progress": sum(1 for r in runs if r.status not in ("completed", "canceled", "failed", "budget_exhausted", "queued"))}
    comparison = ctx.db.execute(select(Comparison).where(Comparison.batch_id == batch.id).order_by(Comparison.created_at.desc()).limit(1)).scalar_one_or_none()
    return {"id": str(batch.id), "project_id": str(batch.project_id), "title": batch.title, "status": batch.status, "plan": batch.immutable_plan, "plan_hash": batch.plan_hash,
            "counts": counts, "budget": batch.budget, "budget_used": batch.budget_used, "runs": [_run(r) for r in runs], "comparison_id": str(comparison.id) if comparison else None,
            "created_at": batch.created_at.isoformat()}


@router.get("/projects/{project_id}/batches")
def list_batches(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id)
    rows = ctx.db.execute(select(ExperimentBatch).where(ExperimentBatch.project_id == project_id).order_by(ExperimentBatch.created_at.desc()).limit(100)).scalars().all()
    return {"items": [{"id": str(b.id), "title": b.title, "status": b.status, "planned_runs": b.planned_runs, "created_at": b.created_at.isoformat(), "modes": b.immutable_plan.get("modes", [])} for b in rows]}


@router.get("/workspaces/{workspace_id}/runs")
def workspace_runs(workspace_id: uuid.UUID, ctx: CtxDep, limit: int = 50) -> dict[str, Any]:
    ctx.require_workspace(workspace_id)
    rows = ctx.db.execute(select(Run, Project.name).join(Project, Project.id == Run.project_id).where(Run.workspace_id == workspace_id).order_by(Run.created_at.desc()).limit(min(limit, 100))).all()
    items = []
    for run, project_name in rows:
        try:
            ctx.require_project(run.project_id)
        except ApiError:
            continue
        items.append({**_run(run), "project_name": project_name})
    return {"items": items}


@router.post("/batches/{batch_id}/cancel")
def cancel_batch(batch_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    batch = _get_batch(ctx, batch_id)
    ctx.require_project(batch.project_id, "run")
    for run in ctx.db.execute(select(Run).where(Run.batch_id == batch.id)).scalars():
        if "cancel" in RUN_COMMANDS.get(run.status, []):
            run_command(ctx.db, run, "cancel")
    audit(ctx.db, batch.workspace_id, ctx.user.id, "batch.cancel", f"batch:{batch.id}")
    ctx.db.commit()
    return get_batch(batch_id, ctx)


# --- runs ----------------------------------------------------------------------------------

def _get_run(ctx, run_id: uuid.UUID, need: str = "read") -> Run:
    run = ctx.db.get(Run, run_id)
    if run is None:
        raise not_found("Запуск")
    ctx.require_project(run.project_id, need)
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    project = ctx.db.get(Project, run.project_id)
    rule = ctx.db.get(RuleVersion, run.rule_version_id)
    batch = ctx.db.get(ExperimentBatch, run.batch_id)
    findings = ctx.db.execute(select(Finding).where(Finding.run_id == run.id)).scalars().all()
    calls = ctx.db.execute(select(func.count()).select_from(ModelCall).where(ModelCall.run_id == run.id)).scalar()
    return {**_run(run), "project": {"id": str(project.id), "name": project.name, "environment_id": project.environment_id},
            "rule": {"id": str(rule.id), "name": rule.name, "version": rule.version, "ast_hash": rule.ast_hash, "source_text": rule.source_text},
            "batch": {"id": str(batch.id), "title": batch.title, "status": batch.status}, "audit": run.audit, "snapshot": run.snapshot,
            "findings": [{"id": str(f.id), "check_id": f.check_id, "title": f.card.get("title"), "replay_status": f.replay_status} for f in findings], "model_calls": calls}


@router.post("/runs/{run_id}/{command}")
def command(run_id: uuid.UUID, command: str, ctx: CtxDep) -> dict[str, Any]:
    if command not in ("pause", "resume", "cancel"):
        raise not_found("Команда")
    run = _get_run(ctx, run_id, "run")
    run_command(ctx.db, run, command)
    audit(ctx.db, run.workspace_id, ctx.user.id, f"run.{command}", f"run:{run.id}")
    ctx.db.commit()
    return _run(run)


def _event(e: RunEvent) -> dict[str, Any]:
    return {"schema_version": "1.0", "run_id": str(e.run_id), "seq": e.seq, "event_class": e.event_class, "domain_seq": e.domain_seq, "tick": e.tick, "type": e.type,
            "actor_id": e.actor_id, "entity_id": e.entity_id, "created_at": e.created_at.isoformat() if e.created_at else None, "payload": e.payload,
            "state_hash": e.state_hash, "event_hash": e.event_hash, "prev_hash": e.prev_hash}


@router.get("/runs/{run_id}/events")
def events(run_id: uuid.UUID, ctx: CtxDep, after: int = 0, limit: int = 500, until: int | None = None, domain_only: bool = False) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    query = select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.seq > after)
    if until is not None:
        query = query.where(RunEvent.seq <= until)
    if domain_only:
        query = query.where(RunEvent.event_class == "domain")
    rows = ctx.db.execute(query.order_by(RunEvent.seq).limit(min(max(limit, 1), 2000))).scalars().all()
    return {"items": [_event(e) for e in rows], "last_seq": run.last_seq, "status": run.status}


def _fetch_stream(run_id: uuid.UUID, user_id: uuid.UUID, after: int) -> tuple[list[dict[str, Any]], str, int, bool]:
    db = SessionLocal()
    try:
        from ..models import User

        user = db.get(User, user_id)
        roles = load_roles(db, user)
        set_tenant(db, user_id, roles.keys())
        run = db.get(Run, run_id)
        if run is None or run.workspace_id not in roles:
            return [], "revoked", 0, False
        rows = db.execute(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after).order_by(RunEvent.seq).limit(500)).scalars().all()
        return [_event(e) for e in rows], run.status, run.last_seq, True
    finally:
        db.close()


@router.get("/runs/{run_id}/stream")
async def stream(run_id: uuid.UUID, request: Request, cursor: int | None = None, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")) -> StreamingResponse:
    """SSE of committed events only. `id` is the committed seq; heartbeats every 15 s carry no id."""
    db = SessionLocal()
    try:
        ctx = await run_in_threadpool(authenticate, request, db)
        run = await run_in_threadpool(lambda: _get_run(ctx, run_id))
        user_id = ctx.user.id
        session_token = request.cookies.get("chobra_session")
    finally:
        db.close()
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else (cursor or 0)
    from ..config import settings
    from ..security import load_session

    async def generate():
        last = start
        last_beat = time.monotonic()
        last_check = time.monotonic()
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            items, status, last_seq, allowed = await run_in_threadpool(_fetch_stream, run_id, user_id, last)
            if time.monotonic() - last_check > settings.access_recheck_seconds:
                last_check = time.monotonic()

                def session_alive() -> bool:
                    check_db = SessionLocal()
                    try:
                        alive = load_session(check_db, session_token) is not None
                        check_db.commit()
                        return alive
                    finally:
                        check_db.close()

                allowed = allowed and await run_in_threadpool(session_alive)
            if not allowed:
                yield "event: access_revoked\ndata: {\"message\": \"Доступ к запуску отозван\"}\n\n"
                return
            for item in items:
                last = item["seq"]
                yield f"id: {item['seq']}\nevent: run_event\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            if time.monotonic() - last_beat >= settings.sse_heartbeat_seconds:
                last_beat = time.monotonic()
                yield f"event: heartbeat\ndata: {json.dumps({'last_seq': last_seq, 'status': status, 'server_time': utcnow().isoformat()})}\n\n"
            if not items and status in ("completed", "canceled", "failed", "budget_exhausted") and last >= last_seq:
                yield f"event: end\ndata: {json.dumps({'status': status, 'last_seq': last_seq})}\n\n"
                return
            await asyncio.sleep(0.25 if not items else 0.02)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/runs/{run_id}/state")
def state(run_id: uuid.UUID, ctx: CtxDep, tick: int | None = None, seq: int | None = None) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    query = select(StateCheckpoint).where(StateCheckpoint.run_id == run.id)
    if seq is not None:
        query = query.where(StateCheckpoint.seq <= seq)
    if tick is not None:
        query = query.where(StateCheckpoint.tick <= tick)
    checkpoint = ctx.db.execute(query.order_by(StateCheckpoint.tick.desc()).limit(1)).scalar_one_or_none()
    if checkpoint is None:
        raise not_found("Контрольная точка")
    data = get_json(checkpoint.object_key)
    return {"tick": checkpoint.tick, "seq": checkpoint.seq, "state_hash": checkpoint.state_hash, "state": data["state"], "ledger": data["ledger"]}


@router.get("/runs/{run_id}/metrics")
def metrics(run_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    rows = ctx.db.execute(select(MetricSample).where(MetricSample.run_id == run.id).order_by(MetricSample.metric_id, MetricSample.tick)).scalars().all()
    series: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        series.setdefault(r.metric_id, []).append({"tick": r.tick, "value": r.value, "numerator": r.numerator, "denominator": r.denominator, "applicability": r.applicability, "unit": r.unit})
    return {"series": series, "final": (run.audit or {}).get("metrics")}


@router.get("/runs/{run_id}/ledger")
def ledger(run_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    rows = ctx.db.execute(select(RewardLedgerEntry).where(RewardLedgerEntry.run_id == run.id).order_by(RewardLedgerEntry.id)).scalars().all()
    return {"items": [{"entry_id": r.entry_id, "actor_id": r.actor_id, "amount": r.amount, "state": r.state, "reason": r.reason, "unit_ref": r.unit_ref, "dedup_key": r.dedup_key,
                       "source_event_seq": r.source_event_seq, "related_entry_id": r.related_entry_id, "tick": r.tick, "rule_version_id": r.rule_version_id} for r in rows]}


@router.get("/runs/{run_id}/model-calls")
def model_calls(run_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    run = _get_run(ctx, run_id)
    rows = ctx.db.execute(select(ModelCall).where(ModelCall.run_id == run.id).order_by(ModelCall.started_at)).scalars().all()
    return {"items": [{"id": str(c.id), "actor_id": c.actor_id, "tick": c.tick, "status": c.status, "provider": c.provider, "model": c.model, "usage": c.usage,
                       "usage_known": c.usage is not None, "error_kind": c.error_kind, "response_id": c.response_id} for c in rows]}


# --- findings --------------------------------------------------------------------------------

def _finding(f: Finding) -> dict[str, Any]:
    return {"id": str(f.id), "run_id": str(f.run_id), "project_id": str(f.project_id), "check_id": f.check_id, "status": f.status, "replay_status": f.replay_status,
            "replay_result": f.replay_result, "minimization": f.minimization, "fix_candidates": f.fix_candidates, "card": f.card, "evidence_range": f.evidence_range,
            "created_at": f.created_at.isoformat()}


def _get_finding(ctx, finding_id: uuid.UUID, need: str = "read") -> Finding:
    finding = ctx.db.get(Finding, finding_id)
    if finding is None:
        raise not_found("Нарушение")
    ctx.require_project(finding.project_id, need)
    return finding


def _run_events(db, run: Run) -> list[dict[str, Any]]:
    rows = db.execute(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)).scalars().all()
    return [{"seq": e.seq, "domain_seq": e.domain_seq, "event_class": e.event_class, "tick": e.tick, "type": e.type, "actor_id": e.actor_id, "entity_id": e.entity_id,
             "payload": e.payload, "state_hash": e.state_hash, "prev_hash": e.prev_hash, "event_hash": e.event_hash, "run_id": str(run.id), "schema_version": "1.0"} for e in rows]


@router.get("/findings/{finding_id}")
def get_finding(finding_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    finding = _get_finding(ctx, finding_id)
    run = ctx.db.get(Run, finding.run_id)
    return {**_finding(finding), "run": _run(run)}


@router.get("/projects/{project_id}/findings")
def list_findings(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id)
    rows = ctx.db.execute(select(Finding).where(Finding.project_id == project_id).order_by(Finding.created_at.desc()).limit(200)).scalars().all()
    return {"items": [_finding(f) for f in rows]}


@router.post("/findings/{finding_id}/replay")
def replay(finding_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    """Verified replay: recorded actions only, no model calls (AC-035, AC-056)."""
    finding = _get_finding(ctx, finding_id)
    run = ctx.db.get(Run, finding.run_id)
    result = verify_replay(recipe_for_run(ctx.db, run), _run_events(ctx.db, run), check_id=finding.check_id)
    finding.replay_status = result["status"]
    finding.replay_result = {**result, "checked_at": utcnow().isoformat()}
    ctx.db.commit()
    return _finding(finding)


@router.post("/findings/{finding_id}/minimize", status_code=202)
def minimize(finding_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    finding = _get_finding(ctx, finding_id, "run")
    finding.minimization = {"status": "queued"}
    enqueue(ctx.db, finding.workspace_id, "finding.minimize", finding.id)
    ctx.db.commit()
    return _finding(finding)


@router.post("/findings/{finding_id}/propose-fixes")
def fixes(finding_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    finding = _get_finding(ctx, finding_id, "edit")
    run = ctx.db.get(Run, finding.run_id)
    rule = ctx.db.get(RuleVersion, run.rule_version_id)
    env = get_environment(run.snapshot["environment"])
    finding.fix_candidates = propose_fixes(rule.ast_json, finding.card, env, run.snapshot["config"])
    ctx.db.commit()
    return _finding(finding)


class CreateVariant(BaseModel):
    candidate_key: str


@router.post("/findings/{finding_id}/create-variant", status_code=201)
def create_variant(finding_id: uuid.UUID, payload: CreateVariant, ctx: CtxDep) -> dict[str, Any]:
    finding = _get_finding(ctx, finding_id, "edit")
    candidate = next((c for c in finding.fix_candidates or [] if c["key"] == payload.candidate_key), None)
    if candidate is None:
        raise not_found("Кандидат исправления")
    run = ctx.db.get(Run, finding.run_id)
    base = ctx.db.get(RuleVersion, run.rule_version_id)
    from chobra_engine.rules import rule_hash

    draft = RuleVersion(workspace_id=base.workspace_id, project_id=base.project_id, version=next_version(ctx.db, RuleVersion, base.project_id),
                        name=f"{base.name}: {candidate['title']}", status="draft", ast_json=candidate["tree"], ast_hash=rule_hash(candidate["tree"]),
                        source_text=candidate["explanation"], description=f"Кандидат исправления для «{finding.card.get('title')}». Компромисс: {candidate['tradeoff']}",
                        parent_id=base.id, origin="finding_fix", created_by=ctx.user.id)
    ctx.db.add(draft)
    audit(ctx.db, base.workspace_id, ctx.user.id, "rule.create_from_finding", f"finding:{finding.id}", candidate=payload.candidate_key)
    ctx.db.commit()
    return {"id": str(draft.id), "status": draft.status, "name": draft.name}


class CheckFix(BaseModel):
    rule_version_id: uuid.UUID


@router.post("/findings/{finding_id}/check-fix")
def check_fix(finding_id: uuid.UUID, payload: CheckFix, ctx: CtxDep) -> dict[str, Any]:
    finding = _get_finding(ctx, finding_id)
    run = ctx.db.get(Run, finding.run_id)
    rule = ctx.db.get(RuleVersion, payload.rule_version_id)
    if rule is None or rule.project_id != run.project_id:
        raise not_found("Правило")
    env = get_environment(run.snapshot["environment"])
    if not validate_rule(rule.ast_json, env).ok:
        raise ApiError(422, "RULE_INVALID", "Правило не проходит проверку")
    result = check_fix_on_counterexample(recipe_for_run(ctx.db, run), _run_events(ctx.db, run), rule.ast_json, check_id=finding.check_id)
    return {"rule_version_id": str(rule.id), "reproduced": result["reproduced"], "checks": result["checks"],
            "note": "Проверка на действиях исходного контрпримера. Для отдельного набора условий запустите серию с новыми seed."}


# --- comparisons ---------------------------------------------------------------------------

def _comparison(c: Comparison) -> dict[str, Any]:
    return {"id": str(c.id), "batch_id": str(c.batch_id), "project_id": str(c.project_id), "result": c.result, "completeness": c.completeness, "excluded_runs": c.excluded_runs,
            "decision": c.decision, "settings_hash": c.settings_hash, "created_at": c.created_at.isoformat()}


def _get_comparison(ctx, comparison_id: uuid.UUID) -> Comparison:
    comparison = ctx.db.get(Comparison, comparison_id)
    if comparison is None:
        raise not_found("Сравнение")
    ctx.require_project(comparison.project_id)
    return comparison


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    comparison = _get_comparison(ctx, comparison_id)
    runs = ctx.db.execute(select(Run).where(Run.batch_id == comparison.batch_id)).scalars().all()
    return {**_comparison(comparison), "runs": [_run(r) for r in runs], "plan": ctx.db.get(ExperimentBatch, comparison.batch_id).immutable_plan}


class Exclusion(BaseModel):
    run_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


@router.post("/comparisons/{comparison_id}/exclusions")
def exclude(comparison_id: uuid.UUID, payload: Exclusion, ctx: CtxDep) -> dict[str, Any]:
    comparison = _get_comparison(ctx, comparison_id)
    ctx.require_project(comparison.project_id, "edit")
    comparison.excluded_runs = [*comparison.excluded_runs, {"run_id": str(payload.run_id), "reason": payload.reason, "by": str(ctx.user.id), "at": utcnow().isoformat()}]
    enqueue(ctx.db, comparison.workspace_id, "batch.finalize", comparison.batch_id, {"comparison_id": str(comparison.id)})
    ctx.db.commit()
    return _comparison(comparison)


class Decision(BaseModel):
    accepted_variant: str
    note: str = ""


@router.post("/comparisons/{comparison_id}/decision")
def decide(comparison_id: uuid.UUID, payload: Decision, ctx: CtxDep) -> dict[str, Any]:
    """Records a decision. Accepting a variant never changes real systems (FLOW-007)."""
    comparison = _get_comparison(ctx, comparison_id)
    ctx.require_project(comparison.project_id, "edit")
    comparison.decision = {"accepted_variant": payload.accepted_variant, "note": payload.note, "by": str(ctx.user.id), "at": utcnow().isoformat()}
    audit(ctx.db, comparison.workspace_id, ctx.user.id, "comparison.decision", f"comparison:{comparison.id}", accepted=payload.accepted_variant)
    ctx.db.commit()
    return _comparison(comparison)


# --- reports -------------------------------------------------------------------------------

class ReportBody(BaseModel):
    project_id: uuid.UUID
    batch_id: uuid.UUID
    format: str = Field(pattern="^(json|csv|markdown|pdf)$")
    include_raw_model_io: bool = False


def _report(r: Report, with_link: bool = False) -> dict[str, Any]:
    data = {"id": str(r.id), "project_id": str(r.project_id), "batch_id": str(r.batch_id) if r.batch_id else None, "format": r.format, "status": r.status, "error": r.error,
            "created_at": r.created_at.isoformat(), "snapshot_summary": (r.snapshot or {}).get("summary")}
    if with_link and r.status == "ready" and r.object_key:
        data["download_url"] = f"/api/v1/reports/{r.id}/download?sig={sign_link(r.object_key)}"
        data["link_expires_in_seconds"] = 300
    return data


@router.post("/reports", status_code=202)
def create_report(payload: ReportBody, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "export")
    batch = ctx.db.get(ExperimentBatch, payload.batch_id)
    if batch is None or batch.project_id != project.id:
        raise not_found("Серия")
    report = Report(workspace_id=project.workspace_id, project_id=project.id, batch_id=batch.id, format=payload.format, include_raw_model_io=payload.include_raw_model_io, created_by=ctx.user.id)
    ctx.db.add(report)
    ctx.db.flush()
    enqueue(ctx.db, project.workspace_id, "report.generate", report.id)
    audit(ctx.db, project.workspace_id, ctx.user.id, "report.create", f"report:{report.id}", format=payload.format)
    ctx.db.commit()
    return _report(report)


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    report = ctx.db.get(Report, report_id)
    if report is None:
        raise not_found("Отчет")
    ctx.require_project(report.project_id, "export")
    return {**_report(report, with_link=True), "snapshot": report.snapshot}


@router.get("/projects/{project_id}/reports")
def list_reports(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id)
    rows = ctx.db.execute(select(Report).where(Report.project_id == project_id).order_by(Report.created_at.desc()).limit(100)).scalars().all()
    return {"items": [_report(r) for r in rows]}


MEDIA = {"json": ("application/json", "json"), "csv": ("application/zip", "zip"), "markdown": ("text/markdown; charset=utf-8", "md"), "pdf": ("application/pdf", "pdf")}


@router.get("/reports/{report_id}/download")
def download(report_id: uuid.UUID, sig: str, ctx: CtxDep) -> FileResponse:
    """Access is checked again at download time; the signed link lives five minutes (AC-068)."""
    report = ctx.db.get(Report, report_id)
    if report is None or report.status != "ready" or not report.object_key:
        raise not_found("Отчет")
    ctx.require_project(report.project_id, "export")
    if not verify_link(report.object_key, sig):
        raise ApiError(410, "LINK_EXPIRED", "Ссылка истекла; запросите новую")
    media, ext = MEDIA[report.format]
    audit(ctx.db, report.workspace_id, ctx.user.id, "report.download", f"report:{report.id}")
    ctx.db.commit()
    return FileResponse(file_path(report.object_key), media_type=media, filename=f"chobra-report-{str(report.id)[:8]}.{ext}")
