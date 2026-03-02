"""Integration tests for workflow CRUD and run API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import DomainRegistry

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.server import create_app
from agentplatform.settings import SettingsManager


class _MockProvider(BaseLMProvider):
    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        return LMResponse(
            content='{"action": "finish", "result": "done", "reasoning": "test"}',
            tokens_used=10, prompt_tokens=5, completion_tokens=5,
        )


SAMPLE_WORKFLOW = {
    "name": "Test Pipeline",
    "description": "A test workflow",
    "domain_pack": "labos",
    "nodes": [
        {
            "id": "n1",
            "role": "researcher",
            "display_name": "Researcher",
            "config": {"model": "gpt-4o-mini"},
        },
        {
            "id": "n2",
            "role": "writer",
            "display_name": "Writer",
            "config": {"model": "gpt-4o-mini"},
        },
    ],
    "edges": [{"source": "n1", "target": "n2"}],
}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    registry = DomainRegistry()
    register_builtin_packs(registry)
    sm = SettingsManager(str(tmp_path / "config"))
    app = create_app(
        lm_provider=_MockProvider(),
        domain_registry=registry,
        settings_manager=sm,
    )
    return TestClient(app)


@pytest.mark.integration
class TestWorkflowCRUD:
    def test_save_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Pipeline"
        assert data["node_count"] == 2
        assert data["edge_count"] == 1

    def test_list_workflows(self, client: TestClient) -> None:
        # Save one
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        assert resp.status_code == 201

        # List
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        workflows = resp.json()
        assert len(workflows) >= 1
        assert any(w["name"] == "Test Pipeline" for w in workflows)

    def test_get_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Pipeline"
        assert len(data["nodes"]) == 2

    def test_get_nonexistent_404(self, client: TestClient) -> None:
        resp = client.get("/api/workflows/nonexistent-id")
        assert resp.status_code == 404

    def test_update_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        updated = dict(SAMPLE_WORKFLOW)
        updated["name"] = "Updated Pipeline"
        resp = client.put(f"/api/workflows/{wf_id}", json=updated)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Pipeline"

    def test_delete_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        resp = client.delete(f"/api/workflows/{wf_id}")
        assert resp.status_code == 204

        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 404

    def test_clone_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/clone")
        assert resp.status_code == 200
        cloned = resp.json()
        assert cloned["id"] != wf_id
        assert cloned["name"] == "Test Pipeline (copy)"
        assert cloned["template_source"] == wf_id


@pytest.mark.integration
class TestWorkflowValidation:
    def test_validate_valid_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_validate_nonexistent_404(self, client: TestClient) -> None:
        resp = client.post("/api/workflows/nonexistent/validate")
        assert resp.status_code == 404


@pytest.mark.integration
class TestWorkflowRun:
    def test_run_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/workflows", json=SAMPLE_WORKFLOW)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/run", json={
            "task_description": "Test run",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["state"] == "RUNNING"

    def test_run_nonexistent_404(self, client: TestClient) -> None:
        resp = client.post("/api/workflows/nonexistent/run", json={})
        assert resp.status_code == 404
