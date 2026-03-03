"""Integration test — Tier 2 Claude Code adapter + DAG executor + workspace + budget.

Wires up all Sprint 1-5 components with a mocked subprocess to run
workflow YAMLs end-to-end through the Tier 2 adapter.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentos.adapters.tier2_claude_code import ClaudeCodeAdapter
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


# ---------------------------------------------------------------------------
# Mock subprocess helpers
# ---------------------------------------------------------------------------

@dataclass
class MockCompletedProcess:
    """Mimics subprocess.CompletedProcess."""
    returncode: int = 0
    stdout: str = "{}"
    stderr: str = ""


def make_mock_subprocess(
    *,
    tokens: int = 200,
    cost: float = 0.005,
) -> Any:
    """Create a mock subprocess.run that writes manifest and returns usage."""
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
        # Extract task description from the prompt (embedded in cmd via -p flag)
        prompt = ""
        if "-p" in cmd:
            idx = cmd.index("-p")
            prompt = cmd[idx + 1] if idx + 1 < len(cmd) else ""

        # Write manifest.json in the workspace
        if cwd:
            manifest = {
                "summary": f"Completed work in {Path(cwd).name}.",
                "findings": [{"finding": "Stub finding", "confidence": "medium"}],
                "open_questions": [],
            }
            (Path(cwd) / "manifest.json").write_text(json.dumps(manifest))

        usage_output = {
            "usage": {
                "input_tokens": tokens // 2,
                "output_tokens": tokens // 2,
            },
            "cost_usd": cost,
        }
        return MockCompletedProcess(stdout=json.dumps(usage_output))

    return mock_run


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
def workspace_root(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestTier2LinearWorkflow:
    """End-to-end: linear_research.yaml with Tier 2 Claude Code adapter."""

    def test_linear_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/linear_research.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "tier2-linear"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)

        mock_sub = make_mock_subprocess(tokens=200, cost=0.005)

        # One adapter per agent
        adapters: dict[str, ClaudeCodeAdapter] = {}
        for agent_name in workflow.agents:
            adapters[agent_name] = ClaudeCodeAdapter(
                budget_mgr, agent_name, run_subprocess=mock_sub,
            )

        execution_log: list[str] = []

        def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
            execution_log.append(task_name)

            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="test")
                return TaskStatus.SUCCEEDED

            agent_id = config.agent or "unknown"
            adapter = adapters.get(agent_id)
            if adapter is None:
                return TaskStatus.FAILED

            # Create task-scoped workspace dir
            task_ws = workspace_root / task_name
            task_ws.mkdir(exist_ok=True)

            output = asyncio.run(adapter.execute_task(
                task_description=config.description or task_name,
                role=workflow.agents[agent_id].role if agent_id in workflow.agents else "",
                workspace=task_ws,
                predecessor_context=[],
                allowed_tools=["Read", "Write", "Bash"],
            ))

            return TaskStatus.SUCCEEDED if output.status == TaskStatus.SUCCEEDED else TaskStatus.FAILED

        executor = DAGExecutor(
            workflow=workflow,
            event_log=event_log,
            seq=seq,
            budget_manager=budget_mgr,
            task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        # Workflow succeeds
        assert result.status == "succeeded"
        assert len(result.completed_tasks) == 3
        assert result.failed_tasks == []

        # Execution order preserved
        assert execution_log.index("research") < execution_log.index("review_gate")
        assert execution_log.index("review_gate") < execution_log.index("implement")

        # Budget tracking: 2 agent tasks × 200 tokens
        total = budget_mgr.total_usage
        assert total.tokens_used == 400
        assert total.api_calls_made == 2

        # Manifest files written by mock subprocess
        assert (workspace_root / "research" / "manifest.json").exists()
        assert (workspace_root / "implement" / "manifest.json").exists()

        # Events emitted
        events = event_log.replay(workflow_id)
        event_types = {e.event_type for e in events}
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.WORKFLOW_COMPLETED in event_types
        assert EventType.TASK_STATE_CHANGED in event_types
        assert EventType.BUDGET_CONSUMED in event_types
        assert EventType.GATE_WAITING in event_types
        assert EventType.GATE_RESOLVED in event_types


@pytest.mark.integration
class TestTier2ParallelWorkflow:
    """End-to-end: parallel_analysis.yaml with Tier 2 adapters."""

    def test_parallel_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/parallel_analysis.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "tier2-parallel"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )

        mock_sub = make_mock_subprocess(tokens=300, cost=0.01)
        adapters = {
            name: ClaudeCodeAdapter(budget_mgr, name, run_subprocess=mock_sub)
            for name in workflow.agents
        }

        def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
            agent_id = config.agent or "unknown"
            adapter = adapters.get(agent_id)
            if adapter is None:
                return TaskStatus.FAILED

            task_ws = workspace_root / task_name
            task_ws.mkdir(exist_ok=True)

            output = asyncio.run(adapter.execute_task(
                task_description=config.description or task_name,
                role=workflow.agents[agent_id].role if agent_id in workflow.agents else "",
                workspace=task_ws,
                predecessor_context=[],
                allowed_tools=[],
            ))

            return TaskStatus.SUCCEEDED if output.status == TaskStatus.SUCCEEDED else TaskStatus.FAILED

        executor = DAGExecutor(
            workflow=workflow,
            event_log=event_log,
            seq=seq,
            budget_manager=budget_mgr,
            task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"tech_analysis", "market_analysis", "synthesis"}

        # 3 tasks × 300 tokens
        assert budget_mgr.total_usage.tokens_used == 900

        # Parallel tasks completed before synthesis
        events = event_log.query(
            workflow_id=workflow_id,
            event_type=EventType.TASK_STATE_CHANGED,
        )
        succeeded_order = [
            e.payload["task_id"] for e in events
            if e.payload.get("to_state") == "succeeded"
        ]
        synthesis_idx = succeeded_order.index("synthesis")
        assert "tech_analysis" in succeeded_order[:synthesis_idx]
        assert "market_analysis" in succeeded_order[:synthesis_idx]


@pytest.mark.integration
class TestTier2FanoutWorkflow:
    """End-to-end: fanout_with_gate.yaml with Tier 2 adapters."""

    def test_fanout_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/fanout_with_gate.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "tier2-fanout"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)

        mock_sub = make_mock_subprocess(tokens=200, cost=0.005)
        adapters = {
            name: ClaudeCodeAdapter(budget_mgr, name, run_subprocess=mock_sub)
            for name in workflow.agents
        }

        def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="test")
                return TaskStatus.SUCCEEDED

            agent_id = config.agent or "unknown"
            adapter = adapters.get(agent_id)
            if adapter is None:
                return TaskStatus.FAILED

            task_ws = workspace_root / task_name
            task_ws.mkdir(exist_ok=True)

            output = asyncio.run(adapter.execute_task(
                task_description=config.description or task_name,
                role=workflow.agents[agent_id].role if agent_id in workflow.agents else "",
                workspace=task_ws,
                predecessor_context=[],
                allowed_tools=[],
            ))

            return TaskStatus.SUCCEEDED if output.status == TaskStatus.SUCCEEDED else TaskStatus.FAILED

        executor = DAGExecutor(
            workflow=workflow,
            event_log=event_log,
            seq=seq,
            budget_manager=budget_mgr,
            task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert len(result.completed_tasks) == 6

        # 5 agent tasks × 200 tokens = 1000
        assert budget_mgr.total_usage.tokens_used == 1000

        # Gate events emitted
        gate_events = event_log.query(
            workflow_id=workflow_id,
            event_type=EventType.GATE_WAITING,
        )
        assert len(gate_events) == 1

        resolved = event_log.query(
            workflow_id=workflow_id,
            event_type=EventType.GATE_RESOLVED,
        )
        assert len(resolved) == 1


@pytest.mark.integration
class TestTier2BudgetEnforcement:
    """Tier 2 adapter budget enforcement during workflow execution."""

    def test_budget_exceeded_fails_task(self, event_log, seq, workspace_root):
        """When budget is tight, tasks that exceed it fail the workflow."""
        yaml_path = Path("examples/linear_research.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "tier2-budget-tight"
        # Very tight budget: only 100 tokens total
        from agentos.schemas.budget import BudgetSpec
        tight_spec = BudgetSpec(max_tokens=100, max_api_calls=10)
        budget_mgr = BudgetManager(
            workflow_spec=tight_spec,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
        )

        # Subprocess uses 200 tokens — will exceed budget on first call
        mock_sub = make_mock_subprocess(tokens=200, cost=0.01)

        def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
            if config.type == "approval_gate":
                return TaskStatus.SUCCEEDED

            agent_id = config.agent or "unknown"
            adapter = ClaudeCodeAdapter(
                budget_mgr, agent_id, run_subprocess=mock_sub,
            )
            task_ws = workspace_root / task_name
            task_ws.mkdir(exist_ok=True)

            try:
                output = asyncio.run(adapter.execute_task(
                    task_description=config.description or task_name,
                    role="",
                    workspace=task_ws,
                    predecessor_context=[],
                    allowed_tools=[],
                ))
                return TaskStatus.SUCCEEDED if output.status == TaskStatus.SUCCEEDED else TaskStatus.FAILED
            except Exception:
                return TaskStatus.FAILED

        executor = DAGExecutor(
            workflow=workflow,
            event_log=event_log,
            seq=seq,
            budget_manager=budget_mgr,
            task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        # First task succeeds (budget applied post-hoc) but subsequent
        # tasks fail because budget is already exceeded
        assert len(result.failed_tasks) > 0 or len(result.skipped_tasks) > 0
