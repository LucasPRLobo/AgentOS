"""Tests for agentos.dashboard.app — REST API endpoints."""

from __future__ import annotations

import json

import pytest

from agentos.dashboard.app import create_app
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import Event, EventType

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_workflow(db_path: str, workflow_id: str = "wf-test-01") -> SQLiteEventLog:
    """Seed a database with a complete workflow for testing."""
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()

    events = [
        Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"workflow_name": "test-workflow", "task_count": 2},
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task_a", "from_state": "pending", "to_state": "running", "agent_id": "agent1"},
        ),
        Event(
            event_type=EventType.BUDGET_CONSUMED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={
                "agent_id": "agent1",
                "delta": {"tokens": 500, "api_calls": 1, "time_seconds": 1.0, "cost_usd": 0.01},
                "cumulative": {"tokens_used": 500, "api_calls_made": 1, "time_elapsed_seconds": 1.0, "cost_usd": 0.01},
            },
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task_a", "from_state": "running", "to_state": "succeeded", "agent_id": "agent1"},
        ),
        Event(
            event_type=EventType.GATE_WAITING,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"gate_id": "gate-1", "task_id": "review_gate", "gate_type": "approval"},
        ),
        Event(
            event_type=EventType.GATE_RESOLVED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"gate_id": "gate-1", "resolution": "approved", "reviewer": "human"},
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task_b", "from_state": "pending", "to_state": "running", "agent_id": "agent1"},
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task_b", "from_state": "running", "to_state": "succeeded", "agent_id": "agent1"},
        ),
        Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"status": "succeeded"},
        ),
    ]

    for event in events:
        event_log.append(event)

    return event_log


@pytest.fixture
def seeded_app(tmp_path):
    """Create a seeded app with a test workflow."""
    db_path = str(tmp_path / "test.db")
    _seed_workflow(db_path)
    app = create_app(db_path)
    return TestClient(app)


@pytest.fixture
def empty_app(tmp_path):
    """Create an app with an empty database."""
    db_path = str(tmp_path / "empty.db")
    app = create_app(db_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: GET /api/workflows
# ---------------------------------------------------------------------------

class TestListWorkflows:
    def test_list_workflows(self, seeded_app):
        resp = seeded_app.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["workflow_id"] == "wf-test-01"
        assert data[0]["name"] == "test-workflow"
        assert data[0]["status"] == "succeeded"

    def test_empty_list(self, empty_app):
        resp = empty_app.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Tests: GET /api/workflows/{id}
# ---------------------------------------------------------------------------

class TestGetWorkflow:
    def test_get_existing_workflow(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "wf-test-01"
        assert data["workflow_name"] == "test-workflow"
        assert data["status"] == "succeeded"
        assert "tasks" in data
        assert "events" in data

    def test_get_nonexistent_workflow(self, seeded_app):
        resp = seeded_app.get("/api/workflows/nonexistent")
        assert resp.status_code == 404

    def test_workflow_has_tasks(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01")
        data = resp.json()
        assert "task_a" in data["tasks"]
        assert "task_b" in data["tasks"]
        assert data["tasks"]["task_a"]["state"] == "succeeded"


# ---------------------------------------------------------------------------
# Tests: GET /api/workflows/{id}/events
# ---------------------------------------------------------------------------

class TestGetEvents:
    def test_get_all_events(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert len(data["events"]) == 9
        assert "last_seq" in data

    def test_filter_by_type(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/events?type=task.state_changed")
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["event_type"] == "task.state_changed" for e in data["events"])

    def test_since_seq(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/events?since_seq=5")
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["seq"] >= 5 for e in data["events"])

    def test_limit(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/events?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3


# ---------------------------------------------------------------------------
# Tests: GET /api/workflows/{id}/budget
# ---------------------------------------------------------------------------

class TestGetBudget:
    def test_budget_data(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "total" in data
        assert data["agents"]["agent1"]["usage"]["tokens_used"] == 500

    def test_total_cost(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/budget")
        data = resp.json()
        assert data["total"]["cost"] == 0.01


# ---------------------------------------------------------------------------
# Tests: GET /api/workflows/{id}/gates
# ---------------------------------------------------------------------------

class TestGetGates:
    def test_gate_list(self, seeded_app):
        resp = seeded_app.get("/api/workflows/wf-test-01/gates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["gate_id"] == "gate-1"
        assert data[0]["resolution"] == "approved"
        assert data[0]["pending"] is False

    def test_empty_gates(self, empty_app):
        resp = empty_app.get("/api/workflows/no-wf/gates")
        assert resp.status_code == 200
        assert resp.json() == []
