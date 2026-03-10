"""Tests for the dashboard gate resolution API."""

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from agentos.dashboard.app import create_app
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_gate.db")


@pytest.fixture
def event_log(db_path):
    return SQLiteEventLog(db_path)


@pytest.fixture
def client(db_path):
    app = create_app(db_path)
    return TestClient(app)


class TestGateResolutionAPI:
    """Tests for POST /api/workflows/{wf_id}/gates/{gate_id}/resolve."""

    def test_resolve_gate_endpoint_exists(self, client, event_log):
        """Ensure the endpoint responds (even if gate doesn't exist)."""
        # Create a workflow first
        seq = SeqCounter()
        wf_id = "test-wf-gate"
        event_log.append(Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=wf_id,
            seq=seq.next(),
            payload={"workflow_name": "Test", "task_count": 1},
        ))

        # Try to resolve a non-existent gate — should get 400 or handled gracefully
        resp = client.post(
            f"/api/workflows/{wf_id}/gates/fake-gate/resolve",
            json={"resolution": "approved"},
        )
        # May be 200 or 400 depending on GateManager behavior
        assert resp.status_code in (200, 400)

    def test_run_endpoints_exist(self, client):
        """Test that run management endpoints exist."""
        resp = client.get("/api/run")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_generate_endpoint_requires_description(self, client):
        """Test that generate endpoint rejects empty description."""
        resp = client.post("/api/builder/generate", json={})
        assert resp.status_code == 400

    def test_start_run_requires_yaml(self, client):
        """Test that start run rejects missing yaml."""
        resp = client.post("/api/run", json={})
        assert resp.status_code == 400
