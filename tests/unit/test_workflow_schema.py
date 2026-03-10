"""Tests for budget, agent, and workflow schemas + YAML parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentos.schemas.agent import AdapterTier, AgentConfig
from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage
from agentos.schemas.task import TaskConfig
from agentos.schemas.workflow import WorkflowDefinition

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"


# ---------------------------------------------------------------------------
# BudgetSpec
# ---------------------------------------------------------------------------


class TestBudgetSpec:
    def test_defaults_all_none(self):
        spec = BudgetSpec()
        assert spec.max_tokens is None
        assert spec.max_api_calls is None
        assert spec.max_time_seconds is None
        assert spec.max_cost_usd is None
        assert spec.max_concurrent_tasks == 4

    def test_round_trip(self):
        spec = BudgetSpec(max_tokens=5000, max_cost_usd=1.50)
        data = json.loads(spec.model_dump_json())
        restored = BudgetSpec.model_validate(data)
        assert restored.max_tokens == 5000
        assert restored.max_cost_usd == pytest.approx(1.50)
        assert restored.max_api_calls is None

    def test_max_concurrent_tasks_minimum(self):
        with pytest.raises(Exception):
            BudgetSpec(max_concurrent_tasks=0)


# ---------------------------------------------------------------------------
# BudgetUsage
# ---------------------------------------------------------------------------


class TestBudgetUsage:
    def test_defaults_zero(self):
        usage = BudgetUsage()
        assert usage.tokens_used == 0
        assert usage.api_calls_made == 0
        assert usage.time_elapsed_seconds == 0.0
        assert usage.cost_usd == 0.0

    def test_round_trip(self):
        usage = BudgetUsage(tokens_used=1500, cost_usd=0.05)
        data = json.loads(usage.model_dump_json())
        restored = BudgetUsage.model_validate(data)
        assert restored.tokens_used == 1500
        assert restored.cost_usd == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# BudgetDelta
# ---------------------------------------------------------------------------


class TestBudgetDelta:
    def test_defaults_zero(self):
        delta = BudgetDelta()
        assert delta.tokens == 0
        assert delta.api_calls == 0

    def test_round_trip(self):
        delta = BudgetDelta(tokens=500, api_calls=1, cost_usd=0.01)
        data = json.loads(delta.model_dump_json())
        restored = BudgetDelta.model_validate(data)
        assert restored.tokens == 500
        assert restored.api_calls == 1


# ---------------------------------------------------------------------------
# AdapterTier
# ---------------------------------------------------------------------------


class TestAdapterTier:
    def test_values(self):
        assert AdapterTier.TIER1 == 1
        assert AdapterTier.TIER2 == 2
        assert AdapterTier.TIER3 == 3

    def test_is_int(self):
        assert isinstance(AdapterTier.TIER1, int)


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig()
        assert config.adapter == "tier1"
        assert config.model == "claude-sonnet-4-6"
        assert config.role == ""
        assert config.tools == []
        assert config.budget.max_tokens is None

    def test_round_trip(self):
        config = AgentConfig(
            adapter="tier2_claude_code",
            model="claude-opus-4-6",
            role="You are a researcher.",
            tools=["web_search", "file_read"],
            budget=BudgetSpec(max_tokens=10000),
        )
        data = json.loads(config.model_dump_json())
        restored = AgentConfig.model_validate(data)
        assert restored.adapter == "tier2_claude_code"
        assert restored.tools == ["web_search", "file_read"]
        assert restored.budget.max_tokens == 10000

    def test_per_agent_budget(self):
        config = AgentConfig(budget=BudgetSpec(max_tokens=5000, max_cost_usd=0.50))
        assert config.budget.max_tokens == 5000
        assert config.budget.max_cost_usd == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# TaskConfig (added in Sprint 1, verify it still works in workflow context)
# ---------------------------------------------------------------------------


class TestTaskConfig:
    def test_defaults(self):
        config = TaskConfig(name="t1")
        assert config.agent is None
        assert config.type == "agent_task"
        assert config.depends_on == []
        assert config.workspace == "shared"

    def test_gate_config(self):
        config = TaskConfig(
            name="review",
            type="approval_gate",
            depends_on=["research"],
            prompt="Review findings.",
        )
        assert config.type == "approval_gate"
        assert config.depends_on == ["research"]
        assert config.prompt == "Review findings."


# ---------------------------------------------------------------------------
# WorkflowDefinition
# ---------------------------------------------------------------------------


class TestWorkflowDefinition:
    def test_minimal(self):
        wf = WorkflowDefinition(name="test")
        assert wf.name == "test"
        assert wf.version == "1.0"
        assert wf.tasks == {}
        assert wf.agents == {}

    def test_round_trip(self):
        wf = WorkflowDefinition(
            name="demo",
            budget=BudgetSpec(max_tokens=50000),
            agents={"a1": AgentConfig(role="researcher")},
            tasks={"t1": TaskConfig(name="t1", agent="a1")},
        )
        data = json.loads(wf.model_dump_json())
        restored = WorkflowDefinition.model_validate(data)
        assert restored.name == "demo"
        assert "a1" in restored.agents
        assert restored.tasks["t1"].agent == "a1"
        assert restored.budget.max_tokens == 50000


# ---------------------------------------------------------------------------
# YAML parsing — example workflows
# ---------------------------------------------------------------------------


class TestYAMLParseLinear:
    def test_parse_linear_research(self):
        raw = yaml.safe_load((EXAMPLES_DIR / "linear_research.yaml").read_text())
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.name == "research_and_implement"
        assert len(wf.tasks) == 3
        assert len(wf.agents) == 2
        assert "researcher" in wf.agents
        assert "implementer" in wf.agents
        assert wf.tasks["review_gate"].type == "approval_gate"
        assert wf.tasks["implement"].depends_on == ["review_gate"]
        assert wf.budget.max_tokens == 50000
        assert wf.budget.max_cost_usd == pytest.approx(2.00)


class TestYAMLParseParallel:
    def test_parse_parallel_analysis(self):
        raw = yaml.safe_load((EXAMPLES_DIR / "parallel_analysis.yaml").read_text())
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.name == "parallel_analysis"
        assert len(wf.tasks) == 3
        assert len(wf.agents) == 3
        # tech_analysis and market_analysis have no dependencies (parallel)
        assert wf.tasks["tech_analysis"].depends_on == []
        assert wf.tasks["market_analysis"].depends_on == []
        # synthesis depends on both
        assert set(wf.tasks["synthesis"].depends_on) == {
            "tech_analysis",
            "market_analysis",
        }


class TestYAMLParseFanout:
    def test_parse_fanout_with_gate(self):
        raw = yaml.safe_load((EXAMPLES_DIR / "fanout_with_gate.yaml").read_text())
        wf = WorkflowDefinition.model_validate(raw)
        assert wf.name == "fanout_review"
        assert len(wf.tasks) == 6
        assert len(wf.agents) == 5
        # Three parallel tasks depend on plan
        for name in ("data_layer", "api_layer", "cli_layer"):
            assert wf.tasks[name].depends_on == ["plan"]
        # Gate depends on all three
        assert set(wf.tasks["review_gate"].depends_on) == {
            "data_layer",
            "api_layer",
            "cli_layer",
        }
        assert wf.tasks["integration"].depends_on == ["review_gate"]
        assert wf.budget.max_tokens == 120000
