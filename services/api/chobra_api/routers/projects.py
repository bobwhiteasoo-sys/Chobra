"""Projects, scenarios, rules, agent profiles, comments and imports."""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, Header, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, func, or_, select

from chobra_engine.canonical import sha256_hex
from chobra_engine.rules import compute_examples, rule_hash, validate_rule
from chobra_envs.registry import ENVIRONMENTS, get_environment

from ..deps import CtxDep
from ..errors import ApiError, conflict, forbidden, not_found
from ..models import AgentProfile, Comment, Comparison, ExperimentBatch, Finding, ImportJob, Project, ProjectPermission, RuleVersion, ScenarioVersion
from ..objects import put_bytes
from ..rule_tools import compile_text, rule_diff
from ..services import audit, check_revision, create_project, next_version, utcnow

router = APIRouter()


def _project(p: Project, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(p.id), "workspace_id": str(p.workspace_id), "name": p.name, "description": p.description, "environment_id": p.environment_id,
        "tags": p.tags, "owner_id": str(p.owner_id), "restricted": p.restricted, "is_demo": p.is_demo, "research_question": p.research_question,
        "desired_outcome": p.desired_outcome, "archived_at": p.archived_at.isoformat() if p.archived_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None, "updated_at": p.updated_at.isoformat() if p.updated_at else None, **(extra or {}),
    }


@router.get("/projects")
def list_projects(ctx: CtxDep, workspace_id: uuid.UUID, q: str = "", environment: str = "", archived: bool = False, owner: str = "", cursor: str = "", limit: int = 50) -> dict[str, Any]:
    ctx.require_workspace(workspace_id)
    limit = min(max(limit, 1), 100)
    query = select(Project).where(Project.workspace_id == workspace_id)
    query = query.where(Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Project.name).like(like), cast(Project.tags, Text).ilike(like)))
    if environment:
        query = query.where(Project.environment_id == environment)
    if owner == "me":
        query = query.where(Project.owner_id == ctx.user.id)
    if cursor:
        query = query.where(Project.created_at < datetime.fromisoformat(cursor))
    rows = ctx.db.execute(query.order_by(Project.created_at.desc(), Project.id).limit(limit + 1)).scalars().all()
    visible = []
    for project in rows[:limit]:
        try:
            ctx.require_project(project.id)
        except ApiError:
            continue
        last = ctx.db.execute(select(ExperimentBatch).where(ExperimentBatch.project_id == project.id).order_by(ExperimentBatch.created_at.desc()).limit(1)).scalar_one_or_none()
        visible.append(_project(project, {"last_batch": {"id": str(last.id), "status": last.status, "created_at": last.created_at.isoformat()} if last else None}))
    next_cursor = rows[limit - 1].created_at.isoformat() if len(rows) > limit else None
    return {"items": visible, "next_cursor": next_cursor}


