"""Tests for agentos.validation.workflow_verifier — static DAG analysis."""

from __future__ import annotations

import pytest

from agentos.schemas.agent import AgentConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import TaskConfig
from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.workflow_verifier import (
    Severity,
    VerificationReport,
    WorkflowVerifier,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wf(tasks: dict, agents: dict | None = None, budget: BudgetSpec | None = None) -> WorkflowDefinition:
    """Shorthand for building a WorkflowDefinition."""
    return WorkflowDefinition(
        name="test",
        tasks={name: TaskConfig(name=name, **cfg) for name, cfg in tasks.items()},
        agents={name: AgentConfig(**acfg) for name, acfg in (agents or {}).items()},
        budget=budget or BudgetSpec(),
    )


@pytest.fixture
def verifier():
    return WorkflowVerifier()


# ---------------------------------------------------------------------------
# Tests: Valid workflows
# ---------------------------------------------------------------------------

class TestValidWorkflows:
    def test_linear_workflow(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ag1"},
                "b": {"agent": "ag1", "depends_on": ["a"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert report.valid
        assert report.errors == []

    def test_parallel_workflow(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ag1"},
                "b": {"agent": "ag2"},
                "c": {"agent": "ag1", "depends_on": ["a", "b"]},
            },
            agents={"ag1": {}, "ag2": {}},
        )
        report = verifier.verify(wf)
        assert report.valid

    def test_diamond_dag(self, verifier):
        wf = _wf(
            tasks={
                "root": {"agent": "ag1"},
                "left": {"agent": "ag1", "depends_on": ["root"]},
                "right": {"agent": "ag2", "depends_on": ["root"]},
                "merge": {"agent": "ag1", "depends_on": ["left", "right"]},
            },
            agents={"ag1": {}, "ag2": {}},
        )
        report = verifier.verify(wf)
        assert report.valid

    def test_gate_task_no_agent(self, verifier):
        wf = _wf(
            tasks={
                "research": {"agent": "ag1"},
                "review": {"type": "approval_gate", "depends_on": ["research"]},
                "implement": {"agent": "ag1", "depends_on": ["review"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert report.valid
        assert report.warnings == []

    def test_single_task(self, verifier):
        wf = _wf(
            tasks={"only": {"agent": "ag1"}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert report.valid

    def test_example_linear_research(self, verifier):
        """Verify the real linear_research.yaml example."""
        import yaml
        raw = yaml.safe_load(open("examples/linear_research.yaml").read())
        wf = WorkflowDefinition.model_validate(raw)
        report = verifier.verify(wf)
        assert report.valid

    def test_example_parallel_analysis(self, verifier):
        import yaml
        raw = yaml.safe_load(open("examples/parallel_analysis.yaml").read())
        wf = WorkflowDefinition.model_validate(raw)
        report = verifier.verify(wf)
        assert report.valid

    def test_example_fanout_with_gate(self, verifier):
        import yaml
        raw = yaml.safe_load(open("examples/fanout_with_gate.yaml").read())
        wf = WorkflowDefinition.model_validate(raw)
        report = verifier.verify(wf)
        assert report.valid


# ---------------------------------------------------------------------------
# Tests: Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def test_direct_cycle(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ag1", "depends_on": ["b"]},
                "b": {"agent": "ag1", "depends_on": ["a"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "cycle_detected" in codes

    def test_transitive_cycle(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ag1", "depends_on": ["c"]},
                "b": {"agent": "ag1", "depends_on": ["a"]},
                "c": {"agent": "ag1", "depends_on": ["b"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "cycle_detected" in codes

    def test_self_cycle(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1", "depends_on": ["a"]}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid


# ---------------------------------------------------------------------------
# Tests: Missing dependencies
# ---------------------------------------------------------------------------

class TestMissingDependencies:
    def test_missing_single_dep(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1", "depends_on": ["nonexistent"]}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "missing_dependency" in codes
        assert report.errors[0].task == "a"

    def test_missing_multiple_deps(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ag1", "depends_on": ["x", "y"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        missing = [e for e in report.errors if e.code == "missing_dependency"]
        assert len(missing) == 2


# ---------------------------------------------------------------------------
# Tests: Undefined agents
# ---------------------------------------------------------------------------

class TestUndefinedAgents:
    def test_undefined_agent(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ghost"}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "undefined_agent" in codes
        assert report.errors[0].agent == "ghost"

    def test_multiple_undefined_agents(self, verifier):
        wf = _wf(
            tasks={
                "a": {"agent": "ghost1"},
                "b": {"agent": "ghost2"},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        undefined = [e for e in report.errors if e.code == "undefined_agent"]
        assert len(undefined) == 2


# ---------------------------------------------------------------------------
# Tests: Unreachable tasks
# ---------------------------------------------------------------------------

class TestUnreachableTasks:
    def test_no_root_tasks(self, verifier):
        """All tasks have deps but form a cycle → detected as both cycle and no-root."""
        wf = _wf(
            tasks={
                "a": {"agent": "ag1", "depends_on": ["b"]},
                "b": {"agent": "ag1", "depends_on": ["a"]},
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "no_root_tasks" in codes

    def test_disconnected_subgraph(self, verifier):
        """Task C depends on nonexistent D, but A→B is valid. C has missing dep."""
        wf = _wf(
            tasks={
                "a": {"agent": "ag1"},
                "b": {"agent": "ag1", "depends_on": ["a"]},
                "c": {"agent": "ag1", "depends_on": ["d"]},  # d doesn't exist
            },
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "missing_dependency" in codes


# ---------------------------------------------------------------------------
# Tests: Budget allocation warnings
# ---------------------------------------------------------------------------

class TestBudgetAllocations:
    def test_agent_tokens_exceed_workflow(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1"}},
            agents={"ag1": {"budget": {"max_tokens": 200000}}},
            budget=BudgetSpec(max_tokens=100000),
        )
        report = verifier.verify(wf)
        assert report.valid  # warnings don't invalidate
        assert len(report.warnings) == 1
        assert report.warnings[0].code == "budget_exceeds_workflow"
        assert "token" in report.warnings[0].message.lower()

    def test_agent_cost_exceeds_workflow(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1"}},
            agents={"ag1": {"budget": {"max_cost_usd": 10.0}}},
            budget=BudgetSpec(max_cost_usd=5.0),
        )
        report = verifier.verify(wf)
        assert report.valid
        assert len(report.warnings) == 1
        assert "cost" in report.warnings[0].message.lower()

    def test_agent_api_calls_exceed_workflow(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1"}},
            agents={"ag1": {"budget": {"max_api_calls": 500}}},
            budget=BudgetSpec(max_api_calls=100),
        )
        report = verifier.verify(wf)
        assert report.valid
        assert len(report.warnings) == 1
        assert "api call" in report.warnings[0].message.lower()

    def test_no_warning_when_under_limit(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ag1"}},
            agents={"ag1": {"budget": {"max_tokens": 5000}}},
            budget=BudgetSpec(max_tokens=100000),
        )
        report = verifier.verify(wf)
        assert report.valid
        assert report.warnings == []

    def test_no_warning_when_no_workflow_limit(self, verifier):
        """No warning if workflow has no max set."""
        wf = _wf(
            tasks={"a": {"agent": "ag1"}},
            agents={"ag1": {"budget": {"max_tokens": 999999}}},
            budget=BudgetSpec(),  # no limits
        )
        report = verifier.verify(wf)
        assert report.valid
        assert report.warnings == []


# ---------------------------------------------------------------------------
# Tests: Gate warnings
# ---------------------------------------------------------------------------

class TestGateWarnings:
    def test_gate_with_agent_warns(self, verifier):
        wf = _wf(
            tasks={"gate": {"type": "approval_gate", "agent": "ag1"}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        # gate_has_agent is a warning, but agent_task_no_agent won't fire (type is gate)
        assert report.valid
        assert len(report.warnings) == 1
        assert report.warnings[0].code == "gate_has_agent"

    def test_input_gate_with_agent_warns(self, verifier):
        wf = _wf(
            tasks={"gate": {"type": "input_gate", "agent": "ag1"}},
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert report.valid
        assert any(w.code == "gate_has_agent" for w in report.warnings)


# ---------------------------------------------------------------------------
# Tests: Agent tasks without agents
# ---------------------------------------------------------------------------

class TestAgentTaskNoAgent:
    def test_agent_task_without_agent(self, verifier):
        wf = _wf(
            tasks={"a": {}},  # agent_task type, no agent
            agents={"ag1": {}},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "agent_task_no_agent" in codes


# ---------------------------------------------------------------------------
# Tests: Empty workflow
# ---------------------------------------------------------------------------

class TestEmptyWorkflow:
    def test_empty_workflow_warns(self, verifier):
        wf = _wf(tasks={}, agents={})
        report = verifier.verify(wf)
        assert report.valid  # empty is technically valid
        assert len(report.warnings) == 1
        assert report.warnings[0].code == "empty_workflow"


# ---------------------------------------------------------------------------
# Tests: Verification report model
# ---------------------------------------------------------------------------

class TestVerificationReport:
    def test_issue_count(self):
        report = VerificationReport(valid=True)
        assert report.issue_count == 0

    def test_issue_count_with_issues(self, verifier):
        wf = _wf(
            tasks={"a": {"agent": "ghost", "depends_on": ["missing"]}},
            agents={},
        )
        report = verifier.verify(wf)
        assert report.issue_count >= 2  # at least missing_dep + undefined_agent


# ---------------------------------------------------------------------------
# Tests: Multiple errors
# ---------------------------------------------------------------------------

class TestMultipleErrors:
    def test_multiple_error_types(self, verifier):
        """Workflow with multiple different error types."""
        wf = _wf(
            tasks={
                "a": {"agent": "ghost", "depends_on": ["missing"]},
                "b": {},  # no agent
            },
            agents={},
        )
        report = verifier.verify(wf)
        assert not report.valid
        codes = {e.code for e in report.errors}
        assert "missing_dependency" in codes
        assert "undefined_agent" in codes
        assert "agent_task_no_agent" in codes


# ---------------------------------------------------------------------------
# Tests: Tool name checks
# ---------------------------------------------------------------------------

class TestToolNameChecks:
    def test_valid_tools_no_warnings(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read", "file_write"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        tool_warnings = [w for w in report.warnings if w.code == "unknown_tool"]
        assert len(tool_warnings) == 0

    def test_unknown_tool_warns(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read", "websearch"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        tool_warnings = [w for w in report.warnings if w.code == "unknown_tool"]
        assert len(tool_warnings) == 1
        assert "websearch" in tool_warnings[0].message

    def test_did_you_mean_suggestion(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_reade"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        tool_warnings = [w for w in report.warnings if w.code == "unknown_tool"]
        assert len(tool_warnings) == 1
        assert "file_read" in tool_warnings[0].message

    def test_empty_tools_no_warnings(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test"}},
        )
        report = verifier.verify(wf)
        tool_warnings = [w for w in report.warnings if w.code == "unknown_tool"]
        assert len(tool_warnings) == 0


# ---------------------------------------------------------------------------
# Tests: Write capability checks
# ---------------------------------------------------------------------------

class TestWriteCapabilityChecks:
    def test_no_file_write_warns(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        write_warnings = [w for w in report.warnings if w.code == "missing_write_tool"]
        assert len(write_warnings) == 1

    def test_has_file_write_no_warning(self, verifier):
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read", "file_write"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        write_warnings = [w for w in report.warnings if w.code == "missing_write_tool"]
        assert len(write_warnings) == 0

    def test_gate_task_no_write_warning(self, verifier):
        wf = _wf(
            tasks={"gate1": {"description": "approve", "type": "approval_gate", "depends_on": []}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read"],
                          "budget": {"max_tokens": 1000, "max_cost_usd": 1.0}}},
        )
        report = verifier.verify(wf)
        write_warnings = [w for w in report.warnings if w.code == "missing_write_tool"]
        assert len(write_warnings) == 0

    def test_no_agent_no_write_warning(self, verifier):
        """Tasks without an agent (e.g. gates) should not trigger write warnings."""
        wf = _wf(
            tasks={"gate1": {"description": "approve", "type": "input_gate"}},
            agents={},
        )
        report = verifier.verify(wf)
        write_warnings = [w for w in report.warnings if w.code == "missing_write_tool"]
        assert len(write_warnings) == 0


# ---------------------------------------------------------------------------
# Tests: Manager tool restrictions
# ---------------------------------------------------------------------------

class TestManagerToolRestrictions:
    def test_manager_with_shell_exec_errors(self, verifier):
        from agentos.schemas.team import TeamConfig
        wf = WorkflowDefinition(
            name="test",
            tasks={
                "t1": TaskConfig(name="t1", description="do", agent="manager1"),
            },
            agents={
                "manager1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read", "file_write", "shell_exec"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
                "member1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read", "file_write"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
            },
            teams={
                "team1": TeamConfig(manager="manager1", members=["member1"]),
            },
        )
        report = verifier.verify(wf)
        mgr_errors = [e for e in report.errors if e.code == "manager_dangerous_tools"]
        assert len(mgr_errors) == 1
        assert "shell_exec" in mgr_errors[0].message

    def test_manager_with_web_search_errors(self, verifier):
        from agentos.schemas.team import TeamConfig
        wf = WorkflowDefinition(
            name="test",
            tasks={
                "t1": TaskConfig(name="t1", description="do", agent="manager1"),
            },
            agents={
                "manager1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read", "web_search"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
                "member1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
            },
            teams={
                "team1": TeamConfig(manager="manager1", members=["member1"]),
            },
        )
        report = verifier.verify(wf)
        mgr_errors = [e for e in report.errors if e.code == "manager_dangerous_tools"]
        assert len(mgr_errors) == 1
        assert "web_search" in mgr_errors[0].message

    def test_manager_safe_tools_no_error(self, verifier):
        from agentos.schemas.team import TeamConfig
        wf = WorkflowDefinition(
            name="test",
            tasks={
                "t1": TaskConfig(name="t1", description="do", agent="manager1"),
            },
            agents={
                "manager1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read", "file_write"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
                "member1": AgentConfig(
                    adapter="tier2_claude_code", model="test",
                    tools=["file_read", "file_write"],
                    budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0),
                ),
            },
            teams={
                "team1": TeamConfig(manager="manager1", members=["member1"]),
            },
        )
        report = verifier.verify(wf)
        mgr_errors = [e for e in report.errors if e.code == "manager_dangerous_tools"]
        assert len(mgr_errors) == 0

    def test_no_teams_no_manager_errors(self, verifier):
        """Without teams, manager tool restrictions should not fire."""
        wf = _wf(
            tasks={"t1": {"description": "do", "agent": "a1"}},
            agents={"a1": {"adapter": "tier2_claude_code", "model": "test",
                          "tools": ["file_read", "shell_exec"]}},
        )
        report = verifier.verify(wf)
        mgr_errors = [e for e in report.errors if e.code == "manager_dangerous_tools"]
        assert len(mgr_errors) == 0
