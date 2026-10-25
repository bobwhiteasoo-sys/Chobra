"""Contracts used by the completed frontend, including authorization failures."""
import uuid

import pytest

from .conftest import Api, drain_jobs, plan_for


@pytest.fixture(scope="module")
def comparison_batch(alice, project):
    response = alice.post("/batches", plan_for(alice, project, seeds=(601, 602)))
    assert response.status_code == 202, response.text
    drain_jobs()
    return alice.get(f"/batches/{response.json()['batch_id']}").json()


def test_profile_update_preserves_identity():
    user = Api("До изменения", "profile-contract@example.test")
    response = user.patch("/me", {"display_name": " Новое имя ", "locale": "en"})
    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Новое имя"
    assert response.json()["locale"] == "en"
    assert response.json()["email"] == "profile-contract@example.test"
    assert user.get("/me").json()["display_name"] == "Новое имя"
    assert user.patch("/me", {"display_name": "   "}).status_code == 422


def test_workspace_models_are_validated_and_owner_only(alice, workspace):
    admin = Api("Администратор", "models-admin@example.test")
    alice.post(f"/workspaces/{workspace['id']}/members", {"email": "models-admin@example.test", "role": "admin"})
    settings = alice.get(f"/workspaces/{workspace['id']}").json()["model_settings"]
    path = f"/workspaces/{workspace['id']}"
    assert admin.patch(path, {"model_settings": settings}).status_code == 403
    assert alice.patch(path, {"model_settings": {"default_model": "unknown", "allowed_models": ["unknown"]}}).status_code == 422
    assert alice.patch(path, {"model_settings": settings}).status_code == 200
    assert alice.patch(path, {"limits": {"max_agents": -1}}).status_code == 422


def test_project_comparisons_list_checks_tenant(alice, bob, project, comparison_batch):
    path = f"/projects/{project['id']}/comparisons"
    response = alice.get(path)
    assert response.status_code == 200
    assert comparison_batch["comparison_id"] in [c["id"] for c in response.json()["items"]]
    assert all(c["project_id"] == project["id"] for c in response.json()["items"])
    assert bob.get(path).status_code == 404


def test_exclusion_keeps_runs_and_rejects_outside_batch(alice, comparison_batch):
    path = f"/comparisons/{comparison_batch['comparison_id']}/exclusions"
    assert alice.post(path, {"run_id": str(uuid.uuid4()), "reason": "Чужой запуск"}).status_code == 404
    run_id = comparison_batch["runs"][0]["id"]
    assert alice.post(path, {"run_id": run_id, "reason": "   "}).status_code == 422
    assert alice.post(path, {"run_id": run_id, "reason": "Проверка чувствительности анализа"}).status_code == 200
    assert alice.post(path, {"run_id": run_id, "reason": "Повтор"}).status_code == 409
    drain_jobs()
    assert alice.get(f"/runs/{run_id}").status_code == 200
    data = alice.get(f"/comparisons/{comparison_batch['comparison_id']}").json()
    assert data["excluded_runs"][0]["run_id"] == run_id
    assert len(data["runs"]) == len(comparison_batch["runs"])


def test_decision_accepts_only_a_compared_variant(alice, comparison_batch):
    path = f"/comparisons/{comparison_batch['comparison_id']}/decision"
    assert alice.post(path, {"accepted_variant": "Несуществующий вариант"}).status_code == 422
    label = comparison_batch["runs"][0]["variant_label"]
    response = alice.post(path, {"accepted_variant": label, "note": "Принято для следующего испытания"})
    assert response.status_code == 200
    assert response.json()["decision"]["accepted_variant"] == label