class ProjectCreate(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    environment_id: str
    description: str = ""
    tags: list[str] = []
    is_demo: bool = False


@router.post("/projects", status_code=201)
def create(payload: ProjectCreate, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(payload.workspace_id, "edit")
    project = create_project(ctx.db, workspace_id=payload.workspace_id, user_id=ctx.user.id, name=payload.name.strip(), environment=payload.environment_id,
                             description=payload.description, tags=payload.tags, is_demo=payload.is_demo)
    ctx.db.commit()
    return _project(project)


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id)
    db = ctx.db
    scenarios = db.execute(select(ScenarioVersion).where(ScenarioVersion.project_id == project_id).order_by(ScenarioVersion.version.desc()).limit(5)).scalars().all()
    rules = db.execute(select(RuleVersion).where(RuleVersion.project_id == project_id).order_by(RuleVersion.version.desc())).scalars().all()
    batches = db.execute(select(ExperimentBatch).where(ExperimentBatch.project_id == project_id).order_by(ExperimentBatch.created_at.desc()).limit(10)).scalars().all()
    comparison = db.execute(select(Comparison).where(Comparison.project_id == project_id).order_by(Comparison.created_at.desc()).limit(1)).scalar_one_or_none()
    findings = db.execute(select(Finding).where(Finding.project_id == project_id).order_by(Finding.created_at.desc()).limit(20)).scalars().all()
    role = ctx.roles[project.workspace_id]
    return _project(project, {
        "role": role,
        "scenarios": [_scenario(s) for s in scenarios],
        "rules": [_rule(r, brief=True) for r in rules],
        "batches": [_batch_brief(b) for b in batches],
        "last_comparison": {"id": str(comparison.id), "batch_id": str(comparison.batch_id), "created_at": comparison.created_at.isoformat(), "summary": comparison.result.get("summary", [])[:4],
                            "tradeoffs": comparison.result.get("tradeoffs", [])} if comparison else None,
        "findings": [_finding_brief(f) for f in findings],
    })


def _batch_brief(b: ExperimentBatch) -> dict[str, Any]:
    return {"id": str(b.id), "title": b.title, "status": b.status, "planned_runs": b.planned_runs, "created_at": b.created_at.isoformat(), "modes": b.immutable_plan.get("modes", [])}


def _finding_brief(f: Finding) -> dict[str, Any]:
    return {"id": str(f.id), "run_id": str(f.run_id), "check_id": f.check_id, "title": f.card.get("title"), "explanation": f.card.get("explanation"),
            "replay_status": f.replay_status, "status": f.status, "created_at": f.created_at.isoformat()}


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    tags: list[str] | None = None
    research_question: str | None = None
    desired_outcome: str | None = None
    restricted: bool | None = None


@router.patch("/projects/{project_id}")
def patch_project(project_id: uuid.UUID, payload: ProjectPatch, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id, "edit")
    data = payload.model_dump(exclude_unset=True)
    if "restricted" in data:
        ctx.require_workspace(project.workspace_id, "manage")
    for key, value in data.items():
        setattr(project, key, value)
    audit(ctx.db, project.workspace_id, ctx.user.id, "project.update", f"project:{project.id}", fields=sorted(data))
    ctx.db.commit()
    return _project(project)


@router.post("/projects/{project_id}/archive")
def archive(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id, "edit")
    project.archived_at = utcnow()
    audit(ctx.db, project.workspace_id, ctx.user.id, "project.archive", f"project:{project.id}")
    ctx.db.commit()
    return _project(project)


@router.post("/projects/{project_id}/restore")
def restore(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id, "edit")
    project.archived_at = None
    audit(ctx.db, project.workspace_id, ctx.user.id, "project.restore", f"project:{project.id}")
    ctx.db.commit()
    return _project(project)


class PermissionItem(BaseModel):
    user_id: uuid.UUID
    permission: str = Field(pattern="^(reader|editor|export)$")


class PermissionSet(BaseModel):
    items: list[PermissionItem]


@router.get("/projects/{project_id}/permissions")
def get_permissions(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id)
    rows = ctx.db.execute(select(ProjectPermission).where(ProjectPermission.project_id == project.id)).scalars().all()
    return {"restricted": project.restricted, "items": [{"user_id": str(r.principal_id), "permission": r.permission} for r in rows]}


@router.put("/projects/{project_id}/permissions")
def set_permissions(project_id: uuid.UUID, payload: PermissionSet, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id)
    ctx.require_workspace(project.workspace_id, "manage")
    for row in ctx.db.execute(select(ProjectPermission).where(ProjectPermission.project_id == project.id)).scalars():
        ctx.db.delete(row)
    ctx.db.flush()
    for item in payload.items:
        ctx.db.add(ProjectPermission(workspace_id=project.workspace_id, project_id=project.id, principal_id=item.user_id, permission=item.permission))
    audit(ctx.db, project.workspace_id, ctx.user.id, "project.permissions", f"project:{project.id}", count=len(payload.items))
    ctx.db.commit()
    return {"ok": True}


# --- scenarios ---------------------------------------------------------------------------

def _scenario(s: ScenarioVersion) -> dict[str, Any]:
    return {"id": str(s.id), "project_id": str(s.project_id), "version": s.version, "status": s.status, "revision": s.revision, "config": s.config_json,
            "actor_count": s.actor_count, "snapshot_hash": s.snapshot_hash, "parent_id": str(s.parent_id) if s.parent_id else None,
            "published_at": s.published_at.isoformat() if s.published_at else None, "updated_at": s.updated_at.isoformat() if s.updated_at else None}


class ScenarioValidate(BaseModel):
    environment: str
    config: dict[str, Any]
    actor_count: int = 3


def _validate_scenario(environment: str, config: dict[str, Any], actor_count: int) -> list[dict[str, str]]:
    if environment not in ENVIRONMENTS:
        raise ApiError(422, "UNKNOWN_ENVIRONMENT", "Неизвестная среда")
    issues = [{"path": i.path, "message": i.message} for i in get_environment(environment).validate_config(config)]
    if not 1 <= actor_count <= 20:
        issues.append({"path": "actor_count", "message": "От 1 до 20 участников"})
    return issues


@router.post("/scenarios/validate")
def validate_scenario(payload: ScenarioValidate, ctx: CtxDep) -> dict[str, Any]:
    issues = _validate_scenario(payload.environment, payload.config, payload.actor_count)
    return {"ok": not issues, "issues": issues}


class ScenarioCreate(BaseModel):
    project_id: uuid.UUID
    from_version_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    actor_count: int | None = None


@router.post("/scenarios", status_code=201)
def create_scenario(payload: ScenarioCreate, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "edit")
    base = ctx.db.get(ScenarioVersion, payload.from_version_id) if payload.from_version_id else None
    if base is not None and base.project_id != project.id:
        raise not_found("Сценарий")
    config = payload.config or (base.config_json if base else get_environment(project.environment_id).default_config())
    draft = ScenarioVersion(workspace_id=project.workspace_id, project_id=project.id, version=next_version(ctx.db, ScenarioVersion, project.id), status="draft",
                            config_json=config, actor_count=payload.actor_count or (base.actor_count if base else 3), parent_id=base.id if base else None, created_by=ctx.user.id)
    ctx.db.add(draft)
    ctx.db.commit()
    return _scenario(draft)


@router.get("/projects/{project_id}/scenarios")
def list_scenarios(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id)
    rows = ctx.db.execute(select(ScenarioVersion).where(ScenarioVersion.project_id == project_id).order_by(ScenarioVersion.version.desc())).scalars().all()
    return {"items": [_scenario(s) for s in rows]}


def _get_scenario(ctx, scenario_id: uuid.UUID, need: str = "read") -> ScenarioVersion:
    scenario = ctx.db.get(ScenarioVersion, scenario_id)
    if scenario is None:
        raise not_found("Сценарий")
    ctx.require_project(scenario.project_id, need)
    return scenario


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    return _scenario(_get_scenario(ctx, scenario_id))


class ScenarioPatch(BaseModel):
    config: dict[str, Any] | None = None
    actor_count: int | None = None


@router.patch("/scenarios/{scenario_id}")
def patch_scenario(scenario_id: uuid.UUID, payload: ScenarioPatch, ctx: CtxDep, if_match: str | None = Header(default=None)) -> dict[str, Any]:
    scenario = _get_scenario(ctx, scenario_id, "edit")
    if scenario.status != "draft":
        raise conflict("IMMUTABLE_VERSION", "Опубликованная версия неизменяема; создайте новую версию")
    check_revision(scenario.revision, if_match)
    if payload.config is not None:
        scenario.config_json = payload.config
    if payload.actor_count is not None:
        scenario.actor_count = payload.actor_count
    scenario.revision += 1
    ctx.db.commit()
    return _scenario(scenario)


@router.post("/scenarios/{scenario_id}/publish")
def publish_scenario(scenario_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    scenario = _get_scenario(ctx, scenario_id, "edit")
    if scenario.status != "draft":
        raise conflict("IMMUTABLE_VERSION", "Версия уже опубликована")
    project = ctx.db.get(Project, scenario.project_id)
    issues = _validate_scenario(project.environment_id, scenario.config_json, scenario.actor_count)
    if issues:
        raise ApiError(422, "SCENARIO_INVALID", "Сценарий не прошел проверку", {"issues": issues})
    env = get_environment(project.environment_id)
    scenario.status = "published"
    scenario.published_at = utcnow()
    scenario.snapshot_hash = sha256_hex({"environment": project.environment_id, "version": env.version, "config": scenario.config_json, "actors": scenario.actor_count})
    audit(ctx.db, project.workspace_id, ctx.user.id, "scenario.publish", f"scenario:{scenario.id}", version=scenario.version)
    ctx.db.commit()
    return _scenario(scenario)


# --- rules -------------------------------------------------------------------------------

def _rule(r: RuleVersion, brief: bool = False) -> dict[str, Any]:
    data = {"id": str(r.id), "project_id": str(r.project_id), "version": r.version, "name": r.name, "template_key": r.template_key, "status": r.status,
            "revision": r.revision, "ast_hash": r.ast_hash, "parent_id": str(r.parent_id) if r.parent_id else None, "origin": r.origin,
            "description": r.description, "source_text": r.source_text, "published_at": r.published_at.isoformat() if r.published_at else None}
    if not brief:
        data["tree"] = r.ast_json
    return data


def _env_for_rule(tree: dict[str, Any], project: Project):
    return get_environment(project.environment_id)


class RuleCompile(BaseModel):
    project_id: uuid.UUID
    text: str = Field(min_length=3, max_length=2000)


@router.post("/rules/compile")
def compile_rule(payload: RuleCompile, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "edit")
    result = compile_text(project.environment_id, payload.text)
    if result["candidate"] is not None:
        env = get_environment(project.environment_id)
        result["validation"] = validate_rule(result["candidate"], env).to_dict()
    return result


class RuleValidate(BaseModel):
    project_id: uuid.UUID
    tree: dict[str, Any]
    compare_to: uuid.UUID | None = None


@router.post("/rules/validate")
def validate(payload: RuleValidate, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id)
    env = get_environment(project.environment_id)
    validation = validate_rule(payload.tree, env)
    examples = compute_examples(payload.tree, env) if validation.ok else []
    diff = None
    if payload.compare_to:
        base = ctx.db.get(RuleVersion, payload.compare_to)
        if base is None or base.project_id != project.id:
            raise not_found("Правило")
        diff = rule_diff(base.ast_json, payload.tree)
    return {"validation": validation.to_dict(), "examples": examples, "diff": diff}


class RuleCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    tree: dict[str, Any]
    source_text: str = ""
    description: str = ""
    parent_id: uuid.UUID | None = None
    origin: str = "manual"


@router.post("/rules", status_code=201)
def create_rule(payload: RuleCreate, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(payload.project_id, "edit")
    if payload.parent_id:
        parent = ctx.db.get(RuleVersion, payload.parent_id)
        if parent is None or parent.project_id != project.id:
            raise not_found("Исходное правило")
    rule = RuleVersion(workspace_id=project.workspace_id, project_id=project.id, version=next_version(ctx.db, RuleVersion, project.id), name=payload.name, status="draft",
                       ast_json=payload.tree, ast_hash=rule_hash(payload.tree) if _hashable(payload.tree) else "", source_text=payload.source_text,
                       description=payload.description, parent_id=payload.parent_id, origin=payload.origin if payload.origin in ("manual", "text", "finding_fix", "template") else "manual",
                       created_by=ctx.user.id)
    ctx.db.add(rule)
    ctx.db.commit()
    return _rule(rule)


def _hashable(tree: Any) -> bool:
    try:
        rule_hash(tree)
        return True
    except TypeError:
        return False


@router.get("/projects/{project_id}/rules")
def list_rules(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id)
    rows = ctx.db.execute(select(RuleVersion).where(RuleVersion.project_id == project_id).order_by(RuleVersion.version.desc())).scalars().all()
    return {"items": [_rule(r) for r in rows]}


def _get_rule(ctx, rule_id: uuid.UUID, need: str = "read") -> RuleVersion:
    rule = ctx.db.get(RuleVersion, rule_id)
    if rule is None:
        raise not_found("Правило")
    ctx.require_project(rule.project_id, need)
    return rule


@router.get("/rules/{rule_id}")
def get_rule(rule_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    rule = _get_rule(ctx, rule_id)
    project = ctx.db.get(Project, rule.project_id)
    env = get_environment(project.environment_id)
    validation = validate_rule(rule.ast_json, env)
    parent = ctx.db.get(RuleVersion, rule.parent_id) if rule.parent_id else None
    return {**_rule(rule), "validation": validation.to_dict(), "examples": compute_examples(rule.ast_json, env) if validation.ok else [],
            "diff_from_parent": rule_diff(parent.ast_json, rule.ast_json) if parent else None}


class RulePatch(BaseModel):
    name: str | None = None
    tree: dict[str, Any] | None = None
    source_text: str | None = None
    description: str | None = None


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: uuid.UUID, payload: RulePatch, ctx: CtxDep, if_match: str | None = Header(default=None)) -> dict[str, Any]:
    rule = _get_rule(ctx, rule_id, "edit")
    if rule.status != "draft":
        raise conflict("IMMUTABLE_VERSION", "Опубликованная версия неизменяема; создайте новую версию со ссылкой на исходную")
    check_revision(rule.revision, if_match)
    data = payload.model_dump(exclude_unset=True)
    if "tree" in data:
        rule.ast_json = data.pop("tree")
        rule.ast_hash = rule_hash(rule.ast_json) if _hashable(rule.ast_json) else ""
    for key, value in data.items():
        setattr(rule, key, value)
    rule.revision += 1
    ctx.db.commit()
    return _rule(rule)


@router.post("/rules/{rule_id}/publish")
def publish_rule(rule_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    rule = _get_rule(ctx, rule_id, "edit")
    if rule.status != "draft":
        raise conflict("IMMUTABLE_VERSION", "Версия уже опубликована")
    project = ctx.db.get(Project, rule.project_id)
    validation = validate_rule(rule.ast_json, get_environment(project.environment_id))
    if not validation.ok:
        first = validation.errors[0]
        raise ApiError(422, first.code, first.message, {"path": first.path, **first.details, "errors": [e.to_dict() for e in validation.errors]})
    rule.status = "published"
    rule.published_at = utcnow()
    rule.ast_hash = rule_hash(rule.ast_json)
    audit(ctx.db, project.workspace_id, ctx.user.id, "rule.publish", f"rule:{rule.id}", version=rule.version, hash=rule.ast_hash)
    ctx.db.commit()
    return _rule(rule)


@router.post("/rules/{rule_id}/new-version", status_code=201)
def new_rule_version(rule_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    rule = _get_rule(ctx, rule_id, "edit")
    draft = RuleVersion(workspace_id=rule.workspace_id, project_id=rule.project_id, version=next_version(ctx.db, RuleVersion, rule.project_id), name=f"{rule.name} (изменение)",
                        status="draft", ast_json=rule.ast_json, ast_hash=rule.ast_hash, source_text=rule.source_text, description=rule.description, parent_id=rule.id,
                        origin="manual", created_by=ctx.user.id)
    ctx.db.add(draft)
    ctx.db.commit()
    return _rule(draft)


@router.get("/rules/{rule_id}/diff")
def diff_rules(rule_id: uuid.UUID, against: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    rule = _get_rule(ctx, rule_id)
    other = _get_rule(ctx, against)
    if other.project_id != rule.project_id:
        raise not_found("Правило")
    return {"rows": rule_diff(other.ast_json, rule.ast_json)}


# --- agent profiles ---------------------------------------------------------------------

def _profile(p: AgentProfile) -> dict[str, Any]:
    return {"id": str(p.id), "name": p.name, "mode": p.mode, "kind": p.kind, "model": p.model_config_json, "params": p.params, "observation_policy": p.observation_policy,
            "memory_config": p.memory_config, "version": p.version}


@router.get("/projects/{project_id}/agents")
def list_profiles(project_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id)
    rows = ctx.db.execute(select(AgentProfile).where(AgentProfile.project_id == project.id).order_by(AgentProfile.created_at)).scalars().all()
    scenario = ctx.db.execute(select(ScenarioVersion).where(ScenarioVersion.project_id == project.id, ScenarioVersion.status == "published").order_by(ScenarioVersion.version.desc()).limit(1)).scalar_one_or_none()
    count = scenario.actor_count if scenario else 3
    return {"items": [_profile(p) for p in rows], "participants": [{"actor_id": f"agent_{i + 1:02d}", "display_name": f"Участник {i + 1}"} for i in range(count)]}


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mode: str = Field(pattern="^(cooperative|incentive_seeking|adversarial_search)$")
    kind: str = Field(pattern="^(scripted|model)$")
    params: dict[str, Any] = {}
    model: dict[str, Any] = {}


@router.post("/projects/{project_id}/agents", status_code=201)
def create_profile(project_id: uuid.UUID, payload: ProfileBody, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id, "edit")
    profile = AgentProfile(workspace_id=project.workspace_id, project_id=project.id, name=payload.name, mode=payload.mode, kind=payload.kind, params=payload.params,
                           model_config_json=payload.model if payload.kind == "model" else {}, observation_policy={"history_access": payload.params.get("history_access", True)})
    ctx.db.add(profile)
    ctx.db.commit()
    return _profile(profile)


class ProfilePatch(BaseModel):
    name: str | None = None
    params: dict[str, Any] | None = None
    model: dict[str, Any] | None = None


@router.patch("/agents/{profile_id}")
def patch_profile(profile_id: uuid.UUID, payload: ProfilePatch, ctx: CtxDep) -> dict[str, Any]:
    profile = ctx.db.get(AgentProfile, profile_id)
    if profile is None or profile.project_id is None:
        raise not_found("Профиль")
    ctx.require_project(profile.project_id, "edit")
    if payload.name is not None:
        profile.name = payload.name
    if payload.params is not None:
        profile.params = {**profile.params, **payload.params}
    if payload.model is not None and profile.kind == "model":
        profile.model_config_json = {**profile.model_config_json, **payload.model}
    profile.version += 1
    ctx.db.commit()
    return _profile(profile)


class BulkPatch(BaseModel):
    profile_ids: list[uuid.UUID]
    params: dict[str, Any]
    preview: bool = True


@router.post("/projects/{project_id}/agents/bulk")
def bulk_profiles(project_id: uuid.UUID, payload: BulkPatch, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_project(project_id, "edit")
    changes = []
    for profile_id in payload.profile_ids:
        profile = ctx.db.get(AgentProfile, profile_id)
        if profile is None or profile.project_id != project_id:
            raise not_found("Профиль")
        diff = {k: {"before": profile.params.get(k), "after": v} for k, v in payload.params.items() if profile.params.get(k) != v}
        changes.append({"id": str(profile.id), "name": profile.name, "changes": diff})
        if not payload.preview and diff:
            profile.params = {**profile.params, **payload.params}
            profile.version += 1
    if not payload.preview:
        ctx.db.commit()
    return {"preview": payload.preview, "changes": changes}


# --- comments ---------------------------------------------------------------------------

class CommentBody(BaseModel):
    target_type: str = Field(pattern="^(event|rule|finding|comparison|run)$")
    target_id: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


@router.get("/projects/{project_id}/comments")
def list_comments(project_id: uuid.UUID, ctx: CtxDep, target_type: str = "", target_id: str = "") -> dict[str, Any]:
    ctx.require_project(project_id)
    query = select(Comment).where(Comment.project_id == project_id)
    if target_type:
        query = query.where(Comment.target_type == target_type)
    if target_id:
        query = query.where(Comment.target_id == target_id)
    rows = ctx.db.execute(query.order_by(Comment.created_at)).scalars().all()
    return {"items": [{"id": str(c.id), "target_type": c.target_type, "target_id": c.target_id, "author_id": str(c.author_id), "body": c.body, "created_at": c.created_at.isoformat()} for c in rows]}


@router.post("/projects/{project_id}/comments", status_code=201)
def add_comment(project_id: uuid.UUID, payload: CommentBody, ctx: CtxDep) -> dict[str, Any]:
    project = ctx.require_project(project_id)
    if ctx.roles[project.workspace_id] == "viewer":
        raise forbidden("Комментарии оставляют участники с правом редактирования")
    comment = Comment(workspace_id=project.workspace_id, project_id=project.id, target_type=payload.target_type, target_id=payload.target_id, author_id=ctx.user.id, body=payload.body)
    ctx.db.add(comment)
    ctx.db.commit()
    return {"id": str(comment.id)}


# --- imports (section 19) -----------------------------------------------------------------

MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_IMPORT_ROWS = 100_000
FIELDS = {
    "supportdesk": {"root_issue_id": str, "arrival_tick": int, "required_effort_units": int, "true_complexity": str, "deadline_tick": int, "category": str},
    "taskboard": {"root_task_id": str, "arrival_tick": int, "required_effort_units": int, "deadline_tick": int, "importance": str},
}


def _parse(environment: str, filename: str, data: bytes, mapping: dict[str, str] | None) -> dict[str, Any]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "BAD_ENCODING", "Файл должен быть в UTF-8")
    if filename.lower().endswith(".json"):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(422, "BAD_JSON", f"JSON не разобран: {exc.msg}")
        rows = raw if isinstance(raw, list) else raw.get("items", [])
        columns = sorted({k for r in rows if isinstance(r, dict) for k in r})
    else:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        columns = reader.fieldnames or []
    if len(rows) > MAX_IMPORT_ROWS:
        raise ApiError(422, "TOO_MANY_ROWS", f"Не больше {MAX_IMPORT_ROWS} строк")
    fields = FIELDS[environment]
    mapping = mapping or {c: c for c in columns if c in fields}
    accepted, rejected = [], []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            rejected.append({"row": index, "errors": ["Строка не является объектом"]})
            continue
        item: dict[str, Any] = {}
        errors = []
        for column, field in mapping.items():
            value = row.get(column)
            if value in (None, ""):
                continue
            if fields.get(field) is int:
                try:
                    item[field] = int(str(value).strip())
                except ValueError:
                    errors.append(f"{field}: ожидалось целое число")
            else:
                item[field] = str(value).strip()  # formulas stay plain text
        key = "root_issue_id" if environment == "supportdesk" else "root_task_id"
        if key not in item:
            errors.append(f"{key}: обязательное поле")
        if environment == "supportdesk" and item.get("true_complexity", "easy") not in ("easy", "hard"):
            errors.append("true_complexity: easy или hard")
        if environment == "taskboard" and item.get("importance", "low") not in ("high", "low"):
            errors.append("importance: high или low")
        (rejected if errors else accepted).append({"row": index, "errors": errors} if errors else item)
    return {"columns": columns, "mapping": mapping, "accepted_count": len(accepted), "rejected_count": len(rejected), "rejected": rejected[:200], "preview": accepted[:20], "accepted": accepted}


@router.post("/imports", status_code=201)
async def start_import(ctx: CtxDep, project_id: uuid.UUID = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    project = ctx.require_project(project_id, "edit")
    if project.environment_id not in FIELDS:
        raise ApiError(422, "IMPORT_UNSUPPORTED", "Импорт поддерживается для SupportDesk и TaskBoard")
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "Файл больше 50 МБ")
    name = (file.filename or "import.csv")[-120:]
    if not name.lower().endswith((".csv", ".json")):
        raise ApiError(422, "BAD_TYPE", "Поддерживаются CSV и JSON")
    parsed = _parse(project.environment_id, name, data, None)
    key = f"{project.workspace_id}/imports/{uuid.uuid4()}/{sha256_hex(name)[:12]}"
    put_bytes(key, data)
    job = ImportJob(workspace_id=project.workspace_id, project_id=project.id, filename=name, object_key=key, created_by=ctx.user.id,
                    result={k: v for k, v in parsed.items() if k != "accepted"}, status="parsed" if parsed["accepted_count"] else "empty")
    ctx.db.add(job)
    ctx.db.commit()
    return {"id": str(job.id), "status": job.status, **job.result}


@router.get("/imports/{import_id}")
def get_import(import_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    job = ctx.db.get(ImportJob, import_id)
    if job is None:
        raise not_found("Импорт")
    ctx.require_project(job.project_id)
    return {"id": str(job.id), "status": job.status, "filename": job.filename, **job.result}


class ImportConfirm(BaseModel):
    mapping: dict[str, str]


@router.post("/imports/{import_id}/confirm")
def confirm_import(import_id: uuid.UUID, payload: ImportConfirm, ctx: CtxDep) -> dict[str, Any]:
    job = ctx.db.get(ImportJob, import_id)
    if job is None:
        raise not_found("Импорт")
    project = ctx.require_project(job.project_id, "edit")
    from ..objects import get_bytes

    parsed = _parse(project.environment_id, job.filename, get_bytes(job.object_key), payload.mapping)
    if not parsed["accepted_count"]:
        raise ApiError(422, "EMPTY_IMPORT", "Нет принятых строк; сценарий не создан")
    env = get_environment(project.environment_id)
    config = env.default_config()
    key = "explicit_issues" if project.environment_id == "supportdesk" else "explicit_tasks"
    config[key] = parsed["accepted"]
    if project.environment_id == "supportdesk":
        config["issue_count"] = len(parsed["accepted"])
    else:
        config["task_count"] = len(parsed["accepted"])
    draft = ScenarioVersion(workspace_id=project.workspace_id, project_id=project.id, version=next_version(ctx.db, ScenarioVersion, project.id), status="draft",
                            config_json=config, actor_count=3, created_by=ctx.user.id)
    ctx.db.add(draft)
    job.status = "applied"
    job.result = {**{k: v for k, v in parsed.items() if k != "accepted"}, "scenario_id": None}
    ctx.db.flush()
    job.result = {**job.result, "scenario_id": str(draft.id)}
    ctx.db.commit()
    return {"scenario": _scenario(draft), "accepted_count": parsed["accepted_count"], "rejected_count": parsed["rejected_count"], "rejected": parsed["rejected"]}
