"""Identity, workspaces, members, provider keys and the environment catalog."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from chobra_agents.budget import PRICES
from chobra_agents.profiles import MODE_LABELS, PROFILES
from chobra_audit.catalog import available_checks
from chobra_audit.comparison import COMPARISON_METRICS
from chobra_engine.contract import TickContext
from chobra_engine.rules import compute_examples, validate_rule
from chobra_envs.registry import ENVIRONMENTS, TEMPLATES, get_environment
from chobra_envs.rules_catalog import starting_rules

from ..access import ROLE_RANK, dev_mode_required, load_roles
from ..config import settings
from ..db import set_tenant
from ..deps import CtxDep, DbDep
from ..errors import ApiError, conflict, forbidden, not_found
from ..models import AuditLog, AuthSession, Membership, ProviderKey, User, Workspace
from ..security import CSRF_COOKIE, SESSION_COOKIE, create_session, decrypt_secret, encrypt_secret, load_session, now
from ..services import audit

router = APIRouter()


# --- identity --------------------------------------------------------------------------

def _set_cookies(response: Response, token: str, csrf: str) -> None:
    max_age = settings.session_max_days * 86400
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=settings.secure_cookies, samesite="lax", path="/")


def _me(db, user: User, session: AuthSession) -> dict[str, Any]:
    roles = load_roles(db, user)
    set_tenant(db, user.id, roles.keys())
    workspaces = db.execute(select(Workspace).where(Workspace.id.in_(list(roles)))).scalars().all() if roles else []
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "email": user.email,
        "locale": user.locale,
        "auth_mode": settings.auth_mode,
        "csrf_token": session.csrf_token,
        "last_workspace_id": str(session.last_workspace_id) if session.last_workspace_id in roles else (str(workspaces[0].id) if workspaces else None),
        "workspaces": [{"id": str(w.id), "name": w.name, "role": roles[w.id]} for w in sorted(workspaces, key=lambda w: w.created_at)],
    }


@router.get("/auth/config")
def auth_config() -> dict[str, Any]:
    return {"mode": settings.auth_mode, "oidc_configured": bool(settings.oidc_issuer and settings.oidc_client_id)}


class DevLogin(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)


@router.post("/auth/dev-login")
def dev_login(payload: DevLogin, response: Response, db: DbDep) -> dict[str, Any]:
    """Development sign-in. Disabled unless CHOBRA_AUTH_MODE=dev; labelled in the UI."""
    dev_mode_required()
    subject = payload.email.strip().lower()
    user = db.execute(select(User).where(User.oidc_issuer == "dev", User.oidc_subject == subject)).scalar_one_or_none()
    if user is None:
        user = User(oidc_issuer="dev", oidc_subject=subject, display_name=payload.display_name.strip(), email=subject)
        db.add(user)
        db.flush()
    token, session = create_session(db, user)
    db.commit()
    _set_cookies(response, token, session.csrf_token)
    return _me(db, user, session)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: DbDep) -> dict[str, Any]:
    loaded = load_session(db, request.cookies.get(SESSION_COOKIE))
    if loaded is not None:
        loaded[0].revoked_at = now()
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: CtxDep) -> dict[str, Any]:
    data = _me(ctx.db, ctx.user, ctx.session)
    ctx.db.commit()
    return data


class LastWorkspace(BaseModel):
    workspace_id: uuid.UUID


@router.post("/me/last-workspace")
def set_last_workspace(payload: LastWorkspace, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(payload.workspace_id)
    ctx.session.last_workspace_id = payload.workspace_id
    ctx.db.commit()
    return {"ok": True}


# --- workspaces --------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _workspace(w: Workspace, role: str) -> dict[str, Any]:
    return {"id": str(w.id), "name": w.name, "role": role, "limits": w.limits, "retention_policy": w.retention_policy, "status": w.status,
            "model_settings": w.model_settings, "created_at": w.created_at.isoformat() if w.created_at else None}


DEFAULT_LIMITS = {"max_concurrent_runs": 4, "max_runs_per_series": 100, "max_agents": 20, "max_horizon_ticks": 240}
DEFAULT_RETENTION = {"events_days": 180, "raw_model_io_days": 30, "technical_logs_days": 30}


@router.get("/workspaces")
def list_workspaces(ctx: CtxDep) -> dict[str, Any]:
    items = ctx.db.execute(select(Workspace).where(Workspace.id.in_(ctx.workspace_ids)).order_by(Workspace.created_at)).scalars().all() if ctx.roles else []
    return {"items": [_workspace(w, ctx.roles[w.id]) for w in items]}


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, ctx: CtxDep) -> dict[str, Any]:
    workspace = Workspace(name=payload.name.strip(), owner_id=ctx.user.id, limits=dict(DEFAULT_LIMITS), retention_policy=dict(DEFAULT_RETENTION),
                          model_settings={"default_model": "claude-opus-5-5", "allowed_models": sorted(PRICES)})
    ctx.db.add(workspace)
    ctx.db.flush()
    ctx.db.add(Membership(workspace_id=workspace.id, user_id=ctx.user.id, role="owner"))
    ctx.roles[workspace.id] = "owner"
    set_tenant(ctx.db, ctx.user.id, ctx.roles.keys())
    audit(ctx.db, workspace.id, ctx.user.id, "workspace.create", f"workspace:{workspace.id}")
    ctx.session.last_workspace_id = workspace.id
    ctx.db.commit()
    return _workspace(workspace, "owner")


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    role = ctx.require_workspace(workspace_id)
    return _workspace(ctx.db.get(Workspace, workspace_id), role)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    limits: dict[str, int] | None = None
    retention_policy: dict[str, int] | None = None


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: uuid.UUID, payload: WorkspacePatch, ctx: CtxDep) -> dict[str, Any]:
    role = ctx.require_workspace(workspace_id, "manage")
    workspace = ctx.db.get(Workspace, workspace_id)
    if payload.name:
        workspace.name = payload.name.strip()
    if payload.limits is not None:
        merged = {**workspace.limits}
        for key, value in payload.limits.items():
            ceiling = DEFAULT_LIMITS.get(key)
            if ceiling is None:
                raise ApiError(422, "UNKNOWN_LIMIT", f"Неизвестный предел {key}")
            if value > ceiling:
                raise ApiError(422, "LIMIT_TOO_HIGH", f"{key} не больше {ceiling}; увеличение требует нагрузочной проверки")
            if role != "owner" and value > workspace.limits.get(key, ceiling):
                raise forbidden("Повысить предел может только владелец")
            merged[key] = value
        workspace.limits = merged
    if payload.retention_policy is not None:
        if role != "owner":
            raise forbidden("Срок хранения меняет владелец")
        merged = {**workspace.retention_policy}
        for key, value in payload.retention_policy.items():
            if key not in DEFAULT_RETENTION or not 1 <= value <= DEFAULT_RETENTION[key]:
                raise ApiError(422, "BAD_RETENTION", f"{key}: от 1 до {DEFAULT_RETENTION.get(key)} дней")
            merged[key] = value
        workspace.retention_policy = merged
    audit(ctx.db, workspace_id, ctx.user.id, "workspace.update", f"workspace:{workspace_id}")
    ctx.db.commit()
    return _workspace(workspace, role)


@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(workspace_id)
    rows = ctx.db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.workspace_id == workspace_id).order_by(Membership.created_at)).all()
    return {"items": [{"id": str(m.id), "user_id": str(u.id), "display_name": u.display_name, "email": u.email, "role": m.role, "status": m.status} for m, u in rows]}


class MemberInvite(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str = Field(pattern="^(admin|analyst|viewer)$")
    display_name: str | None = None


@router.post("/workspaces/{workspace_id}/members", status_code=201)
def invite_member(workspace_id: uuid.UUID, payload: MemberInvite, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(workspace_id, "manage")
    subject = payload.email.strip().lower()
    user = ctx.db.execute(select(User).where(User.email == subject)).scalars().first()
    if user is None:
        user = User(oidc_issuer="dev" if settings.dev_auth else "invite", oidc_subject=subject, display_name=payload.display_name or subject.split("@")[0], email=subject)
        ctx.db.add(user)
        ctx.db.flush()
    existing = ctx.db.execute(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)).scalar_one_or_none()
    if existing is not None and existing.status == "active":
        raise conflict("ALREADY_MEMBER", "Пользователь уже участник пространства")
    if existing is not None:
        existing.status, existing.role = "active", payload.role
        member = existing
    else:
        member = Membership(workspace_id=workspace_id, user_id=user.id, role=payload.role)
        ctx.db.add(member)
    audit(ctx.db, workspace_id, ctx.user.id, "member.invite", f"user:{user.id}", role=payload.role)
    ctx.db.commit()
    return {"id": str(member.id), "user_id": str(user.id), "email": user.email, "role": member.role, "status": member.status}


class MemberPatch(BaseModel):
    role: str = Field(pattern="^(admin|analyst|viewer)$")


def _member(ctx, member_id: uuid.UUID) -> Membership:
    member = ctx.db.get(Membership, member_id)
    if member is None or member.workspace_id not in ctx.roles:
        raise not_found("Участник")
    return member


@router.patch("/members/{member_id}")
def patch_member(member_id: uuid.UUID, payload: MemberPatch, ctx: CtxDep) -> dict[str, Any]:
    member = _member(ctx, member_id)
    role = ctx.require_workspace(member.workspace_id, "manage")
    if member.role == "owner":
        raise forbidden("Роль владельца меняется только передачей владения")
    if member.role == "admin" and role != "owner":
        raise forbidden("Администратора меняет владелец")
    member.role = payload.role
    audit(ctx.db, member.workspace_id, ctx.user.id, "member.role", f"membership:{member.id}", role=payload.role)
    ctx.db.commit()
    return {"id": str(member.id), "role": member.role}


@router.delete("/members/{member_id}")
def revoke_member(member_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    member = _member(ctx, member_id)
    ctx.require_workspace(member.workspace_id, "manage")
    if member.role == "owner":
        owners = ctx.db.execute(select(func.count()).select_from(Membership).where(Membership.workspace_id == member.workspace_id, Membership.role == "owner", Membership.status == "active")).scalar()
        if owners <= 1:
            raise conflict("LAST_OWNER", "В пространстве должен остаться хотя бы один владелец")
    member.status = "revoked"
    audit(ctx.db, member.workspace_id, ctx.user.id, "member.revoke", f"membership:{member.id}")
    ctx.db.commit()
    return {"id": str(member.id), "status": member.status}


class OwnershipTransfer(BaseModel):
    member_id: uuid.UUID
    confirm_display_name: str


@router.post("/workspaces/{workspace_id}/transfer-ownership")
def transfer_ownership(workspace_id: uuid.UUID, payload: OwnershipTransfer, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(workspace_id, "own")
    # Re-confirmation: in OIDC mode this is a fresh login at the provider; in dev mode the owner retypes their name.
    if payload.confirm_display_name.strip() != ctx.user.display_name:
        raise forbidden("Подтверждение личности не прошло")
    member = _member(ctx, payload.member_id)
    if member.workspace_id != workspace_id or member.status != "active":
        raise not_found("Участник")
    mine = ctx.db.execute(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == ctx.user.id)).scalar_one()
    member.role, mine.role = "owner", "admin"
    ctx.db.get(Workspace, workspace_id).owner_id = member.user_id
    audit(ctx.db, workspace_id, ctx.user.id, "workspace.transfer_ownership", f"membership:{member.id}")
    ctx.db.commit()
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/audit")
def audit_log(workspace_id: uuid.UUID, ctx: CtxDep, limit: int = 100) -> dict[str, Any]:
    ctx.require_workspace(workspace_id, "manage")
    rows = ctx.db.execute(select(AuditLog).where(AuditLog.workspace_id == workspace_id).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 100))).scalars().all()
    return {"items": [{"id": r.id, "operation": r.operation, "object_ref": r.object_ref, "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None, "timestamp": r.timestamp.isoformat(), "details": r.details} for r in rows]}


# --- provider keys ------------------------------------------------------------------------

class KeyCreate(BaseModel):
    provider: str = Field(pattern="^anthropic$")
    api_key: str = Field(min_length=10, max_length=300)


@router.get("/workspaces/{workspace_id}/provider-keys")
def list_keys(workspace_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(workspace_id, "manage")
    rows = ctx.db.execute(select(ProviderKey).where(ProviderKey.workspace_id == workspace_id, ProviderKey.status == "active")).scalars().all()
    env_key = bool(settings.anthropic_api_key)
    return {"items": [{"id": str(k.id), "provider": k.provider, "last4": k.last4, "created_at": k.created_at.isoformat()} for k in rows], "deployment_key_present": env_key}


@router.post("/workspaces/{workspace_id}/provider-keys", status_code=201)
def add_key(workspace_id: uuid.UUID, payload: KeyCreate, ctx: CtxDep) -> dict[str, Any]:
    ctx.require_workspace(workspace_id, "own")
    for old in ctx.db.execute(select(ProviderKey).where(ProviderKey.workspace_id == workspace_id, ProviderKey.provider == payload.provider, ProviderKey.status == "active")).scalars():
        old.status = "replaced"
    key = ProviderKey(workspace_id=workspace_id, provider=payload.provider, ciphertext=encrypt_secret(payload.api_key.strip()), last4=payload.api_key.strip()[-4:])
    ctx.db.add(key)
    audit(ctx.db, workspace_id, ctx.user.id, "provider_key.set", f"provider:{payload.provider}", last4=key.last4)
    ctx.db.commit()
    return {"id": str(key.id), "provider": key.provider, "last4": key.last4}


@router.delete("/provider-keys/{key_id}")
def revoke_key(key_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    key = ctx.db.get(ProviderKey, key_id)
    if key is None or key.workspace_id not in ctx.roles:
        raise not_found("Ключ")
    ctx.require_workspace(key.workspace_id, "own")
    key.status = "revoked"
    audit(ctx.db, key.workspace_id, ctx.user.id, "provider_key.revoke", f"provider:{key.provider}", last4=key.last4)
    ctx.db.commit()
    return {"id": str(key.id), "status": key.status}


@router.post("/workspaces/{workspace_id}/provider-keys/check")
def check_key(workspace_id: uuid.UUID, ctx: CtxDep) -> dict[str, Any]:
    """A minimal paid request to confirm the connection. Shows only status and available models."""
    ctx.require_workspace(workspace_id, "manage")
    key = ctx.db.execute(select(ProviderKey).where(ProviderKey.workspace_id == workspace_id, ProviderKey.status == "active")).scalars().first()
    secret = decrypt_secret(key.ciphertext) if key else settings.anthropic_api_key
    if not secret:
        return {"status": "no_key", "message": "Ключ не задан; доступны только сценарные агенты и replay"}
    import anthropic

    try:
        client = anthropic.Anthropic(api_key=secret, max_retries=0, timeout=20)
        models = [m.id for m in client.models.list(limit=50)]
    except anthropic.AuthenticationError:
        return {"status": "auth_failed", "message": "Провайдер отклонил ключ"}
    except anthropic.APIError as exc:
        return {"status": "unavailable", "message": type(exc).__name__}
    return {"status": "ok", "models": [m for m in models if m in PRICES] or models[:10]}


# --- catalog -----------------------------------------------------------------------------

@router.get("/environments")
def environments() -> dict[str, Any]:
    items = []
    for name in ENVIRONMENTS:
        env = get_environment(name)
        config = env.default_config()
        actions = env.list_actions(env.build_initial_state(config, 1, ["agent_01"]), "agent_01", TickContext(1, 1, config))
        items.append(
            {
                "name": name,
                "version": env.version,
                "template": TEMPLATES[name],
                "default_config": config,
                "actions": [{"type": a.type, "description": a.description, "schema": a.schema, "cost": a.cost, "events": list(a.possible_events)} for a in actions],
                "triggers": {
                    k: {"description": t.description, "confirmed_outcome": t.confirmed_outcome, "repeatable_per_root": t.repeatable_per_root,
                        "fields": {f: {"type": s.type, "unit": s.unit, "enum": list(s.enum_values), "mutable_by_actor": s.mutable_by_actor, "description": s.description} for f, s in t.fields.items()}}
                    for k, t in env.triggers().items()
                },
                "entity_fields": {f: {"type": s.type, "unit": s.unit, "enum": list(s.enum_values), "mutable_by_actor": s.mutable_by_actor, "description": s.description} for f, s in env.entity_fields().items()},
                "checks": available_checks(name),
                "comparison_metrics": [{"id": m, "direction": d, "title": t} for m, d, t in COMPARISON_METRICS[name]],
            }
        )
    return {"items": items}


@router.get("/templates")
def templates() -> dict[str, Any]:
    out = []
    for name, template in TEMPLATES.items():
        env = get_environment(name)
        rules = starting_rules(name)
        out.append({
            "environment": name,
            **template,
            "starting_rules": [{"key": k, "name": r["name"], "description": r["description"], "source_text": r["source_text"], "tree": r["tree"],
                                "validation": validate_rule(r["tree"], env).to_dict(), "examples": compute_examples(r["tree"], env)} for k, r in rules.items()],
        })
    return {"items": out}


@router.get("/settings/models")
def models_catalog() -> dict[str, Any]:
    return {
        "default_model": "claude-opus-5-5",
        "models": [{"id": p.model, "input_usd_per_mtok": f"{p.input_microusd_per_mtok / 1_000_000:.2f}", "output_usd_per_mtok": f"{p.output_microusd_per_mtok / 1_000_000:.2f}",
                    "currency": p.currency, "price_source": p.source, "price_as_of": p.as_of} for p in PRICES.values()],
        "modes": [{"id": m, "label": MODE_LABELS[m], "defaults": PROFILES[m].to_dict()} for m in MODE_LABELS],
        "deployment_key_present": bool(settings.anthropic_api_key),
        "note": "Параметры профиля — настройки экспериментального агента, а не типы человеческой личности.",
    }
