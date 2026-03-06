"""Integration tests — Aider adapter in full workflow pipelines.

Exercises the Aider adapter through the DAG executor with mocked subprocesses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentos.adapters.tier2_aider import AiderAdapter
from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_aider_mock(*, manifest_data: dict | None = None):
    """Create a mock subprocess.run that simulates Aider."""
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
        if cwd and manifest_data is not None:
            (Path(cwd) / "manifest.json").write_text(json.dumps(manifest_data))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    return mock_run


def _make_workflow_yaml(agents: dict, tasks: dict, budget: dict | None = None) -> str:
    """Build a workflow YAML string."""
    wf = {
        "name": "test-aider-wf",
        "version": "1.0",
        "budget": budget or {"max_tokens": 100000, "max_cost_usd": 10.0},
        "agents": agents,
        "tasks": tasks,
    }
    return yaml.dump(wf)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAiderLinearWorkflow:
    """Linear: aider_task_a -> aider_task_b."""

    def test_linear_two_aider_tasks(self, tmp_path):
        """Two sequential Aider tasks complete successfully."""
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        workflow_id = "aider-linear-01"

        raw = yaml.safe_load(_make_workflow_yaml(
            agents={
                "coder": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Coder"},
            },
            tasks={
                "implement": {
                    "name": "implement",
                    "agent": "coder",
                    "description": "Implement feature X",
                },
                "test": {
                    "name": "test",
                    "agent": "coder",
                    "description": "Write tests for feature X",
                    "depends_on": ["implement"],
                },
            },
        ))
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id,
        )

        mock_sub = _make_aider_mock(manifest_data={
            "summary": "Task done.", "findings": [], "open_questions": [],
        })
        adapter = AiderAdapter(budget_mgr, "coder", run_subprocess=mock_sub)

        import asyncio

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []
            ws = tmp_path / task_name
            ws.mkdir(exist_ok=True)
            output = asyncio.run(adapter.execute_task(
                task_description=config.description,
                role="Coder",
                workspace=ws,
                predecessor_context=predecessors,
                allowed_tools=[],
            ))
            output.task_id = task_name
            return output.status, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"implement", "test"}


class TestAiderParallelWorkflow:
    """Parallel: plan -> (dev_a | dev_b) -> merge."""

    def test_parallel_aider_tasks(self, tmp_path):
        """Parallel Aider tasks converge correctly."""
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        workflow_id = "aider-parallel-01"

        raw = yaml.safe_load(_make_workflow_yaml(
            agents={
                "planner": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Planner"},
                "dev_a": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Dev A"},
                "dev_b": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Dev B"},
                "integrator": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Integrator"},
            },
            tasks={
                "plan": {"name": "plan", "agent": "planner", "description": "Create plan"},
                "impl_a": {"name": "impl_a", "agent": "dev_a", "description": "Implement A", "depends_on": ["plan"]},
                "impl_b": {"name": "impl_b", "agent": "dev_b", "description": "Implement B", "depends_on": ["plan"]},
                "merge": {"name": "merge", "agent": "integrator", "description": "Merge all", "depends_on": ["impl_a", "impl_b"]},
            },
        ))
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id,
        )

        mock_sub = _make_aider_mock(manifest_data={
            "summary": "Done.", "findings": [], "open_questions": [],
        })
        adapters = {name: AiderAdapter(budget_mgr, name, run_subprocess=mock_sub) for name in wf.agents}

        import asyncio

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []
            agent_id = config.agent or "unassigned"
            adapter = adapters[agent_id]
            ws = tmp_path / task_name
            ws.mkdir(exist_ok=True)
            output = asyncio.run(adapter.execute_task(
                task_description=config.description,
                role=wf.agents[agent_id].role,
                workspace=ws,
                predecessor_context=predecessors,
                allowed_tools=[],
            ))
            output.task_id = task_name
            return output.status, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"plan", "impl_a", "impl_b", "merge"}


class TestMixedTierWorkflow:
    """Mixed: Tier 1 stub + Aider Tier 2 in same workflow."""

    def test_mixed_tier1_and_aider(self, tmp_path):
        """Tier 1 stub and Aider adapter coexist in a workflow."""
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        workflow_id = "mixed-01"

        raw = yaml.safe_load(_make_workflow_yaml(
            agents={
                "researcher": {"adapter": "tier1", "model": "claude-sonnet-4-6", "role": "Researcher"},
                "coder": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Coder"},
            },
            tasks={
                "research": {"name": "research", "agent": "researcher", "description": "Research the topic"},
                "implement": {"name": "implement", "agent": "coder", "description": "Implement findings", "depends_on": ["research"]},
            },
        ))
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id,
        )

        mock_sub = _make_aider_mock(manifest_data={
            "summary": "Implemented.", "findings": [], "open_questions": [],
        })
        aider_adapter = AiderAdapter(budget_mgr, "coder", run_subprocess=mock_sub)

        import asyncio

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []
            agent_id = config.agent or "unassigned"

            if agent_id == "coder":
                ws = tmp_path / task_name
                ws.mkdir(exist_ok=True)
                output = asyncio.run(aider_adapter.execute_task(
                    task_description=config.description,
                    role="Coder",
                    workspace=ws,
                    predecessor_context=predecessors,
                    allowed_tools=[],
                ))
                output.task_id = task_name
                return output.status, output

            # Stub for Tier 1
            output = TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.SUCCEEDED, summary="Stub completed.",
            )
            return TaskStatus.SUCCEEDED, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"research", "implement"}


class TestAiderBudgetEnforcement:
    """Budget enforcement with Aider adapter."""

    def test_budget_halts_workflow(self, tmp_path):
        """Exceeding budget during Aider execution halts the workflow."""
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        workflow_id = "aider-budget-01"

        raw = yaml.safe_load(_make_workflow_yaml(
            agents={
                "coder": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Coder"},
            },
            tasks={
                "task1": {"name": "task1", "agent": "coder", "description": "First task"},
                "task2": {"name": "task2", "agent": "coder", "description": "Second task", "depends_on": ["task1"]},
            },
            budget={"max_tokens": 100000, "max_api_calls": 1, "max_cost_usd": 10.0},
        ))
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id,
        )

        mock_sub = _make_aider_mock(manifest_data={
            "summary": "Done.", "findings": [], "open_questions": [],
        })
        adapter = AiderAdapter(budget_mgr, "coder", run_subprocess=mock_sub)

        import asyncio

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []
            ws = tmp_path / task_name
            ws.mkdir(exist_ok=True)
            output = asyncio.run(adapter.execute_task(
                task_description=config.description,
                role="Coder",
                workspace=ws,
                predecessor_context=predecessors,
                allowed_tools=[],
            ))
            output.task_id = task_name
            return output.status, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        # First task succeeds, second fails due to budget (api_calls=1 already used)
        assert result.status == "failed"
        assert "task1" in result.completed_tasks
