"""Database access as the application role with a transaction-local tenant context.

The context (`app.user_id`, `app.workspace_ids`) is set with `set_config(..., true)` at the
start of every transaction, so it disappears when the connection returns to the pool.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20, future=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False, future=True)


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, transaction, connection) -> None:  # noqa: ANN001
    tenant = session.info.get("tenant")
    if tenant is None:
        return
    user_id, workspace_ids = tenant
    connection.execute(
        text("SELECT set_config('app.user_id', :u, true), set_config('app.workspace_ids', :w, true)"),
        {"u": str(user_id) if user_id else "", "w": ",".join(str(w) for w in workspace_ids)},
    )


def set_tenant(session: Session, user_id: uuid.UUID | None, workspace_ids: Iterable[uuid.UUID]) -> None:
    """Install the tenant for this session; applies to the current and every later transaction."""
    session.info["tenant"] = (user_id, list(workspace_ids))
    if session.in_transaction():
        user, ids = session.info["tenant"]
        session.execute(
            text("SELECT set_config('app.user_id', :u, true), set_config('app.workspace_ids', :w, true)"),
            {"u": str(user) if user else "", "w": ",".join(str(w) for w in ids)},
        )
