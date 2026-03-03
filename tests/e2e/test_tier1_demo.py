"""E2E test — Phase 1 exit criterion: 10 consecutive successful runs.

Runs the full pipeline (workflow load → DAG execution → gate resolution →
budget tracking → event log) 10 times with all 3 example workflows.
"""

from __future__ import annotations

import uuid

import pytest
import yaml

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig


def _run_workflow(yaml_path: str, tmp_path) -> dict:
    """Run a workflow end-to-end and return result metadata."""
    raw = yaml.safe_load(open(yaml_path).read())
    wf = WorkflowDefinition.model_validate(raw)

    event_log = SQLiteEventLog()
    seq = SeqCounter()
    workflow_id = f"e2e-{uuid.uuid4().hex[:8]}"

    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs=agent_specs,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    ws_root = tmp_path / workflow_id
    workspace = Workspace(
        WorkspaceConfig(root=str(ws_root)),
        event_log, seq, workflow_id=workflow_id,
    )
    workspace.ensure_root()

    def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="e2e-test")
            return TaskStatus.SUCCEEDED

        agent_id = config.agent or "unassigned"
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=200, api_calls=1, time_seconds=0.05, cost_usd=0.005,
        ))
        workspace.write_file(
            f"{task_name}/output.md",
            f"# {task_name}\nStatus: succeeded\n",
            agent_id=agent_id, task_id=task_name,
        )
        return TaskStatus.SUCCEEDED

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
    )
    result = executor.run(workflow_id)

    events = event_log.replay(workflow_id)
    event_types = {e.event_type for e in events}

    return {
        "status": result.status,
        "completed": len(result.completed_tasks),
        "failed": len(result.failed_tasks),
        "skipped": len(result.skipped_tasks),
        "event_count": len(events),
        "has_workflow_started": EventType.WORKFLOW_STARTED in event_types,
        "has_workflow_completed": EventType.WORKFLOW_COMPLETED in event_types,
        "has_task_events": EventType.TASK_STATE_CHANGED in event_types,
        "has_budget_events": EventType.BUDGET_CONSUMED in event_types,
        "total_tokens": budget_mgr.total_usage.tokens_used,
        "files_produced": len(workspace.manifest),
    }


@pytest.mark.e2e
class TestTier1Demo10Runs:
    """Phase 1 exit criterion: 10 consecutive successful runs per workflow."""

    @pytest.mark.parametrize("run_id", range(10))
    def test_linear_research(self, run_id, tmp_path):
        result = _run_workflow("examples/linear_research.yaml", tmp_path)
        assert result["status"] == "succeeded"
        assert result["completed"] == 3
        assert result["failed"] == 0
        assert result["has_workflow_started"]
        assert result["has_workflow_completed"]
        assert result["has_task_events"]
        assert result["has_budget_events"]
        assert result["total_tokens"] == 400  # 2 agent tasks × 200
        assert result["files_produced"] == 2  # 2 agent tasks write output

    @pytest.mark.parametrize("run_id", range(10))
    def test_parallel_analysis(self, run_id, tmp_path):
        result = _run_workflow("examples/parallel_analysis.yaml", tmp_path)
        assert result["status"] == "succeeded"
        assert result["completed"] == 3
        assert result["failed"] == 0
        assert result["has_workflow_started"]
        assert result["has_workflow_completed"]
        assert result["total_tokens"] == 600  # 3 agent tasks × 200
        assert result["files_produced"] == 3

    @pytest.mark.parametrize("run_id", range(10))
    def test_fanout_with_gate(self, run_id, tmp_path):
        result = _run_workflow("examples/fanout_with_gate.yaml", tmp_path)
        assert result["status"] == "succeeded"
        assert result["completed"] == 6
        assert result["failed"] == 0
        assert result["has_workflow_started"]
        assert result["has_workflow_completed"]
        assert result["total_tokens"] == 1000  # 5 agent tasks × 200
        assert result["files_produced"] == 5
