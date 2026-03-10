"""End-to-end tests for the dashboard — seed DB, hit all endpoints, verify data."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import Event, EventType
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig

try:
    from fastapi.testclient import TestClient
    from agentos.dashboard.app import create_app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_demo_workflow(db_path: str) -> str:
    """Run a simple workflow and return the workflow_id."""
    import yaml

    wf_yaml = {
        "name": "e2e-dashboard-test",
        "version": "1.0",
        "budget": {"max_tokens": 50000, "max_cost_usd": 5.0},
        "agents": {
            "researcher": {"adapter": "tier1", "role": "Research agent"},
            "coder": {"adapter": "tier1", "role": "Coding agent"},
        },
        "tasks": {
            "research": {
                "name": "research",
                "agent": "researcher",
                "description": "Research the topic.",
            },
            "review_gate": {
                "name": "review_gate",
                "type": "approval_gate",
                "depends_on": ["research"],
                "prompt": "Approve research findings?",
            },
            "implement": {
                "name": "implement",
                "agent": "coder",
                "description": "Implement based on research.",
                "depends_on": ["review_gate"],
            },
        },
    }

    wf = WorkflowDefinition.model_validate(wf_yaml)
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()
    workflow_id = f"e2e-{uuid.uuid4().hex[:8]}"

    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget, event_log=event_log,
        seq=seq, workflow_id=workflow_id, agent_specs=agent_specs,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    def task_executor(task_name, config, predecessors=None):
        predecessors = predecessors or []
        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="e2e")
            output = TaskOutput(
                task_id=task_name, agent_id="gate",
                status=TaskStatus.SUCCEEDED, summary="Auto-approved.",
            )
            return TaskStatus.SUCCEEDED, output

        agent_id = config.agent or "unassigned"
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500, api_calls=1, time_seconds=0.1, cost_usd=0.01,
        ))
        output = TaskOutput(
            task_id=task_name, agent_id=agent_id,
            status=TaskStatus.SUCCEEDED, summary=f"Completed {task_name}",
        )
        return TaskStatus.SUCCEEDED, output

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
    )
    result = executor.run(workflow_id)
    assert result.status == "succeeded"
    return workflow_id


@pytest.fixture
def e2e_app(tmp_path):
    """Create an app with a fully-executed workflow."""
    db_path = str(tmp_path / "e2e.db")
    workflow_id = _run_demo_workflow(db_path)
    app = create_app(db_path)
    return TestClient(app), workflow_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDashboardE2E:
    def test_workflow_list_has_entry(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        ids = [w["workflow_id"] for w in data]
        assert wf_id in ids

    def test_workflow_detail_matches(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf_id
        assert data["status"] == "succeeded"
        assert "research" in data["tasks"]
        assert "implement" in data["tasks"]

    def test_events_complete(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get(f"/api/workflows/{wf_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        types = [e["event_type"] for e in data["events"]]
        assert "workflow.started" in types
        assert "workflow.completed" in types
        assert "task.state_changed" in types

    def test_budget_matches_execution(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get(f"/api/workflows/{wf_id}/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"]["tokens"] > 0
        assert data["total"]["cost"] > 0

    def test_gates_resolved(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get(f"/api/workflows/{wf_id}/gates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["resolution"] == "approved"
        assert data[0]["pending"] is False

    def test_websocket_streaming(self, e2e_app):
        client, wf_id = e2e_app
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "workflow_id": wf_id, "since_seq": 0})
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["data"]["status"] == "succeeded"

    def test_event_filtering_by_type(self, e2e_app):
        client, wf_id = e2e_app
        resp = client.get(f"/api/workflows/{wf_id}/events?type=gate.resolved")
        assert resp.status_code == 200
        data = resp.json()
        for e in data["events"]:
            assert e["event_type"] == "gate.resolved"
