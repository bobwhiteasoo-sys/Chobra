"""Access checks (spec section 03): effective right = workspace role ∩ project permission."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import set_tenant
from .errors import ApiError, forbidden, not_found
from .models import AuthSession, Membership, Project, ProjectPermission, User
from .security import CSRF_HEADER, SESSION_COOKIE, load_session

ROLE_RANK = {"viewer": 1, "analyst": 2, "admin": 3, "owner": 4}
NEED_ROLE = {"read": "viewer", "edit": "analyst", "run": "analyst", "export": "analyst", "manage": "admin", "own": "owner"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Ctx:
    db: Session
    user: User
    session: AuthSession
    roles: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def workspace_ids(self) -> list[uuid.UUID]:
        return list(self.roles)

    def role(self, workspace_id: uuid.UUID) -> str | None:
        return self.roles.get(workspace_id)

    def require_workspace(self, workspace_id: uuid.UUID, need: str = "read") -> str:
        role = self.role(workspace_id)
        if role is None:
            raise not_found("Рабочее пространство")
        if ROLE_RANK[role] < ROLE_RANK[NEED_ROLE[need]]:
            raise forbidden()
        return role

    def require_project(self, project_id: uuid.UUID, need: str = "read") -> Project:
        project = self.db.get(Project, project_id)
        if project is None or project.workspace_id not in self.roles:
            raise not_found("Проект")
        role = self.roles[project.workspace_id]
        allowed = ROLE_RANK[role] >= ROLE_RANK[NEED_ROLE[need]]
        if need == "export" and role == "viewer":
            allowed = self._project_permission(project) == "export"
        if project.restricted and role not in ("owner", "admin"):
            permission = self._project_permission(project)
            if permission is None:
                raise not_found("Проект")
            if need in ("edit", "run") and permission != "editor":
                allowed = False
        if not allowed:
            raise forbidden()
        return project

    def _project_permission(self, project: Project) -> str | None:
        return self.db.execute(
            select(ProjectPermission.permission).where(ProjectPermission.project_id == project.id, ProjectPermission.principal_id == self.user.id)
        ).scalar_one_or_none()


def load_roles(db: Session, user: User) -> dict[uuid.UUID, str]:
    set_tenant(db, user.id, [])
    rows = db.execute(select(Membership.workspace_id, Membership.role).where(Membership.user_id == user.id, Membership.status == "active")).all()
    return {ws: role for ws, role in rows}


def authenticate(request: Request, db: Session) -> Ctx:
    loaded = load_session(db, request.cookies.get(SESSION_COOKIE))
    if loaded is None:
        raise ApiError(401, "UNAUTHENTICATED", "Нужно войти в систему")
    session, user = loaded
    if request.method in UNSAFE:
        header = request.headers.get(CSRF_HEADER)
        if not header or header != session.csrf_token:
            raise ApiError(403, "CSRF_FAILED", "Запрос отклонен защитой от подделки (CSRF)")
    roles = load_roles(db, user)
    set_tenant(db, user.id, roles.keys())
    return Ctx(db=db, user=user, session=session, roles=roles)


def dev_mode_required() -> None:
    if not settings.dev_auth:
        raise ApiError(404, "NOT_FOUND", "Недоступно в этом режиме входа")
