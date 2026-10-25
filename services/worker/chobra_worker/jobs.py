"""Job queue on PostgreSQL: claim with SKIP LOCKED, leases with a generation token, fair per workspace."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chobra_api.db import set_tenant
from chobra_api.models import Job, Run
from chobra_api.services import utcnow

LEASE_SECONDS = 60
ACTIVE_RUN_STATES = ("initializing", "running", "pause_requested", "auditing", "resume_requested")


@dataclass(frozen=True)
class Lease:
    job_id: uuid.UUID
    kind: str
    target_id: uuid.UUID
    workspace_id: uuid.UUID
    generation: int
    owner: str
    args: dict


def _active_runs(db: Session, workspace_id: uuid.UUID) -> int:
    set_tenant(db, None, [workspace_id])
    return db.execute(select(func.count()).select_from(Run).where(Run.workspace_id == workspace_id, Run.status.in_(ACTIVE_RUN_STATES))).scalar() or 0


def claim(db: Session, owner: str, workspace_limits: dict[uuid.UUID, int] | None = None, default_limit: int = 4) -> Lease | None:
    moment = utcnow()
    candidates = db.execute(
        select(Job)
        .where(((Job.status == "ready") & (Job.available_at <= moment)) | ((Job.status == "leased") & (Job.lease_expires_at < moment)))
        .order_by(Job.priority.desc(), Job.available_at, Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(50)
    ).scalars().all()
    # Fair share: prefer the workspace with fewer active runs so one big series does not block others.
    load: dict[uuid.UUID, int] = {}
    for job in candidates:
        if job.workspace_id not in load:
            load[job.workspace_id] = _active_runs(db, job.workspace_id)
    ordered = sorted(candidates, key=lambda j: (load[j.workspace_id] if j.kind == "run.execute" else 0, -j.priority, j.available_at))
    for job in ordered:
        limit = (workspace_limits or {}).get(job.workspace_id, default_limit)
        if job.kind == "run.execute" and load[job.workspace_id] >= limit:
            continue
        job.status = "leased"
        job.lease_owner = owner
        job.lease_generation += 1
        job.lease_expires_at = moment + timedelta(seconds=LEASE_SECONDS)
        job.attempts += 1
        lease = Lease(job.id, job.kind, job.target_id, job.workspace_id, job.lease_generation, owner, dict(job.args or {}))
        db.commit()
        return lease
    db.commit()
    return None


def extend(db: Session, lease: Lease) -> bool:
    job = db.get(Job, lease.job_id, with_for_update=True)
    if job is None or job.lease_generation != lease.generation or job.lease_owner != lease.owner:
        db.rollback()
        return False
    job.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    return True


def finish(db: Session, lease: Lease, *, error: str | None = None, retry_in: int | None = None) -> None:
    job = db.get(Job, lease.job_id, with_for_update=True)
    if job is None or job.lease_generation != lease.generation:
        db.rollback()
        return
    if retry_in is not None and job.attempts < 5:
        job.status = "ready"
        job.available_at = utcnow() + timedelta(seconds=retry_in)
    else:
        job.status = "failed" if error else "done"
    job.last_error = error
    job.lease_owner = None
    job.lease_expires_at = None
    db.commit()
