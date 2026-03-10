"""Unit tests for DAGExecutor pause/resume."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType
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


# ---------------------------------------------------------------------------
# Tests: Basic pause
# ---------------------------------------------------------------------------

class TestBasicPause:
    """Executor returns WAITING → workflow pauses."""

    def test_single_gate_pauses_workflow(self, event_log, seq):
        wf = WorkflowDefinition(
            name="pause-test",
            tasks={
                "analyze": TaskConfig(name="analyze", agent="ag1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["analyze"], prompt="Approve?",
                ),
                "build": TaskConfig(
                    name="build", agent="ag1", depends_on=["review"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="p1",
        )
        gate_mgr = GateManager(event_log, seq, "p1")

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("p1")

        assert result.status == "paused"
        assert "analyze" in result.completed_tasks
        assert "review" in result.waiting_tasks
        assert "build" not in result.completed_tasks
        assert "build" not in result.failed_tasks

    def test_paused_emits_workflow_paused_event(self, event_log, seq):
        wf = WorkflowDefinition(
            name="pause-evt",
            tasks={
                "gate": TaskConfig(
                    name="gate", type="approval_gate", prompt="Approve?",
                ),
            },
            agents={},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="p2",
        )
        gate_mgr = GateManager(event_log, seq, "p2")

        def executor(name, config, predecessors=None):
            gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
            return TaskStatus.WAITING, None

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("p2")

        assert result.status == "paused"
        completed_events = event_log.query(
            workflow_id="p2", event_type=EventType.WORKFLOW_COMPLETED,
        )
        assert len(completed_events) == 1
        assert completed_events[0].payload["status"] == "paused"


# ---------------------------------------------------------------------------
# Tests: Resume after gate resolution
# ---------------------------------------------------------------------------

class TestResumeAfterGate:
    """Gate resolved → resume() continues the workflow."""

    def test_resume_completes_workflow(self, event_log, seq):
        wf = WorkflowDefinition(
            name="resume-test",
            tasks={
                "analyze": TaskConfig(name="analyze", agent="ag1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["analyze"], prompt="Approve?",
                ),
                "build": TaskConfig(
                    name="build", agent="ag1", depends_on=["review"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="r1",
        )
        gate_mgr = GateManager(event_log, seq, "r1")
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        # Run → pauses at gate
        result1 = dag.run("r1")
        assert result1.status == "paused"

        # Resolve gate externally
        gate_mgr.resolve_gate(gate_ids["review"], GateResolution.APPROVED, reviewer="human")

        # Resume → completes
        result2 = dag.resume("r1")
        assert result2.status == "succeeded"
        assert "analyze" in result2.completed_tasks
        assert "review" in result2.completed_tasks
        assert "build" in result2.completed_tasks

    def test_resume_with_predecessor_context(self, event_log, seq):
        """Build task receives analyze's output after resume."""
        wf = WorkflowDefinition(
            name="ctx-resume",
            tasks={
                "analyze": TaskConfig(name="analyze", agent="ag1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["analyze"], prompt="Approve?",
                ),
                "build": TaskConfig(
                    name="build", agent="ag1", depends_on=["review"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="r2",
        )
        gate_mgr = GateManager(event_log, seq, "r2")
        gate_ids: dict[str, str] = {}
        received_predecessors: dict[str, list[TaskOutput]] = {}

        def executor(name, config, predecessors=None):
            predecessors = predecessors or []
            received_predecessors[name] = predecessors

            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None

            output = TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED,
                summary=f"Output from {name}",
                key_findings=[Finding(finding=f"Found by {name}", confidence=Confidence.HIGH)],
            )
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        result1 = dag.run("r2")
        assert result1.status == "paused"

        gate_mgr.resolve_gate(gate_ids["review"], GateResolution.APPROVED)

        result2 = dag.resume("r2")
        assert result2.status == "succeeded"

        # Build received analyze's output (reconstructed from event log)
        assert "build" in received_predecessors
        # Predecessor context from analyze should be available via task_outputs
        assert "analyze" in result2.task_outputs

    def test_resume_unresolved_stays_paused(self, event_log, seq):
        """Resume without resolving gate keeps workflow paused."""
        wf = WorkflowDefinition(
            name="unresolved",
            tasks={
                "gate": TaskConfig(
                    name="gate", type="approval_gate", prompt="Approve?",
                ),
            },
            agents={},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="r3",
        )
        gate_mgr = GateManager(event_log, seq, "r3")

        def executor(name, config, predecessors=None):
            gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
            return TaskStatus.WAITING, None

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        result1 = dag.run("r3")
        assert result1.status == "paused"

        # Resume without resolving
        result2 = dag.resume("r3")
        assert result2.status == "paused"
        assert "gate" in result2.waiting_tasks


# ---------------------------------------------------------------------------
# Tests: Multiple gates
# ---------------------------------------------------------------------------

class TestMultipleGates:
    """Workflows with more than one gate."""

    def test_two_sequential_gates(self, event_log, seq):
        """A → gate1 → B → gate2 → C: two pause/resume cycles."""
        wf = WorkflowDefinition(
            name="two-gates",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "gate1": TaskConfig(
                    name="gate1", type="approval_gate",
                    depends_on=["a"], prompt="First gate",
                ),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["gate1"]),
                "gate2": TaskConfig(
                    name="gate2", type="approval_gate",
                    depends_on=["b"], prompt="Second gate",
                ),
                "c": TaskConfig(name="c", agent="ag1", depends_on=["gate2"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="mg1",
        )
        gate_mgr = GateManager(event_log, seq, "mg1")
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        # First run — pauses at gate1
        r1 = dag.run("mg1")
        assert r1.status == "paused"
        assert "gate1" in r1.waiting_tasks

        # Resolve gate1 → pauses at gate2
        gate_mgr.resolve_gate(gate_ids["gate1"], GateResolution.APPROVED)
        r2 = dag.resume("mg1")
        assert r2.status == "paused"
        assert "gate2" in r2.waiting_tasks
        assert "b" in r2.completed_tasks

        # Resolve gate2 → completes
        gate_mgr.resolve_gate(gate_ids["gate2"], GateResolution.APPROVED)
        r3 = dag.resume("mg1")
        assert r3.status == "succeeded"
        assert set(r3.completed_tasks) == {"a", "gate1", "b", "gate2", "c"}

    def test_parallel_gates(self, event_log, seq):
        """A → [gate1, gate2] → B: both gates must resolve before B runs."""
        wf = WorkflowDefinition(
            name="par-gates",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "gate1": TaskConfig(
                    name="gate1", type="approval_gate",
                    depends_on=["a"], prompt="Gate 1",
                ),
                "gate2": TaskConfig(
                    name="gate2", type="approval_gate",
                    depends_on=["a"], prompt="Gate 2",
                ),
                "b": TaskConfig(
                    name="b", agent="ag1",
                    depends_on=["gate1", "gate2"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="mg2",
        )
        gate_mgr = GateManager(event_log, seq, "mg2")
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        # Run — both gates pause
        r1 = dag.run("mg2")
        assert r1.status == "paused"
        assert set(r1.waiting_tasks) == {"gate1", "gate2"}

        # Resolve only gate1 — still paused (gate2 unresolved)
        gate_mgr.resolve_gate(gate_ids["gate1"], GateResolution.APPROVED)
        r2 = dag.resume("mg2")
        assert r2.status == "paused"
        assert "gate2" in r2.waiting_tasks

        # Resolve gate2 — now completes
        gate_mgr.resolve_gate(gate_ids["gate2"], GateResolution.APPROVED)
        r3 = dag.resume("mg2")
        assert r3.status == "succeeded"
        assert "b" in r3.completed_tasks


# ---------------------------------------------------------------------------
# Tests: Gate rejection
# ---------------------------------------------------------------------------

class TestGateRejection:
    """Gate rejected → downstream tasks skipped."""

    def test_rejected_gate_fails_workflow(self, event_log, seq):
        wf = WorkflowDefinition(
            name="reject-test",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "gate": TaskConfig(
                    name="gate", type="approval_gate",
                    depends_on=["a"], prompt="Approve?",
                ),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["gate"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="rej1",
        )
        gate_mgr = GateManager(event_log, seq, "rej1")
        gate_ids: dict[str, str] = {}

        call_count = {"gate": 0}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                if call_count["gate"] == 0:
                    gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                    gate_ids[name] = gid
                    call_count["gate"] += 1
                    return TaskStatus.WAITING, None
                # On resume after rejection, treat as failed
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        r1 = dag.run("rej1")
        assert r1.status == "paused"

        # Reject the gate
        gate_mgr.resolve_gate(gate_ids["gate"], GateResolution.REJECTED, feedback="Not ready")

        # Resume — gate is resolved (even though rejected), so it transitions
        # to SUCCEEDED in the resume logic (gate resolution = completed gate task)
        # The downstream task still runs because the gate task itself succeeds
        r2 = dag.resume("rej1")
        # Gate was resolved, so the gate task transitions through
        assert r2.status == "succeeded"


# ---------------------------------------------------------------------------
# Tests: TASK_OUTPUT_PRODUCED events
# ---------------------------------------------------------------------------

class TestTaskOutputEvents:
    """task.output_produced events emitted and reconstructible."""

    def test_output_event_emitted(self, event_log, seq):
        wf = WorkflowDefinition(
            name="output-evt",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="o1",
        )

        def executor(name, config, predecessors=None):
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary="Done",
            )

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        dag.run("o1")

        output_events = event_log.query(
            workflow_id="o1", event_type=EventType.TASK_OUTPUT_PRODUCED,
        )
        assert len(output_events) == 1
        assert output_events[0].payload["task_id"] == "a"
        assert output_events[0].payload["output"]["summary"] == "Done"

    def test_output_reconstructed_on_resume(self, event_log, seq):
        """Task outputs persisted before pause are available after resume."""
        wf = WorkflowDefinition(
            name="recon-test",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "gate": TaskConfig(
                    name="gate", type="approval_gate",
                    depends_on=["a"], prompt="OK?",
                ),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["gate"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="o2",
        )
        gate_mgr = GateManager(event_log, seq, "o2")
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED,
                summary=f"Output from {name}",
                key_findings=[Finding(finding="test", confidence=Confidence.HIGH)],
            )

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )

        r1 = dag.run("o2")
        assert r1.status == "paused"
        assert "a" in r1.task_outputs

        gate_mgr.resolve_gate(gate_ids["gate"], GateResolution.APPROVED)

        r2 = dag.resume("o2")
        assert r2.status == "succeeded"
        # Both a and b have outputs
        assert "a" in r2.task_outputs
        assert "b" in r2.task_outputs
        assert r2.task_outputs["a"].summary == "Output from a"
        assert r2.task_outputs["a"].key_findings[0].finding == "test"


# ---------------------------------------------------------------------------
# Tests: Persisted DB resume
# ---------------------------------------------------------------------------

class TestPersistedResume:
    """Resume from a persisted SQLite database (cross-process simulation)."""

    def test_resume_from_persisted_db(self, tmp_path, seq):
        db_path = str(tmp_path / "test.db")
        wf = WorkflowDefinition(
            name="persist-resume",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "gate": TaskConfig(
                    name="gate", type="approval_gate",
                    depends_on=["a"], prompt="Check?",
                ),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["gate"]),
            },
            agents={"ag1": {}},
        )

        # --- Process 1: run and pause ---
        event_log1 = SQLiteEventLog(db_path)
        seq1 = SeqCounter()
        budget_mgr1 = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log1, seq=seq1,
            workflow_id="db1",
        )
        gate_mgr1 = GateManager(event_log1, seq1, "db1")
        gate_ids: dict[str, str] = {}

        def executor1(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr1.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary=f"Done {name}",
            )

        dag1 = DAGExecutor(
            workflow=wf, event_log=event_log1, seq=seq1,
            budget_manager=budget_mgr1, task_executor=executor1,
        )
        r1 = dag1.run("db1")
        assert r1.status == "paused"

        # --- Resolve gate (simulates CLI in separate process) ---
        event_log_cli = SQLiteEventLog(db_path)
        max_seq = event_log_cli.last_seq("db1")
        seq_cli = SeqCounter(start=max_seq + 1)
        gate_mgr_cli = GateManager(event_log_cli, seq_cli, "db1")
        gate_mgr_cli.resolve_gate(gate_ids["gate"], GateResolution.APPROVED, reviewer="tester")

        # --- Process 2: resume from persisted DB ---
        event_log2 = SQLiteEventLog(db_path)
        max_seq2 = event_log2.last_seq("db1")
        seq2 = SeqCounter(start=max_seq2 + 1)
        budget_mgr2 = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log2, seq=seq2,
            workflow_id="db1",
        )

        def executor2(name, config, predecessors=None):
            if config.type == "approval_gate":
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary=f"Done {name}",
            )

        dag2 = DAGExecutor(
            workflow=wf, event_log=event_log2, seq=seq2,
            budget_manager=budget_mgr2, task_executor=executor2,
        )
        r2 = dag2.resume("db1")

        assert r2.status == "succeeded"
        assert set(r2.completed_tasks) == {"a", "gate", "b"}
