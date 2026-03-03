"""Tests for agentos.adapters.tier1 — Tier 1 API-controlled adapter.

All tests use mocked Anthropic API responses to avoid real API calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentos.adapters.tier1 import (
    TOOL_DEFINITIONS,
    Tier1Adapter,
    _build_system_prompt,
    _build_task_output,
    _estimate_cost,
    _filter_tools,
)
from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Mock helpers for the Anthropic Messages API
# ---------------------------------------------------------------------------

@dataclass
class MockUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = "Hello"


@dataclass
class MockToolUseBlock:
    type: str = "tool_use"
    id: str = "tool_1"
    name: str = "task_complete"
    input: dict = field(default_factory=lambda: {"summary": "Done."})


@dataclass
class MockResponse:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: MockUsage = field(default_factory=MockUsage)


def make_client_with_responses(*responses: MockResponse) -> MagicMock:
    """Create a mock Anthropic client that returns canned responses."""
    client = MagicMock()
    client.messages.create = MagicMock(side_effect=list(responses))
    return client


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
def budget_manager(event_log, seq):
    spec = BudgetSpec(
        max_tokens=100000,
        max_api_calls=100,
        max_time_seconds=300,
        max_cost_usd=5.0,
    )
    return BudgetManager(
        workflow_spec=spec,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )


@pytest.fixture
def tight_budget_manager(event_log, seq):
    """Budget manager with very low limits to test enforcement."""
    spec = BudgetSpec(
        max_tokens=100,
        max_api_calls=1,
        max_time_seconds=300,
        max_cost_usd=5.0,
    )
    return BudgetManager(
        workflow_spec=spec,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )


@pytest.fixture
def workspace_path(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Tests: System prompt construction
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    """Test _build_system_prompt helper."""

    def test_basic_role(self):
        prompt = _build_system_prompt("You are a researcher.", [], [])
        assert "You are a researcher." in prompt

    def test_with_predecessor_context(self):
        ctx = TaskOutput(
            task_id="t1",
            agent_id="a1",
            status=TaskStatus.SUCCEEDED,
            summary="Found 3 key issues.",
            key_findings=[Finding(finding="Issue A", confidence=Confidence.HIGH)],
            open_questions=["What about edge cases?"],
        )
        prompt = _build_system_prompt("Role.", [ctx], [])
        assert "t1" in prompt
        assert "Found 3 key issues." in prompt
        assert "Issue A" in prompt
        assert "What about edge cases?" in prompt

    def test_with_tool_allowlist(self):
        prompt = _build_system_prompt("Role.", [], ["file_read", "file_write"])
        assert "file_read" in prompt
        assert "file_write" in prompt


# ---------------------------------------------------------------------------
# Tests: Tool filtering
# ---------------------------------------------------------------------------

class TestFilterTools:
    """Test _filter_tools helper."""

    def test_filters_to_allowed_only(self):
        tools = _filter_tools(["file_read", "file_write"])
        names = {t["name"] for t in tools}
        assert "file_read" in names
        assert "file_write" in names
        assert "shell_exec" not in names

    def test_always_includes_task_complete(self):
        tools = _filter_tools(["file_read"])
        names = {t["name"] for t in tools}
        assert "task_complete" in names

    def test_empty_allowlist_still_has_task_complete(self):
        tools = _filter_tools([])
        names = {t["name"] for t in tools}
        assert "task_complete" in names
        assert len(names) == 1

    def test_unknown_tools_ignored(self):
        tools = _filter_tools(["nonexistent_tool"])
        names = {t["name"] for t in tools}
        assert "nonexistent_tool" not in names
        assert "task_complete" in names


# ---------------------------------------------------------------------------
# Tests: Cost estimation
# ---------------------------------------------------------------------------

class TestEstimateCost:
    """Test _estimate_cost helper."""

    def test_known_model(self):
        cost = _estimate_cost("claude-sonnet-4-6", 1000, 500)
        assert cost > 0

    def test_unknown_model_uses_default(self):
        cost = _estimate_cost("unknown-model", 1000, 500)
        assert cost > 0

    def test_zero_tokens_zero_cost(self):
        cost = _estimate_cost("claude-sonnet-4-6", 0, 0)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Tests: Task output building
# ---------------------------------------------------------------------------

class TestBuildTaskOutput:
    """Test _build_task_output helper."""

    def test_none_result_is_failed(self):
        output = _build_task_output(
            "t1", "a1", None, TaskMetrics()
        )
        assert output.status == TaskStatus.FAILED
        assert "did not produce" in output.summary

    def test_valid_result(self):
        result = {
            "summary": "All done.",
            "findings": [
                {"finding": "Found X", "confidence": "high", "sources": ["url1"]},
            ],
            "open_questions": ["What about Y?"],
        }
        output = _build_task_output("t1", "a1", result, TaskMetrics())
        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "All done."
        assert len(output.key_findings) == 1
        assert output.key_findings[0].confidence == Confidence.HIGH
        assert output.open_questions == ["What about Y?"]

    def test_minimal_result(self):
        output = _build_task_output("t1", "a1", {"summary": "Done."}, TaskMetrics())
        assert output.status == TaskStatus.SUCCEEDED
        assert output.key_findings == []
        assert output.open_questions == []


# ---------------------------------------------------------------------------
# Tests: Adapter execute_task
# ---------------------------------------------------------------------------

class TestTier1AdapterExecute:
    """Test the full execute_task loop with mocked API."""

    def test_simple_end_turn(self, budget_manager, workspace_path):
        """Model responds with text only (no tool calls) → succeeds."""
        response = MockResponse(
            content=[MockTextBlock(text="I completed the analysis.")],
            stop_reason="end_turn",
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        output = asyncio.run(adapter.execute_task(
            task_description="Analyze the data.",
            role="You are an analyst.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=["file_read"],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert "completed the analysis" in output.summary
        assert output.metrics is not None
        assert output.metrics.api_calls_made == 1

    def test_task_complete_tool_call(self, budget_manager, workspace_path):
        """Model calls task_complete → structured output."""
        response = MockResponse(
            content=[
                MockToolUseBlock(
                    name="task_complete",
                    id="tc_1",
                    input={
                        "summary": "Found 3 vulnerabilities.",
                        "findings": [
                            {"finding": "SQL injection in login", "confidence": "high"},
                        ],
                        "open_questions": ["Is the admin panel affected?"],
                    },
                ),
            ],
            stop_reason="tool_use",
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        output = asyncio.run(adapter.execute_task(
            task_description="Audit the code.",
            role="Security auditor.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Found 3 vulnerabilities."
        assert len(output.key_findings) == 1
        assert output.open_questions == ["Is the admin panel affected?"]

    def test_tool_call_then_complete(self, budget_manager, workspace_path):
        """Model calls file_read, then task_complete in next turn."""
        # First response: call file_read
        resp1 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="file_read",
                    id="fr_1",
                    input={"path": "data.txt"},
                ),
            ],
            stop_reason="tool_use",
        )
        # Second response: call task_complete
        resp2 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="task_complete",
                    id="tc_1",
                    input={"summary": "Read the data successfully."},
                ),
            ],
            stop_reason="tool_use",
        )
        # Pre-create the file
        (workspace_path / "data.txt").write_text("hello world")

        client = make_client_with_responses(resp1, resp2)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        output = asyncio.run(adapter.execute_task(
            task_description="Read data.txt",
            role="Reader.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=["file_read"],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert output.metrics.api_calls_made == 2

    def test_file_write_tool(self, budget_manager, workspace_path):
        """Model calls file_write, then task_complete."""
        resp1 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="file_write",
                    id="fw_1",
                    input={"path": "output.txt", "content": "result data"},
                ),
            ],
            stop_reason="tool_use",
        )
        resp2 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="task_complete",
                    id="tc_1",
                    input={"summary": "Wrote output file."},
                ),
            ],
            stop_reason="tool_use",
        )
        client = make_client_with_responses(resp1, resp2)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        output = asyncio.run(adapter.execute_task(
            task_description="Write output",
            role="Writer.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=["file_write"],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert (workspace_path / "output.txt").read_text() == "result data"

    def test_budget_enforcement_stops_execution(self, tight_budget_manager, workspace_path):
        """Exceeding budget raises BudgetExceededError during the loop."""
        # Token usage (100+50=150) exceeds tight limit of 100
        response = MockResponse(
            content=[MockTextBlock(text="Working...")],
            stop_reason="end_turn",
            usage=MockUsage(input_tokens=100, output_tokens=50),
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", tight_budget_manager, "agent1")

        with pytest.raises(BudgetExceededError):
            asyncio.run(adapter.execute_task(
                task_description="Do work.",
                role="Worker.",
                workspace=workspace_path,
                predecessor_context=[],
                allowed_tools=[],
            ))

    def test_terminate_stops_loop(self, budget_manager, workspace_path):
        """Calling terminate causes the loop to exit."""
        response = MockResponse(
            content=[MockTextBlock(text="Still working...")],
            stop_reason="end_turn",
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        # Pre-terminate
        asyncio.run(adapter.terminate())

        output = asyncio.run(adapter.execute_task(
            task_description="Do work.",
            role="Worker.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=[],
        ))

        # Should return failed since loop didn't run
        assert output.status == TaskStatus.FAILED
        client.messages.create.assert_not_called()

    def test_predecessor_context_injected(self, budget_manager, workspace_path):
        """Predecessor task outputs appear in the system prompt."""
        response = MockResponse(
            content=[MockTextBlock(text="Done.")],
            stop_reason="end_turn",
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        predecessor = TaskOutput(
            task_id="prev_task",
            agent_id="prev_agent",
            status=TaskStatus.SUCCEEDED,
            summary="Previous work completed.",
        )

        asyncio.run(adapter.execute_task(
            task_description="Continue work.",
            role="Continuator.",
            workspace=workspace_path,
            predecessor_context=[predecessor],
            allowed_tools=[],
        ))

        # Verify the system prompt passed to the API contains predecessor info
        call_kwargs = client.messages.create.call_args
        system = call_kwargs.kwargs.get("system") or call_kwargs[1].get("system")
        assert "prev_task" in system
        assert "Previous work completed." in system

    def test_tool_allowlist_passed_to_api(self, budget_manager, workspace_path):
        """Only allowed tools (plus task_complete) are sent to the API."""
        response = MockResponse(
            content=[MockTextBlock(text="Done.")],
            stop_reason="end_turn",
        )
        client = make_client_with_responses(response)
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "agent1")

        asyncio.run(adapter.execute_task(
            task_description="Read files.",
            role="Reader.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=["file_read"],
        ))

        call_kwargs = client.messages.create.call_args
        tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools")
        tool_names = {t["name"] for t in tools}
        assert "file_read" in tool_names
        assert "task_complete" in tool_names
        assert "file_write" not in tool_names
        assert "shell_exec" not in tool_names

    def test_custom_tool_handler(self, budget_manager, workspace_path):
        """Custom tool handler is called for tool dispatching."""
        handler_calls = []

        def handler(name, input_data, workspace):
            handler_calls.append((name, input_data))
            return "custom result"

        resp1 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="file_read",
                    id="fr_1",
                    input={"path": "x.txt"},
                ),
            ],
            stop_reason="tool_use",
        )
        resp2 = MockResponse(
            content=[
                MockToolUseBlock(
                    name="task_complete",
                    id="tc_1",
                    input={"summary": "Used custom handler."},
                ),
            ],
            stop_reason="tool_use",
        )
        client = make_client_with_responses(resp1, resp2)
        adapter = Tier1Adapter(
            client, "claude-sonnet-4-6", budget_manager, "agent1",
            tool_handler=handler,
        )

        asyncio.run(adapter.execute_task(
            task_description="Read x.txt",
            role="Reader.",
            workspace=workspace_path,
            predecessor_context=[],
            allowed_tools=["file_read"],
        ))

        assert len(handler_calls) == 1
        assert handler_calls[0][0] == "file_read"


class TestTier1AdapterProperties:
    """Basic adapter properties."""

    def test_tier_is_1(self, budget_manager):
        client = MagicMock()
        adapter = Tier1Adapter(client, "claude-sonnet-4-6", budget_manager, "a1")
        assert adapter.tier == 1


class TestToolDefinitions:
    """Verify tool definition structure."""

    def test_all_have_required_fields(self):
        for name, defn in TOOL_DEFINITIONS.items():
            assert "name" in defn
            assert "description" in defn
            assert "input_schema" in defn
            assert defn["name"] == name

    def test_task_complete_exists(self):
        assert "task_complete" in TOOL_DEFINITIONS
