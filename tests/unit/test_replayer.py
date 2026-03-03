"""Tests for WorkflowReplayer — deterministic state reconstruction from events."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.lifecycle import (
    AgentLifecycleManager,
    TerminationReason,
)
from agentos.kernel.replayer import WorkflowReplayer, WorkflowSnapshot
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


@pytest.fixture
def replayer(event_log):
    return WorkflowReplayer(event_log)


def _run_simple_workflow(event_log, seq, workflow_id="replay-test"):
    """Helper: run a 2-task linear workflow returning the workflow_id."""
    wf = WorkflowDefinition(
        name="replay-demo",
        tasks={
            "research": TaskConfig(name="research", agent="ag1"),
            "write": TaskConfig(name="write", agent="ag2", depends_on=["research"]),
        },
        agents={"ag1": {}, "ag2": {}},
    )
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget, event_log=event_log, seq=seq,
        workflow_id=workflow_id,
    )

    def executor(name, config, predecessors=None):
        budget_mgr.apply(config.agent, BudgetDelta(
            tokens=200, api_calls=1, cost_usd=0.01,
        ))
        output = TaskOutput(
            task_id=name, agent_id=config.agent,
            status=TaskStatus.SUCCEEDED,
            summary=f"Completed {name}",
            key_findings=[Finding(
                finding=f"Finding from {name}",
                confidence=Confidence.HIGH,
            )],
        )
        return TaskStatus.SUCCEEDED, output

    dag = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=executor,
    )
    return dag.run(workflow_id)


# ---------------------------------------------------------------------------
# Tests: Empty / missing workflow
# ---------------------------------------------------------------------------

class TestEmptyReplay:

    def test_no_events_returns_empty_snapshot(self, replayer):
        snap = replayer.replay("nonexistent")
        assert snap.event_count == 0
        assert snap.workflow_id == "nonexistent"
        assert snap.status == ""

    def test_workflow_id_preserved(self, replayer):
        snap = replayer.replay("my-workflow-123")
        assert snap.workflow_id == "my-workflow-123"


# ---------------------------------------------------------------------------
# Tests: Task state reconstruction
# ---------------------------------------------------------------------------

class TestTaskStateReconstruction:

    def test_tasks_reconstructed(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert "research" in snap.tasks
        assert "write" in snap.tasks
        assert snap.tasks["research"].state == TaskStatus.SUCCEEDED
        assert snap.tasks["write"].state == TaskStatus.SUCCEEDED

    def test_succeeded_tasks_property(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert set(snap.succeeded_tasks) == {"research", "write"}
        assert snap.failed_tasks == []
        assert snap.waiting_tasks == []

    def test_task_transitions_tracked(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        research = snap.tasks["research"]
        # PENDING → RUNNING, RUNNING → SUCCEEDED
        assert len(research.transitions) == 2
        assert research.transitions[0][0] == "pending"
        assert research.transitions[0][1] == "running"
        assert research.transitions[1][0] == "running"
        assert research.transitions[1][1] == "succeeded"


# ---------------------------------------------------------------------------
# Tests: Task output reconstruction
# ---------------------------------------------------------------------------

class TestTaskOutputReconstruction:

    def test_outputs_reconstructed(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        research = snap.tasks["research"]
        assert research.output is not None
        assert research.output.summary == "Completed research"
        assert len(research.output.key_findings) == 1

    def test_output_agent_id(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.tasks["research"].output.agent_id == "ag1"
        assert snap.tasks["write"].output.agent_id == "ag2"


# ---------------------------------------------------------------------------
# Tests: Workflow metadata
# ---------------------------------------------------------------------------

class TestWorkflowMetadata:

    def test_workflow_name(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.workflow_name == "replay-demo"

    def test_workflow_status(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.status == "succeeded"

    def test_task_count(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.task_count == 2

    def test_timestamps(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.started_at is not None
        assert snap.completed_at is not None

    def test_event_count(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.event_count > 0
        assert len(snap.events) == snap.event_count


# ---------------------------------------------------------------------------
# Tests: Budget reconstruction
# ---------------------------------------------------------------------------

class TestBudgetReconstruction:

    def test_budget_per_agent(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert "ag1" in snap.budgets
        assert "ag2" in snap.budgets
        assert snap.budgets["ag1"].usage.tokens_used == 200
        assert snap.budgets["ag2"].usage.tokens_used == 200

    def test_total_tokens(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.total_tokens == 400

    def test_total_cost(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq)
        snap = replayer.replay("replay-test")

        assert snap.total_cost == pytest.approx(0.02)

    def test_budget_exceeded_flag(self, event_log, seq, replayer):
        """Manually emit a budget exceeded event and verify replay."""
        event_log.append(Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="bx",
            seq=seq.next(),
            payload={"workflow_name": "bx-test", "task_count": 1},
        ))
        event_log.append(Event(
            event_type=EventType.BUDGET_EXCEEDED,
            workflow_id="bx",
            seq=seq.next(),
            payload={
                "agent_id": "ag1",
                "resource": "tokens",
                "limit": 1000,
                "attempted": 1500,
            },
        ))
        snap = replayer.replay("bx")
        assert snap.budgets["ag1"].exceeded is True
        assert snap.budgets["ag1"].exceeded_resource == "tokens"


# ---------------------------------------------------------------------------
# Tests: Agent reconstruction
# ---------------------------------------------------------------------------

class TestAgentReconstruction:

    def test_agent_spawned_and_terminated(self, event_log, seq, replayer):
        lm = AgentLifecycleManager(event_log, seq, "agent-test")
        # Also need a workflow.started event
        event_log.append(Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="agent-test",
            seq=seq.next(),
            payload={"workflow_name": "agent-test", "task_count": 0},
        ))
        lm.spawn("ag1", agent_name="researcher", adapter_tier=1)
        lm.stop("ag1", reason=TerminationReason.COMPLETED)

        snap = replayer.replay("agent-test")
        assert "ag1" in snap.agents
        agent = snap.agents["ag1"]
        assert agent.agent_name == "researcher"
        assert agent.adapter_tier == 1
        assert agent.termination_reason == "completed"
        assert agent.spawned_at is not None
        assert agent.terminated_at is not None


# ---------------------------------------------------------------------------
# Tests: Gate reconstruction
# ---------------------------------------------------------------------------

class TestGateReconstruction:

    def test_gate_waiting_and_resolved(self, event_log, seq, replayer):
        event_log.append(Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="gate-test",
            seq=seq.next(),
            payload={"workflow_name": "gate-test", "task_count": 1},
        ))
        event_log.append(Event(
            event_type=EventType.GATE_WAITING,
            workflow_id="gate-test",
            seq=seq.next(),
            payload={
                "gate_id": "g1",
                "task_id": "review",
                "gate_type": "approval",
            },
        ))
        event_log.append(Event(
            event_type=EventType.GATE_RESOLVED,
            workflow_id="gate-test",
            seq=seq.next(),
            payload={
                "gate_id": "g1",
                "resolution": "approved",
                "reviewer": "admin",
            },
        ))

        snap = replayer.replay("gate-test")
        assert "g1" in snap.gates
        gate = snap.gates["g1"]
        assert gate.task_id == "review"
        assert gate.gate_type == "approval"
        assert gate.resolution == "approved"
        assert gate.resolved_by == "admin"

    def test_pending_gate(self, event_log, seq, replayer):
        event_log.append(Event(
            event_type=EventType.GATE_WAITING,
            workflow_id="gate-pend",
            seq=seq.next(),
            payload={"gate_id": "g2", "task_id": "review", "gate_type": "approval"},
        ))
        snap = replayer.replay("gate-pend")
        assert snap.gates["g2"].resolution == ""


# ---------------------------------------------------------------------------
# Tests: Failed workflow reconstruction
# ---------------------------------------------------------------------------

class TestFailedWorkflow:

    def test_failed_task_state(self, event_log, seq, replayer):
        wf = WorkflowDefinition(
            name="fail-demo",
            tasks={
                "bad": TaskConfig(name="bad", agent="ag1"),
                "after": TaskConfig(name="after", agent="ag1", depends_on=["bad"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="fail-test",
        )

        def executor(name, config, predecessors=None):
            if name == "bad":
                raise RuntimeError("oops")
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        dag.run("fail-test")

        snap = replayer.replay("fail-test")
        assert snap.status == "failed"
        assert "bad" in snap.failed_tasks

    def test_inferred_status_when_no_completion_event(self, event_log, seq, replayer):
        """If only task state changes exist with no workflow.completed, infer status."""
        event_log.append(Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id="partial",
            seq=seq.next(),
            payload={"task_id": "t1", "from_state": "pending", "to_state": "running"},
        ))
        snap = replayer.replay("partial")
        assert snap.status == "running"


# ---------------------------------------------------------------------------
# Tests: Error events
# ---------------------------------------------------------------------------

class TestErrorReconstruction:

    def test_error_events_collected(self, event_log, seq, replayer):
        event_log.append(Event(
            event_type=EventType.ERROR_OCCURRED,
            workflow_id="err-test",
            seq=seq.next(),
            payload={"message": "Something went wrong", "task_id": "t1"},
        ))
        snap = replayer.replay("err-test")
        assert len(snap.errors) == 1
        assert snap.errors[0]["message"] == "Something went wrong"


# ---------------------------------------------------------------------------
# Tests: Workflow isolation
# ---------------------------------------------------------------------------

class TestWorkflowIsolation:

    def test_separate_workflows(self, event_log, seq, replayer):
        _run_simple_workflow(event_log, seq, workflow_id="wf-a")
        _run_simple_workflow(event_log, seq, workflow_id="wf-b")

        snap_a = replayer.replay("wf-a")
        snap_b = replayer.replay("wf-b")

        assert snap_a.workflow_id == "wf-a"
        assert snap_b.workflow_id == "wf-b"
        assert snap_a.workflow_name == "replay-demo"
        assert snap_b.workflow_name == "replay-demo"
        # Each has its own task set
        assert snap_a.event_count > 0
        assert snap_b.event_count > 0
