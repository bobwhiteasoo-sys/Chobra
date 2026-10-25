"""API tests run against a freshly migrated `chobra_test` database on the local PostgreSQL."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("CHOBRA_DATABASE_URL", "postgresql+psycopg://chobra_app@127.0.0.1:54329/chobra_test")
os.environ.setdefault("CHOBRA_OWNER_DATABASE_URL", "postgresql+psycopg://chobra_owner@127.0.0.1:54329/chobra_test")
os.environ.setdefault("CHOBRA_OBJECTS_DIR", tempfile.mkdtemp(prefix="chobra-objects-"))
os.environ["CHOBRA_AUTH_MODE"] = "dev"
os.environ.pop("ANTHROPIC_API_KEY", None)

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reset_database() -> None:
    with psycopg.connect(host="127.0.0.1", port=54329, user="postgres", dbname="postgres", autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'chobra_test' AND pid <> pg_backend_pid()")
        conn.execute("DROP DATABASE IF EXISTS chobra_test")
        conn.execute("CREATE DATABASE chobra_test OWNER chobra_owner")
    config = Config(os.path.join(ROOT, "services/api/alembic.ini"))
    config.set_main_option("script_location", os.path.join(ROOT, "services/api/migrations"))
    config.set_main_option("sqlalchemy.url", os.environ["CHOBRA_OWNER_DATABASE_URL"])
    command.upgrade(config, "head")


_reset_database()

from chobra_api.app import create_app  # noqa: E402
from chobra_worker.main import run_one  # noqa: E402


class Api:
    """TestClient wrapper that keeps one user's cookies and sends the CSRF header."""

    def __init__(self, name: str, email: str):
        self.client = TestClient(create_app())
        response = self.client.post("/api/v1/auth/dev-login", json={"display_name": name, "email": email})
        assert response.status_code == 200, response.text
        self.me = response.json()
        self.csrf = self.me["csrf_token"]

    def _headers(self, extra: dict | None = None) -> dict:
        return {"X-CSRF-Token": self.csrf, **(extra or {})}

    def get(self, path: str, **kw):
        return self.client.get(f"/api/v1{path}", **kw)

    def post(self, path: str, json: dict | None = None, headers: dict | None = None, **kw):
        return self.client.post(f"/api/v1{path}", json=json, headers=self._headers(headers), **kw)

    def patch(self, path: str, json: dict, headers: dict | None = None):
        return self.client.patch(f"/api/v1{path}", json=json, headers=self._headers(headers))

    def put(self, path: str, json: dict):
        return self.client.put(f"/api/v1{path}", json=json, headers=self._headers())

    def delete(self, path: str):
        return self.client.delete(f"/api/v1{path}", headers=self._headers())


def drain_jobs(limit: int = 500) -> int:
    count = 0
    while count < limit and run_one("test-worker"):
        count += 1
    return count


@pytest.fixture(scope="session")
def alice() -> Api:
    return Api("Алиса", "alice@example.test")


@pytest.fixture(scope="session")
def bob() -> Api:
    return Api("Боб", "bob@example.test")


@pytest.fixture(scope="session")
def workspace(alice: Api) -> dict:
    response = alice.post("/workspaces", {"name": "Пространство Алисы"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="session")
def project(alice: Api, workspace: dict) -> dict:
    response = alice.post("/projects", {"workspace_id": workspace["id"], "name": "Премии поддержки", "environment_id": "supportdesk"})
    assert response.status_code == 201, response.text
    return alice.get(f"/projects/{response.json()['id']}").json()


def plan_for(api: Api, project: dict, rule_keys=("SD-P1", "SD-P2"), seeds=(101, 102, 103), profile_name="Ищет награду (сценарный)", **extra) -> dict:
    rules = {r["template_key"]: r for r in project["rules"]}
    profiles = api.get(f"/projects/{project['id']}/agents").json()["items"]
    profile = next(p for p in profiles if p["name"] == profile_name)
    scenario = next(s for s in project["scenarios"] if s["status"] == "published")
    return {
        "project_id": project["id"],
        "scenario_version_id": scenario["id"],
        "variants": [{"label": key, "rule_version_id": rules[key]["id"]} for key in rule_keys],
        "agent_profile_id": profile["id"],
        "conditions": {"seeds": list(seeds), "horizon_ticks": 30},
        **extra,
    }
