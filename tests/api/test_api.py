import json
import uuid

import pytest
from sqlalchemy import func, select

from chobra_api.config import settings
from chobra_api.db import SessionLocal, set_tenant
from chobra_api.models import Run, RunEvent

from .conftest import Api, drain_jobs, plan_for


# --- access ---------------------------------------------------------------------------

def test_login_and_logout_close_protected_routes():
    carol = Api("Кэрол", "carol@example.test")
    assert carol.get("/me").status_code == 200
    assert carol.post("/auth/logout").status_code == 200
    response = carol.get("/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert response.json()["request_id"]


def test_mutation_without_csrf_header_is_rejected(alice, workspace):
    response = alice.client.post("/api/v1/workspaces", json={"name": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


def test_other_workspace_objects_are_invisible_by_id(alice, bob, project):
    bob.post("/workspaces", {"name": "Пространство Боба"})
    assert bob.get(f"/projects/{project['id']}").status_code == 404
    rule = project["rules"][0]
    assert bob.get(f"/rules/{rule['id']}").status_code == 404
    assert bob.post("/rules/validate", {"project_id": project["id"], "tree": rule["tree"] if "tree" in rule else {}}).status_code == 404
    assert bob.get(f"/projects?workspace_id={project['workspace_id']}").status_code == 404


def test_roles_limit_actions(alice, workspace, project):
    dave = Api("Дэйв", "dave@example.test")
    erin = Api("Эрин", "erin@example.test")
    assert alice.post(f"/workspaces/{workspace['id']}/members", {"email": "dave@example.test", "role": "viewer"}).status_code == 201
    assert alice.post(f"/workspaces/{workspace['id']}/members", {"email": "erin@example.test", "role": "analyst"}).status_code == 201
    assert dave.get(f"/projects/{project['id']}").status_code == 200
    assert dave.post("/batches", plan_for(dave, project)).status_code == 403
    assert dave.post("/rules", {"project_id": project["id"], "name": "x", "tree": {}}).status_code == 403
    assert erin.post(f"/workspaces/{workspace['id']}/provider-keys", {"provider": "anthropic", "api_key": "sk-ant-test-1234567890"}).status_code == 403
    erin_member = next(m for m in alice.get(f"/workspaces/{workspace['id']}/members").json()["items"] if m["email"] == "erin@example.test")
    assert erin.post(f"/workspaces/{workspace['id']}/transfer-ownership", {"member_id": erin_member["id"], "confirm_display_name": "Эрин"}).status_code == 403


def test_revoked_member_loses_access(alice, workspace, project):
    frank = Api("Фрэнк", "frank@example.test")
    member = alice.post(f"/workspaces/{workspace['id']}/members", {"email": "frank@example.test", "role": "analyst"}).json()
    assert frank.get(f"/projects/{project['id']}").status_code == 200
    assert alice.delete(f"/members/{member['id']}").status_code == 200
    assert frank.get(f"/projects/{project['id']}").status_code == 404


def test_last_owner_cannot_be_removed(alice, workspace):
    owner = next(m for m in alice.get(f"/workspaces/{workspace['id']}/members").json()["items"] if m["role"] == "owner")
    response = alice.delete(f"/members/{owner['id']}")
    assert response.status_code == 409 and response.json()["code"] == "LAST_OWNER"


def test_provider_key_is_never_returned_in_full(alice, workspace):
    response = alice.post(f"/workspaces/{workspace['id']}/provider-keys", {"provider": "anthropic", "api_key": "sk-ant-test-secret-abcd"})
    assert response.status_code == 201
    listed = alice.get(f"/workspaces/{workspace['id']}/provider-keys").json()
    assert "sk-ant-test-secret" not in json.dumps(listed)
    assert listed["items"][0]["last4"] == "abcd"
    alice.delete(f"/provider-keys/{listed['items'][0]['id']}")


def test_archive_and_restore_keep_versions(alice, workspace):
    created = alice.post("/projects", {"workspace_id": workspace["id"], "name": "Архивный", "environment_id": "taskboard"}).json()
    before = alice.get(f"/projects/{created['id']}").json()
    assert alice.post(f"/projects/{created['id']}/archive").json()["archived_at"]
    assert alice.post(f"/projects/{created['id']}/restore").json()["archived_at"] is None
    after = alice.get(f"/projects/{created['id']}").json()
    assert [r["ast_hash"] for r in after["rules"]] == [r["ast_hash"] for r in before["rules"]]


# --- versions -------------------------------------------------------------------------

def test_concurrent_draft_edit_returns_conflict(alice, project):
    draft = alice.post("/scenarios", {"project_id": project["id"], "from_version_id": project["scenarios"][0]["id"]}).json()
    first = alice.patch(f"/scenarios/{draft['id']}", {"actor_count": 4}, headers={"If-Match": str(draft["revision"])})
    assert first.status_code == 200
    stale = alice.patch(f"/scenarios/{draft['id']}", {"actor_count": 5}, headers={"If-Match": str(draft["revision"])})
    assert stale.status_code == 409
    assert stale.json()["details"]["current_revision"] == first.json()["revision"]


def test_invalid_rule_cannot_be_published_and_error_has_a_path(alice, project):
    tree = json.loads(json.dumps(next(r for r in alice.get(f"/projects/{project['id']}/rules").json()["items"] if r["template_key"] == "SD-P2")["tree"]))
    tree["amount"] = {"op": "add", "args": [{"literal": 5_000_000, "type": "int", "unit": "reward_microunits"}, {"field": "event.age_ticks"}]}
    draft = alice.post("/rules", {"project_id": project["id"], "name": "Ошибочное", "tree": tree}).json()
    response = alice.post(f"/rules/{draft['id']}/publish")
    assert response.status_code == 422
    assert response.json()["code"] == "RULE_TYPE_MISMATCH"
    assert response.json()["details"]["path"] == "amount.args[1]"


def test_published_rule_is_immutable_and_changes_create_versions(alice, project):
    rule = next(r for r in alice.get(f"/projects/{project['id']}/rules").json()["items"] if r["template_key"] == "SD-P1")
    assert alice.patch(f"/rules/{rule['id']}", {"name": "x"}, headers={"If-Match": str(rule["revision"])}).status_code == 409
    version = alice.post(f"/rules/{rule['id']}/new-version").json()
    assert version["parent_id"] == rule["id"] and version["status"] == "draft"
    assert alice.get(f"/rules/{rule['id']}").json()["ast_hash"] == rule["ast_hash"]


def test_text_compiles_to_a_candidate_with_ambiguities_and_never_publishes(alice, project):
    result = alice.post("/rules/compile", {"project_id": project["id"], "text": "Платить 7 очков за подтвержденное решение"}).json()
    assert result["published"] is False
    assert result["candidate"]["amount"]["literal"] == 7_000_000
    assert any(a["field"] == "deduplication.mode" for a in result["ambiguities"])


def test_validate_returns_examples_and_diff(alice, project):
    rules = {r["template_key"]: r for r in alice.get(f"/projects/{project['id']}/rules").json()["items"]}
    result = alice.post("/rules/validate", {"project_id": project["id"], "tree": rules["SD-P2"]["tree"], "compare_to": rules["SD-P1"]["id"]}).json()
    assert result["validation"]["ok"]
    assert [e["kind"] for e in result["examples"]][:4] == ["ordinary", "technical_repeat", "unit_repeat", "boundary"]
    kinds = {row["kind"] for row in result["diff"]}
    assert {"trigger", "unit_of_account"} <= kinds


# --- series, runs and evidence ------------------------------------------------------------

@pytest.fixture(scope="module")
def finished_batch(alice, project):
    response = alice.post("/batches", plan_for(alice, project), headers={"Idempotency-Key": "batch-1"})
    assert response.status_code == 202, response.text
    batch_id = response.json()["batch_id"]
    drain_jobs()
    return alice.get(f"/batches/{batch_id}").json()


def test_estimate_shows_runs_and_budget(alice, project):
    estimate = alice.post("/batches/estimate", plan_for(alice, project)).json()
    assert estimate["planned_runs"] == 6
    assert estimate["estimate"]["scripted_only"] is True
    assert estimate["estimate"]["model_calls_upper_bound"] == 0


def test_idempotency_key_returns_same_batch_or_conflict(alice, project, finished_batch):
    again = alice.post("/batches", plan_for(alice, project), headers={"Idempotency-Key": "batch-1"})
    assert again.json()["batch_id"] == finished_batch["id"]
    different = alice.post("/batches", plan_for(alice, project, seeds=(9,)), headers={"Idempotency-Key": "batch-1"})
    assert different.status_code == 409 and different.json()["code"] == "IDEMPOTENCY_MISMATCH"


def test_batch_runs_complete_with_comparison_and_findings(alice, project, finished_batch):
    assert finished_batch["counts"]["completed"] == 6
    assert finished_batch["comparison_id"]
    comparison = alice.get(f"/comparisons/{finished_batch['comparison_id']}").json()
    primary = comparison["result"]["primary"]
    assert primary["pairing"]["tapes_match"] is True
    assert primary["pairs_complete"] == 3
    findings = alice.get(f"/projects/{project['id']}/findings").json()["items"]
    assert any(f["check_id"] == "rewarded_rejected_resolution_v1" for f in findings)


def test_invalid_run_command_returns_allowed_commands(alice, finished_batch):
    run = finished_batch["runs"][0]
    response = alice.post(f"/runs/{run['id']}/pause")
    assert response.status_code == 409
    assert response.json()["details"] == {"current_state": "completed", "allowed_commands": []}


def test_events_are_ordered_and_tick_records_carry_state_hashes(alice, finished_batch):
    run = finished_batch["runs"][0]
    events = alice.get(f"/runs/{run['id']}/events?limit=2000").json()["items"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))
    assert all(e["state_hash"] for e in events if e["type"] == "tick.completed")
    state = alice.get(f"/runs/{run['id']}/state?tick=5").json()
    assert state["tick"] == 5 and state["state_hash"]


def test_sse_stream_uses_seq_ids_and_ends_after_completion(alice, finished_batch):
    run = finished_batch["runs"][0]
    with alice.client.stream("GET", f"/api/v1/runs/{run['id']}/stream", headers={"Last-Event-ID": str(run["last_seq"] - 3)}) as response:
        text = "".join(response.iter_text())
    ids = [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")]
    assert ids == [run["last_seq"] - 2, run["last_seq"] - 1, run["last_seq"]]
    assert "event: end" in text


def test_replay_minimize_fix_cycle(alice, project, finished_batch):
    finding = next(f for f in alice.get(f"/projects/{project['id']}/findings").json()["items"] if f["check_id"] == "rewarded_rejected_resolution_v1")
    replayed = alice.post(f"/findings/{finding['id']}/replay").json()
    assert replayed["replay_status"] == "replay_verified"
    assert replayed["replay_result"]["model_calls"] == 0
    assert alice.post(f"/findings/{finding['id']}/minimize").status_code == 202
    drain_jobs()
    minimized = alice.get(f"/findings/{finding['id']}").json()["minimization"]
    assert minimized["status"] in ("minimal", "reduced") and minimized["verified"]
    candidates = alice.post(f"/findings/{finding['id']}/propose-fixes").json()["fix_candidates"]
    assert candidates and all(c["validation"]["ok"] for c in candidates)
    variant = alice.post(f"/findings/{finding['id']}/create-variant", {"candidate_key": candidates[0]["key"]}).json()
    assert alice.post(f"/rules/{variant['id']}/publish").status_code == 200
    check = alice.post(f"/findings/{finding['id']}/check-fix", {"rule_version_id": variant["id"]}).json()
    assert check["reproduced"] is False


def test_lease_loss_blocks_late_commit(finished_batch, workspace):
    from chobra_engine.events import Event
    from chobra_worker.executor import LeaseLost, record_operational

    run = finished_batch["runs"][0]
    run_id, workspace_id = uuid.UUID(run["id"]), uuid.UUID(workspace["id"])

    def event_count() -> int:
        db = SessionLocal()
        set_tenant(db, None, [workspace_id])
        try:
            return db.execute(select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run_id)).scalar()
        finally:
            db.close()

    db = SessionLocal()
    set_tenant(db, None, [workspace_id])
    stale_generation = db.get(Run, run_id).lease_generation - 1
    db.close()
    before = event_count()
    late = Event(run_id=run["id"], seq=run["last_seq"] + 1, domain_seq=None, event_class="operational", tick=99, type="model_call.started", actor_id="agent_01", entity_id=None,
                 payload={"model_call_id": str(uuid.uuid4()), "provider": "fake", "model": "m", "request_hash": "0" * 64}, prev_hash="0" * 64, event_hash="1" * 64)
    with pytest.raises(LeaseLost):
        record_operational(run_id, workspace_id, stale_generation, late)
    assert event_count() == before


def test_reports_share_values_and_links_expire(alice, project, finished_batch):
    created = {fmt: alice.post("/reports", {"project_id": project["id"], "batch_id": finished_batch["id"], "format": fmt}).json() for fmt in ("markdown", "csv", "json")}
    drain_jobs()
    reports = {fmt: alice.get(f"/reports/{r['id']}").json() for fmt, r in created.items()}
    assert all(r["status"] == "ready" for r in reports.values()), reports
    markdown = alice.client.get(reports["markdown"]["download_url"])
    assert markdown.status_code == 200
    assert "Ограничения" in markdown.text and "## Нарушения" in markdown.text
    package = alice.client.get(reports["json"]["download_url"]).json()
    assert "sk-ant" not in json.dumps(package)
    from chobra_reporting.package import verify_package

    verification = verify_package(package)
    assert verification["ok"], verification
    bad = reports["markdown"]["download_url"].split("sig=")[0] + "sig=1.deadbeef"
    assert alice.client.get(bad).status_code == 410


def test_import_reports_rejected_rows_and_keeps_formulas_as_text(alice, project):
    content = "root_issue_id,true_complexity,required_effort_units\nissue_A,hard,3\n=cmd|' /C calc'!A0,easy,1\nissue_C,medium,2\n,easy,1\n"
    response = alice.client.post("/api/v1/imports", data={"project_id": project["id"]}, files={"file": ("issues.csv", content, "text/csv")}, headers={"X-CSRF-Token": alice.csrf})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["accepted_count"] == 2 and result["rejected_count"] == 2
    assert any(p["root_issue_id"].startswith("=cmd") for p in result["preview"])
    empty = alice.client.post("/api/v1/imports", data={"project_id": project["id"]}, files={"file": ("empty.csv", "root_issue_id\n", "text/csv")}, headers={"X-CSRF-Token": alice.csrf}).json()
    assert alice.post(f"/imports/{empty['id']}/confirm", {"mapping": {}}).status_code == 422
