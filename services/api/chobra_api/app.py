"""Chobra API application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import errors
from .config import settings
from .db import SessionLocal
from .routers import core, projects, runs
from .services import seed_environment_versions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        seed_environment_versions(db)
        db.commit()
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Chobra API", version="1.0.0", lifespan=lifespan, openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs")
    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "If-Match", "Idempotency-Key", "Last-Event-ID", "X-Request-ID"],
    )
    for module in (core, projects, runs):
        app.include_router(module.router, prefix="/api/v1")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ready"}

    return app


app = create_app()
