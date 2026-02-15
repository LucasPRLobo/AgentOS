"""Integration tests for the integrations API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentplatform.server import create_app
from agentplatform.settings import SettingsManager


@pytest.fixture()
def client(tmp_path) -> TestClient:
    sm = SettingsManager(str(tmp_path / "config"))
    app = create_app(settings_manager=sm)
    return TestClient(app)


@pytest.mark.integration
class TestListIntegrations:
    def test_lists_all_integrations(self, client: TestClient) -> None:
        resp = client.get("/api/integrations")
        assert resp.status_code == 200
        data = resp.json()
        names = {i["name"] for i in data}
        assert "google" in names
        assert "slack" in names

    def test_initially_disconnected(self, client: TestClient) -> None:
        resp = client.get("/api/integrations")
        data = resp.json()
        for integration in data:
            assert integration["connected"] is False


@pytest.mark.integration
class TestSlackConnect:
    def test_connect_slack(self, client: TestClient) -> None:
        resp = client.post(
            "/api/integrations/slack/connect",
            json={"bot_token": "xoxb-test-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "slack"
        assert data["connected"] is True

        # Verify it shows connected now
        resp = client.get("/api/integrations")
        slack = next(i for i in resp.json() if i["name"] == "slack")
        assert slack["connected"] is True


@pytest.mark.integration
class TestDisconnectIntegration:
    def test_disconnect_slack(self, client: TestClient) -> None:
        # First connect
        client.post("/api/integrations/slack/connect", json={"bot_token": "xoxb-test"})

        # Disconnect
        resp = client.delete("/api/integrations/slack/disconnect")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disconnected"

        # Verify disconnected
        resp = client.get("/api/integrations")
        slack = next(i for i in resp.json() if i["name"] == "slack")
        assert slack["connected"] is False

    def test_disconnect_unknown_404(self, client: TestClient) -> None:
        resp = client.delete("/api/integrations/unknown/disconnect")
        assert resp.status_code == 404
