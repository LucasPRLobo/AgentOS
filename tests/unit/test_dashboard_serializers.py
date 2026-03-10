"""Tests for agentos.dashboard.serializers."""

from __future__ import annotations

from datetime import UTC, datetime

from agentos.dashboard.serializers import (
    budget_snapshot_to_dict,
    event_to_dict,
    gate_snapshot_to_dict,
    snapshot_to_dict,
    snapshot_to_summary,
    task_snapshot_to_dict,
)
from agentos.kernel.replayer import (
    AgentSnapshot,
    BudgetSnapshot,
    GateSnapshot,
    TaskSnapshot,
    WorkflowSnapshot,
)
from agentos.schemas.budget import BudgetUsage
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskOutput, TaskStatus


class TestEventToDict:
    def test_basic_event(self):
        event = Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-1",
            seq=0,
            payload={"workflow_name": "test"},
        )
        d = event_to_dict(event)
        assert d["event_type"] == "workflow.started"
        assert d["workflow_id"] == "wf-1"
        assert d["seq"] == 0
        assert d["payload"]["workflow_name"] == "test"
        assert "timestamp" in d


class TestTaskSnapshotToDict:
    def test_basic_task(self):
        task = TaskSnapshot(name="task1", state=TaskStatus.SUCCEEDED, agent_id="a1")
        d = task_snapshot_to_dict(task)
        assert d["name"] == "task1"
        assert d["state"] == "succeeded"
        assert d["agent_id"] == "a1"

    def test_task_with_output(self):
        task = TaskSnapshot(
            name="task1",
            state=TaskStatus.SUCCEEDED,
            agent_id="a1",
            output=TaskOutput(
                task_id="task1", agent_id="a1",
                status=TaskStatus.SUCCEEDED, summary="Done.",
            ),
        )
        d = task_snapshot_to_dict(task)
        assert "output" in d
        assert d["output"]["summary"] == "Done."


class TestGateSnapshotToDict:
    def test_pending_gate(self):
        gate = GateSnapshot(gate_id="g1", task_id="t1", gate_type="approval")
        d = gate_snapshot_to_dict(gate)
        assert d["pending"] is True
        assert d["resolution"] == ""

    def test_resolved_gate(self):
        gate = GateSnapshot(gate_id="g1", task_id="t1", gate_type="approval", resolution="approved")
        d = gate_snapshot_to_dict(gate)
        assert d["pending"] is False
        assert d["resolution"] == "approved"


class TestBudgetSnapshotToDict:
    def test_basic_budget(self):
        budget = BudgetSnapshot(
            agent_id="a1",
            usage=BudgetUsage(tokens_used=1000, cost_usd=0.05),
        )
        d = budget_snapshot_to_dict(budget)
        assert d["agent_id"] == "a1"
        assert d["usage"]["tokens_used"] == 1000
        assert d["exceeded"] is False


class TestSnapshotToDict:
    def test_full_snapshot(self):
        snap = WorkflowSnapshot(
            workflow_id="wf-1",
            workflow_name="test",
            status="succeeded",
            task_count=2,
        )
        snap.tasks["t1"] = TaskSnapshot(name="t1", state=TaskStatus.SUCCEEDED)
        d = snapshot_to_dict(snap)
        assert d["workflow_id"] == "wf-1"
        assert d["status"] == "succeeded"
        assert "t1" in d["tasks"]

    def test_snapshot_to_summary(self):
        snap = WorkflowSnapshot(
            workflow_id="wf-1",
            workflow_name="test",
            status="succeeded",
            task_count=3,
            event_count=10,
        )
        d = snapshot_to_summary(snap)
        assert d["workflow_id"] == "wf-1"
        assert d["name"] == "test"
        assert d["task_count"] == 3
        assert d["event_count"] == 10
