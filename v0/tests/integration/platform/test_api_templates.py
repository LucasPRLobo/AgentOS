"""Integration tests for template API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentplatform.server import create_app
from agentplatform.settings import SettingsManager


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """Create a test client with temp directories."""
    settings_file = tmp_path / "settings.json"
    sm = SettingsManager(str(settings_file))
    sm.update({"workflows_dir": str(tmp_path / "workflows")})
    app = create_app(settings_manager=sm)
    return TestClient(app)


class TestListTemplates:
    def test_list_all(self, client: TestClient) -> None:
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 8  # 8 built-in templates

    def test_list_filter_by_domain_pack(self, client: TestClient) -> None:
        resp = client.get("/api/templates?domain_pack=codeos")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 8  # All templates use codeos domain

    def test_list_filter_no_match(self, client: TestClient) -> None:
        resp = client.get("/api/templates?domain_pack=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 0

    def test_template_summary_shape(self, client: TestClient) -> None:
        resp = client.get("/api/templates")
        tpl = resp.json()[0]
        assert "id" in tpl
        assert "name" in tpl
        assert "description" in tpl
        assert "category" in tpl
        assert "agent_count" in tpl
        assert "estimated_cost" in tpl


class TestGetTemplate:
    def test_get_existing(self, client: TestClient) -> None:
        resp = client.get("/api/templates/tpl_research_report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Research Report"
        assert len(data["nodes"]) == 4

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/templates/tpl_nonexistent")
        assert resp.status_code == 404


class TestInstantiateTemplate:
    def test_instantiate_creates_workflow(self, client: TestClient) -> None:
        resp = client.post("/api/templates/tpl_file_organizer/instantiate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_source"] == "tpl_file_organizer"
        assert "from template" in data["name"]
        assert data["node_count"] == 3

        # Verify the workflow was saved and can be loaded
        wf_id = data["id"]
        resp2 = client.get(f"/api/workflows/{wf_id}")
        assert resp2.status_code == 200

    def test_instantiate_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/templates/tpl_nonexistent/instantiate")
        assert resp.status_code == 404
