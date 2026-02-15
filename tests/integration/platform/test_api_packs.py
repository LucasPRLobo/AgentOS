"""Integration tests for domain pack API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentplatform.server import create_app


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.mark.integration
class TestListPacks:
    def test_returns_builtin_packs(self, client: TestClient) -> None:
        resp = client.get("/api/packs")
        assert resp.status_code == 200
        data = resp.json()
        names = {p["name"] for p in data}
        assert "labos" in names
        assert "codeos" in names

    def test_pack_summary_fields(self, client: TestClient) -> None:
        resp = client.get("/api/packs")
        data = resp.json()
        labos = next(p for p in data if p["name"] == "labos")
        assert labos["display_name"] == "Lab Research OS"
        assert labos["tool_count"] == 18  # 4 domain + 14 platform tools
        assert labos["role_count"] == 5
        assert labos["workflow_count"] == 2


@pytest.mark.integration
class TestGetPack:
    def test_labos_details(self, client: TestClient) -> None:
        resp = client.get("/api/packs/labos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "labos"
        assert len(data["tools"]) == 18  # 4 domain + 14 platform tools
        assert len(data["role_templates"]) == 5
        tool_names = {t["name"] for t in data["tools"]}
        assert "dataset_loader" in tool_names

    def test_codeos_details(self, client: TestClient) -> None:
        resp = client.get("/api/packs/codeos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "codeos"
        assert len(data["tools"]) == 21  # 7 domain + 14 platform tools

    def test_unknown_pack_404(self, client: TestClient) -> None:
        resp = client.get("/api/packs/nonexistent")
        assert resp.status_code == 404


@pytest.mark.integration
class TestGetPackRoles:
    def test_labos_roles(self, client: TestClient) -> None:
        resp = client.get("/api/packs/labos/roles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 5
        role_names = {r["name"] for r in data}
        assert "planner" in role_names
        assert "reviewer" in role_names

    def test_unknown_pack_404(self, client: TestClient) -> None:
        resp = client.get("/api/packs/unknown/roles")
        assert resp.status_code == 404
