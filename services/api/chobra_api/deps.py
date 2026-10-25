"""Request dependencies: one database session per request and the authenticated context."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .access import Ctx, authenticate
from .db import SessionLocal


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def get_ctx(request: Request, db: DbDep) -> Ctx:
    return authenticate(request, db)


CtxDep = Annotated[Ctx, Depends(get_ctx)]
