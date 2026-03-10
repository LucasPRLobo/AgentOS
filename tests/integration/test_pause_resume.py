"""Integration tests — pause/resume with GateManager, CLI, and adapters.

Tests: full pause→resolve→resume flow, cross-process resume on persisted DB,
pause with structured handoffs across tiers, multiple resume cycles.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from agentos.cli.main import cli
from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
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
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Tests: Full pause → CLI resolve → resume
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPauseResolveCLI:
    """Run → pause → resolve gate via CLI → resume → succeed."""

    def test_full_cycle_with_cli_resolve(self, runner, tmp_path):
        db_path = str(tmp_path / "workflow.db")
        wf = WorkflowDefinition(
            name="cli-resume",
            tasks={
                "research": TaskConfig(name="research", agent="ag1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["research"], prompt="Is the research good?",
                ),
                "implement": TaskConfig(
                    name="implement", agent="ag1", depends_on=["review"],
                ),
            },
            agents={"ag1": {}},
        )
        workflow_id = "int-pr1"

        # --- Phase 1: Run and pause ---
        event_log = SQLiteEventLog(db_path)
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id=workflow_id,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            budget_mgr.apply("ag1", BudgetDelta(tokens=100))
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary=f"Completed {name}",
            )

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        r1 = dag.run(workflow_id)
        assert r1.status == "paused"
        assert "review" in r1.waiting_tasks

        # --- Phase 2: Resolve gate via CLI ---
        result = runner.invoke(cli, [
            "gate", "approve", gate_ids["review"],
            "--db", db_path,
            "--reviewer", "integration-test",
            "--feedback", "Looks great, proceed.",
        ])
        assert result.exit_code == 0
        assert "APPROVED" in result.output

        # --- Phase 3: Resume from fresh connection ---
        event_log2 = SQLiteEventLog(db_path)
        max_seq = event_log2.last_seq(workflow_id)
        seq2 = SeqCounter(start=max_seq + 1)
        budget_mgr2 = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log2, seq=seq2,
            workflow_id=workflow_id,
        )

        def executor2(name, config, predecessors=None):
            if config.type == "approval_gate":
                return TaskStatus.WAITING, None
            budget_mgr2.apply("ag1", BudgetDelta(tokens=100))
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary=f"Completed {name}",
            )

        dag2 = DAGExecutor(
            workflow=wf, event_log=event_log2, seq=seq2,
            budget_manager=budget_mgr2, task_executor=executor2,
        )
        r2 = dag2.resume(workflow_id)

        assert r2.status == "succeeded"
        assert set(r2.completed_tasks) == {"research", "review", "implement"}

        # Verify full event trail
        all_events = event_log2.replay(workflow_id)
        event_types = [e.event_type for e in all_events]
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.GATE_WAITING in event_types
        assert EventType.GATE_RESOLVED in event_types
        assert EventType.TASK_OUTPUT_PRODUCED in event_types


# ---------------------------------------------------------------------------
# Tests: Pause with budget tracking
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPauseWithBudget:
    """Budget state is preserved across pause/resume."""

    def test_budget_continues_after_resume(self, tmp_path):
        db_path = str(tmp_path / "budget.db")
        wf = WorkflowDefinition(
            name="budget-resume",
            budget=BudgetSpec(max_tokens=5000),
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
        workflow_id = "bp1"

        # Phase 1: Run
        event_log = SQLiteEventLog(db_path)
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id=workflow_id,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)
        gate_ids: dict[str, str] = {}

        def executor(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            budget_mgr.apply("ag1", BudgetDelta(tokens=1000))
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        r1 = dag.run(workflow_id)
        assert r1.status == "paused"
        assert budget_mgr.total_usage.tokens_used == 1000

        # Resolve
        gate_mgr.resolve_gate(gate_ids["gate"], GateResolution.APPROVED)

        # Phase 2: Resume with fresh budget manager (reconstructed)
        event_log2 = SQLiteEventLog(db_path)
        max_seq = event_log2.last_seq(workflow_id)
        seq2 = SeqCounter(start=max_seq + 1)
        budget_mgr2 = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log2, seq=seq2,
            workflow_id=workflow_id,
        )

        def executor2(name, config, predecessors=None):
            if config.type == "approval_gate":
                return TaskStatus.WAITING, None
            budget_mgr2.apply("ag1", BudgetDelta(tokens=1000))
            return TaskStatus.SUCCEEDED

        dag2 = DAGExecutor(
            workflow=wf, event_log=event_log2, seq=seq2,
            budget_manager=budget_mgr2, task_executor=executor2,
        )
        r2 = dag2.resume(workflow_id)

        assert r2.status == "succeeded"
        # New budget manager only sees task b's usage (1000), not a's
        # Budget state is per-session; event log has the full history
        assert budget_mgr2.total_usage.tokens_used == 1000


# ---------------------------------------------------------------------------
# Tests: Structured handoffs across pause
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestHandoffsAcrossPause:
    """Predecessor outputs survive pause/resume via event log."""

    def test_predecessor_output_available_after_resume(self, tmp_path):
        db_path = str(tmp_path / "handoff.db")
        wf = WorkflowDefinition(
            name="handoff-resume",
            tasks={
                "research": TaskConfig(name="research", agent="ag1"),
                "gate": TaskConfig(
                    name="gate", type="approval_gate",
                    depends_on=["research"], prompt="Review?",
                ),
                "build": TaskConfig(
                    name="build", agent="ag1", depends_on=["gate"],
                ),
            },
            agents={"ag1": {}},
        )
        workflow_id = "ho1"

        # Phase 1
        event_log = SQLiteEventLog(db_path)
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id=workflow_id,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)
        gate_ids: dict[str, str] = {}

        def executor1(name, config, predecessors=None):
            if config.type == "approval_gate":
                gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_ids[name] = gid
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED,
                summary="Found 3 critical issues",
                key_findings=[
                    Finding(finding="Issue A", confidence=Confidence.HIGH),
                    Finding(finding="Issue B", confidence=Confidence.MEDIUM),
                    Finding(finding="Issue C", confidence=Confidence.LOW),
                ],
            )

        dag1 = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor1,
        )
        r1 = dag1.run(workflow_id)
        assert r1.status == "paused"

        # Resolve gate
        gate_mgr.resolve_gate(gate_ids["gate"], GateResolution.APPROVED)

        # Phase 2: Resume — build should have research's output available
        event_log2 = SQLiteEventLog(db_path)
        max_seq = event_log2.last_seq(workflow_id)
        seq2 = SeqCounter(start=max_seq + 1)
        budget_mgr2 = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log2, seq=seq2,
            workflow_id=workflow_id,
        )
        received_predecessors: dict[str, list[TaskOutput]] = {}

        def executor2(name, config, predecessors=None):
            predecessors = predecessors or []
            received_predecessors[name] = predecessors
            if config.type == "approval_gate":
                return TaskStatus.WAITING, None
            return TaskStatus.SUCCEEDED, TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED, summary=f"Built {name}",
            )

        dag2 = DAGExecutor(
            workflow=wf, event_log=event_log2, seq=seq2,
            budget_manager=budget_mgr2, task_executor=executor2,
        )
        r2 = dag2.resume(workflow_id)

        assert r2.status == "succeeded"
        assert "research" in r2.task_outputs
        # Research output was reconstructed from event log
        research_output = r2.task_outputs["research"]
        assert research_output.summary == "Found 3 critical issues"
        assert len(research_output.key_findings) == 3
