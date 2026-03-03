"""Integration tests — mixed Tier 1 + Tier 2 adapters in a single workflow.

Verifies structured handoffs across adapter tiers, shared budget tracking,
and failure propagation across tiers.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agentos.adapters.tier1 import Tier1Adapter
from agentos.adapters.tier2_claude_code import ClaudeCodeAdapter
from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
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
# Mock helpers
# ---------------------------------------------------------------------------

# Tier 1 mock API
@dataclass
class MockUsage:
    input_tokens: int = 50
    output_tokens: int = 25


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


def _make_tier1_mock(summary: str):
    """Mock Anthropic client that returns task_complete immediately."""
    class MockMessages:
        def create(self, **kwargs):
            return MockResponse(
                content=[MockToolUseBlock(input={"summary": summary})],
                stop_reason="tool_use",
            )
    class MockClient:
        messages = MockMessages()
    return MockClient()


# Tier 2 mock subprocess
def _make_tier2_mock_subprocess(tokens: int = 200, cost: float = 0.005):
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
        if cwd:
            manifest = {
                "summary": f"Tier 2 completed in {Path(cwd).name}.",
                "findings": [{"finding": "Tier 2 result", "confidence": "high"}],
                "open_questions": [],
            }
            (Path(cwd) / "manifest.json").write_text(json.dumps(manifest))

        class Result:
            returncode = 0
            stdout = json.dumps({
                "usage": {"input_tokens": tokens // 2, "output_tokens": tokens // 2},
                "cost_usd": cost,
            })
            stderr = ""
        return Result()
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
class TestMixedTierWorkflow:
    """Workflow with both Tier 1 and Tier 2 agents."""

    def test_tier1_to_tier2_handoff(self, event_log, seq, workspace_root):
        """Tier 1 task → Tier 2 task: Tier 2 receives Tier 1's output."""
        wf = WorkflowDefinition(
            name="mixed",
            budget=BudgetSpec(max_tokens=50000),
            tasks={
                "research": TaskConfig(name="research", agent="tier1_agent"),
                "implement": TaskConfig(
                    name="implement", agent="tier2_agent",
                    depends_on=["research"],
                ),
            },
            agents={
                "tier1_agent": {"adapter": "tier1"},
                "tier2_agent": {"adapter": "tier2_claude_code"},
            },
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="m1",
        )

        tier1_client = _make_tier1_mock("Research done: found 3 key issues.")
        tier1_adapter = Tier1Adapter(tier1_client, "test-model", budget_mgr, "tier1_agent")

        tier2_mock = _make_tier2_mock_subprocess(tokens=200, cost=0.005)
        tier2_adapter = ClaudeCodeAdapter(budget_mgr, "tier2_agent", run_subprocess=tier2_mock)

        adapters = {"tier1_agent": tier1_adapter, "tier2_agent": tier2_adapter}
        received_predecessors: dict[str, list[TaskOutput]] = {}

        def executor(name, config, predecessors=None):
            predecessors = predecessors or []
            received_predecessors[name] = predecessors

            agent_id = config.agent
            adapter = adapters[agent_id]

            task_ws = workspace_root / name
            task_ws.mkdir(exist_ok=True)

            output = asyncio.run(adapter.execute_task(
                task_description=config.description or name,
                role="",
                workspace=task_ws,
                predecessor_context=predecessors,
                allowed_tools=[],
            ))
            output.task_id = name

            return output.status, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("m1")

        assert result.status == "succeeded"
        assert len(result.completed_tasks) == 2

        # Tier 2 task received Tier 1's output as predecessor
        assert len(received_predecessors["implement"]) == 1
        assert received_predecessors["implement"][0].task_id == "research"

        # Both adapters contributed to budget
        total = budget_mgr.total_usage
        assert total.tokens_used > 0
        assert total.api_calls_made >= 2

    def test_shared_budget_across_tiers(self, event_log, seq, workspace_root):
        """Budget tracking is shared across Tier 1 and Tier 2 agents."""
        wf = WorkflowDefinition(
            name="shared-budget",
            budget=BudgetSpec(max_tokens=50000),
            tasks={
                "t1_task": TaskConfig(name="t1_task", agent="t1"),
                "t2_task": TaskConfig(name="t2_task", agent="t2"),
            },
            agents={"t1": {"adapter": "tier1"}, "t2": {"adapter": "tier2_claude_code"}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="m2",
        )

        tier1 = Tier1Adapter(_make_tier1_mock("Done T1."), "test-model", budget_mgr, "t1")
        tier2 = ClaudeCodeAdapter(budget_mgr, "t2", run_subprocess=_make_tier2_mock_subprocess())
        adapters = {"t1": tier1, "t2": tier2}

        def executor(name, config, predecessors=None):
            adapter = adapters[config.agent]
            task_ws = workspace_root / name
            task_ws.mkdir(exist_ok=True)
            output = asyncio.run(adapter.execute_task(
                task_description=name, role="",
                workspace=task_ws, predecessor_context=[], allowed_tools=[],
            ))
            return output.status, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("m2")

        assert result.status == "succeeded"

        # Both agents tracked separately
        t1_usage = budget_mgr.usage_for("t1")
        t2_usage = budget_mgr.usage_for("t2")
        assert t1_usage.tokens_used > 0
        assert t2_usage.tokens_used > 0

        # Total reflects both
        total = budget_mgr.total_usage
        assert total.tokens_used == t1_usage.tokens_used + t2_usage.tokens_used

    def test_gate_between_tiers(self, event_log, seq, workspace_root):
        """Tier 1 → gate → Tier 2: gate doesn't break cross-tier handoff."""
        wf = WorkflowDefinition(
            name="gate-tiers",
            budget=BudgetSpec(max_tokens=50000),
            tasks={
                "analyze": TaskConfig(name="analyze", agent="t1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["analyze"], prompt="Approve analysis?",
                ),
                "build": TaskConfig(
                    name="build", agent="t2", depends_on=["review"],
                ),
            },
            agents={"t1": {"adapter": "tier1"}, "t2": {"adapter": "tier2_claude_code"}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="m3",
        )
        gate_mgr = GateManager(event_log, seq, "m3")

        tier1 = Tier1Adapter(_make_tier1_mock("Analysis complete."), "test-model", budget_mgr, "t1")
        tier2 = ClaudeCodeAdapter(budget_mgr, "t2", run_subprocess=_make_tier2_mock_subprocess())

        def executor(name, config, predecessors=None):
            predecessors = predecessors or []

            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="test")
                return TaskStatus.SUCCEEDED, None

            adapter = tier1 if config.agent == "t1" else tier2
            task_ws = workspace_root / name
            task_ws.mkdir(exist_ok=True)

            output = asyncio.run(adapter.execute_task(
                task_description=name, role="",
                workspace=task_ws, predecessor_context=predecessors, allowed_tools=[],
            ))
            return output.status, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("m3")

        assert result.status == "succeeded"
        assert len(result.completed_tasks) == 3

        # Gate events emitted
        gate_events = event_log.query(workflow_id="m3", event_type=EventType.GATE_WAITING)
        assert len(gate_events) == 1

    def test_tier1_failure_skips_tier2(self, event_log, seq, workspace_root):
        """Tier 1 fails → Tier 2 dependent is skipped."""
        wf = WorkflowDefinition(
            name="cross-fail",
            budget=BudgetSpec(max_tokens=50000),
            tasks={
                "analyze": TaskConfig(name="analyze", agent="t1"),
                "build": TaskConfig(name="build", agent="t2", depends_on=["analyze"]),
            },
            agents={"t1": {"adapter": "tier1"}, "t2": {"adapter": "tier2_claude_code"}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="m4",
        )

        def executor(name, config, predecessors=None):
            if name == "analyze":
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("m4")

        assert result.status == "failed"
        assert "analyze" in result.failed_tasks
        assert "build" in result.skipped_tasks
