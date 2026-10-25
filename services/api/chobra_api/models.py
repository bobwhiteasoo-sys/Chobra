"""Storage model (spec section 17). Every user entity carries `workspace_id` for row level security."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)


def _ws() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("oidc_issuer", "oidc_subject"),)
    id: Mapped[uuid.UUID] = _id()
    oidc_issuer: Mapped[str] = mapped_column(String(300))
    oidc_subject: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), default="ru")
    created_at: Mapped[datetime] = _created()


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = _id()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_workspace_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = _created()


class ProviderKey(Base):
    __tablename__ = "provider_keys"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    provider: Mapped[str] = mapped_column(String(40))
    ciphertext: Mapped[str] = mapped_column(Text)
    last4: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = _created()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    environment_id: Mapped[str] = mapped_column(String(40))
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    research_question: Mapped[str] = mapped_column(Text, default="")
    desired_outcome: Mapped[str] = mapped_column(Text, default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectPermission(Base):
    __tablename__ = "project_permissions"
    __table_args__ = (UniqueConstraint("project_id", "principal_id"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    permission: Mapped[str] = mapped_column(String(20))


class EnvironmentVersion(Base):
    __tablename__ = "environment_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    schemas_hash: Mapped[str] = mapped_column(String(64))
    engine_image_digest: Mapped[str] = mapped_column(String(100))


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actor_count: Mapped[int] = mapped_column(Integer, default=3)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    template_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    ast_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ast_hash: Mapped[str] = mapped_column(String(64))
    source_text: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(40), default="manual")
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AgentProfile(Base):
    __tablename__ = "agent_profiles"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(20), default="scripted")
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    observation_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    memory_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()


class ExperimentBatch(Base):
    __tablename__ = "experiment_batches"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    immutable_plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    planned_runs: Mapped[int] = mapped_column(Integer)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    budget_used: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_ws_status", "workspace_id", "status"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("experiment_batches.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[str] = mapped_column(String(100))
    variant_label: Mapped[str] = mapped_column(String(200), default="")
    rule_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rule_versions.id"))
    scenario_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("scenario_versions.id"))
    seed: Mapped[int] = mapped_column(BigInteger)
    agent_mode: Mapped[str] = mapped_column(String(30))
    agent_kind: Mapped[str] = mapped_column(String(20), default="scripted")
    kind: Mapped[str] = mapped_column(String(30), default="experiment")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    stop_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    current_tick: Mapped[int] = mapped_column(Integer, default=-1)
    horizon_ticks: Mapped[int] = mapped_column(Integer)
    tail_ticks: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    tape_hash: Mapped[str] = mapped_column(String(64), default="")
    audit: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    chain_root: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"), Index("ix_run_events_run_tick", "run_id", "tick"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(BigInteger)
    domain_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_class: Mapped[str] = mapped_column(String(20))
    tick: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(80))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64))
    state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = _created()


class StateCheckpoint(Base):
    __tablename__ = "state_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "tick"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    tick: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(BigInteger)
    state_hash: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(300))
    size_bytes: Mapped[int] = mapped_column(Integer)


class ModelCall(Base):
    __tablename__ = "model_calls"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    tick: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RewardLedgerEntry(Base):
    __tablename__ = "reward_ledger"
    __table_args__ = (UniqueConstraint("run_id", "entry_id"), UniqueConstraint("run_id", "rule_version_id", "source_event_key"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(String(120))
    rule_version_id: Mapped[str] = mapped_column(String(120))
    source_event_key: Mapped[str] = mapped_column(String(200))
    source_event_seq: Mapped[int] = mapped_column(BigInteger)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    related_entry_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tick: Mapped[int] = mapped_column(Integer)


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (UniqueConstraint("run_id", "tick", "metric_id"), Index("ix_metric_samples_run_metric_tick", "run_id", "metric_id", "tick"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"))
    tick: Mapped[int] = mapped_column(Integer)
    metric_id: Mapped[str] = mapped_column(String(80))
    value: Mapped[str | None] = mapped_column(String(60), nullable=True)
    numerator: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    denominator: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    applicability: Mapped[str] = mapped_column(String(20))
    unit: Mapped[str] = mapped_column(String(40))


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("run_id", "check_id"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    check_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="observed")
    evidence_range: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    replay_status: Mapped[str] = mapped_column(String(30), default="not_checked")
    replay_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    minimization: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fix_candidates: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("experiment_batches.id", ondelete="CASCADE"), index=True)
    settings_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    completeness: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    excluded_runs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comparisons.id", ondelete="SET NULL"), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    format: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    object_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    include_raw_model_io: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("experiment_batches.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"))
    model_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reserved: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actual: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="reserved")


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = _ws()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    operation: Mapped[str] = mapped_column(String(80))
    object_ref: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str] = mapped_column(String(120))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ImportJob(Base):
    __tablename__ = "imports"
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="parsed")
    filename: Mapped[str] = mapped_column(String(300))
    object_key: Mapped[str] = mapped_column(String(300))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", "operation", "key"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = _ws()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    operation: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class Job(Base):
    """Queue entries. Holds only identifiers; the worker sets the tenant context from `workspace_id`."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_ready", "status", "available_at"),)
    id: Mapped[uuid.UUID] = _id()
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


RLS_TABLES = [
    "workspaces", "memberships", "provider_keys", "projects", "project_permissions", "scenario_versions", "rule_versions",
    "agent_profiles", "experiment_batches", "runs", "run_events", "state_checkpoints", "model_calls", "reward_ledger",
    "metric_samples", "findings", "comparisons", "reports", "budget_reservations", "outbox", "audit_log", "comments",
    "imports", "idempotency_keys",
]


class TelegramLogin(Base):
    """Short-lived challenge: Telegram approves; only the originating browser consumes."""
    __tablename__ = "telegram_logins"
    id: Mapped[uuid.UUID] = _id()
    start_hash: Mapped[str] = mapped_column(String(64), unique=True)
    browser_hash: Mapped[str] = mapped_column(String(64), index=True)
    display_code: Mapped[str] = mapped_column(String(8))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BotCursor(Base):
    __tablename__ = "bot_cursors"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, default=0)
