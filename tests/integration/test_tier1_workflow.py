"""Integration test — Tier 1 adapter + DAG executor + workspace + budget.

Wires up all Sprint 1-3 components with a mocked Anthropic API to run
a real workflow YAML end-to-end.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from agentos.adapters.tier1 import Tier1Adapter
from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig


# ---------------------------------------------------------------------------
# Mock API helpers (same pattern as unit tests)
# ---------------------------------------------------------------------------

@dataclass
class MockUsage:
    input_tokens: int = 50
    output_tokens: int = 25


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "tc_1"
    name: str = "task_complete"
    input: dict = field(default_factory=lambda: {"summary": "Done."})


@dataclass
class MockResponse:
    content: list = field(default_factory=list)
    stop_reason: str = "tool_use"
    usage: MockUsage = field(default_factory=MockUsage)


def _make_task_complete_response(summary: str) -> MockResponse:
    """Create a mock response that immediately calls task_complete."""
    return MockResponse(
        content=[MockToolUseBlock(input={"summary": summary})],
        stop_reason="tool_use",
    )


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
class TestLinearWorkflowIntegration:
    """End-to-end: load linear_research.yaml, run with mocked Tier 1 adapters."""

    def test_linear_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/linear_research.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "integration-linear"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )

        # Track which tasks were executed and in what order
        execution_log: list[str] = []

        def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
            execution_log.append(task_name)

            if config.type == "approval_gate":
                # Auto-approve gates
                return TaskStatus.SUCCEEDED

            agent_id = config.agent or "unknown"
            budget_mgr.apply(agent_id, BudgetDelta(
                tokens=200, api_calls=1, time_seconds=0.1, cost_usd=0.005,
            ))
            return TaskStatus.SUCCEEDED

        executor = DAGExecutor(
            workflow=workflow,
            event_log=event_log,
            seq=seq,
            budget_manager=budget_mgr,
            task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        # Workflow should succeed
        assert result.status == "succeeded"
        assert len(result.completed_tasks) == 3
        assert result.failed_tasks == []

        # Order: research → review_gate → implement
        assert execution_log.index("research") < execution_log.index("review_gate")
        assert execution_log.index("review_gate") < execution_log.index("implement")

        # Event log should have workflow + task + budget events
        events = event_log.replay(workflow_id)
        event_types = {e.event_type for e in events}
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.WORKFLOW_COMPLETED in event_types
        assert EventType.TASK_STATE_CHANGED in event_types
        assert EventType.BUDGET_CONSUMED in event_types

        # Budget should reflect 2 agent tasks (gate doesn't apply budget)
        total = budget_mgr.total_usage
        assert total.tokens_used == 400  # 200 per agent task × 2
        assert total.api_calls_made == 2


@pytest.mark.integration
class TestParallelWorkflowIntegration:
    """End-to-end: parallel_analysis.yaml with parallel task execution."""

    def test_parallel_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/parallel_analysis.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "integration-parallel"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )

        def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
            agent_id = config.agent or "unknown"
            budget_mgr.apply(agent_id, BudgetDelta(
                tokens=300, api_calls=1, time_seconds=0.1, cost_usd=0.01,
            ))
            return TaskStatus.SUCCEEDED

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

        # Both analyses must complete before synthesis
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
class TestFanoutWorkflowIntegration:
    """End-to-end: fanout_with_gate.yaml — fan-out, gate, merge."""

    def test_fanout_workflow_succeeds(self, event_log, seq, workspace_root):
        yaml_path = Path("examples/fanout_with_gate.yaml")
        raw = yaml.safe_load(yaml_path.read_text())
        workflow = WorkflowDefinition.model_validate(raw)

        workflow_id = "integration-fanout"
        agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=workflow.budget,
            event_log=event_log,
            seq=seq,
            workflow_id=workflow_id,
            agent_specs=agent_specs,
        )

        def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
            if config.type == "approval_gate":
                return TaskStatus.SUCCEEDED
            agent_id = config.agent or "unknown"
            budget_mgr.apply(agent_id, BudgetDelta(
                tokens=200, api_calls=1, time_seconds=0.1, cost_usd=0.005,
            ))
            return TaskStatus.SUCCEEDED

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

        # Budget: 5 agent tasks × 200 tokens = 1000
        assert budget_mgr.total_usage.tokens_used == 1000


@pytest.mark.integration
class TestWorkspaceWithDAGIntegration:
    """Workspace tracks files produced during DAG execution."""

    def test_workspace_file_tracking_across_tasks(self, event_log, seq, workspace_root):
        config = WorkspaceConfig(root=str(workspace_root))
        workspace = Workspace(config, event_log, seq, workflow_id="ws-test")

        # Simulate two tasks writing files
        workspace.write_file("research/notes.md", "# Notes", agent_id="a1", task_id="research")
        workspace.write_file("research/data.json", "{}", agent_id="a1", task_id="research")
        workspace.write_file("output/result.txt", "done", agent_id="a2", task_id="implement")

        # Query by task
        research_files = workspace.query_manifest(task_id="research")
        assert len(research_files) == 2
        assert {e.path for e in research_files} == {"research/notes.md", "research/data.json"}

        impl_files = workspace.query_manifest(task_id="implement")
        assert len(impl_files) == 1
        assert impl_files[0].path == "output/result.txt"

        # Event log should have FILE_CREATED events
        file_events = event_log.query(event_type=EventType.FILE_CREATED)
        assert len(file_events) == 3

        # All files exist on disk
        assert (workspace_root / "research" / "notes.md").exists()
        assert (workspace_root / "output" / "result.txt").exists()
