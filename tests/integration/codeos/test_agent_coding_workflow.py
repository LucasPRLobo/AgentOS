"""Integration tests for the CodeOS agent coding workflow."""

from __future__ import annotations

import json

import pytest

from agentos.governance.permissions import (
    PermissionPolicy,
    PermissionRule,
    PolicyAction,
)
from agentos.lm.agent_config import AgentConfig
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.workspace import WorkspaceConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.tools.base import SideEffect
from codeos.workflows.agent_coding import run_coding_agent
from tests.conftest import MockLMProvider, assert_has_event


def _tool_call(tool: str, inp: dict, reasoning: str = "") -> str:
    return json.dumps({"action": "tool_call", "tool": tool, "input": inp, "reasoning": reasoning})


def _finish(result: str = "Done.") -> str:
    return json.dumps({"action": "finish", "result": result})


@pytest.mark.integration
class TestAgentCodingWorkflow:
    def test_full_workflow_with_file_operations(self, tmp_path) -> None:
        """Full workflow: write a file, read it back, finish."""
        responses = [
            _tool_call("file_write", {"path": "hello.txt", "content": "Hello, World!"}),
            _tool_call("file_read", {"path": "hello.txt"}),
            _finish("Created and verified hello.txt"),
        ]
        lm = MockLMProvider(responses)
        event_log = SQLiteEventLog(":memory:")
        ws_config = WorkspaceConfig(
            root=str(tmp_path),
            allowed_commands=["echo"],
        )

        rid, result = run_coding_agent(
            "Create a hello.txt file",
            lm,
            ws_config,
            event_log=event_log,
        )

        assert result == "Created and verified hello.txt"
        assert (tmp_path / "hello.txt").read_text() == "Hello, World!"

        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_STARTED, executor="AgentRunner")
        assert_has_event(events, EventType.RUN_FINISHED, outcome="SUCCEEDED")
        assert_has_event(events, EventType.TOOL_CALL_STARTED, tool_name="file_write")
        assert_has_event(events, EventType.TOOL_CALL_STARTED, tool_name="file_read")

    def test_event_sequence_complete(self, tmp_path) -> None:
        """Verify complete event sequence for a single tool call."""
        responses = [
            _tool_call("file_write", {"path": "test.py", "content": "print('hi')"}),
            _finish("Done"),
        ]
        lm = MockLMProvider(responses)
        event_log = SQLiteEventLog(":memory:")
        ws_config = WorkspaceConfig(root=str(tmp_path))

        rid, _ = run_coding_agent("Write test.py", lm, ws_config, event_log=event_log)

        events = event_log.query_by_run(rid)
        types = [e.event_type for e in events]

        assert types[0] == EventType.RUN_STARTED
        assert types[-1] == EventType.RUN_FINISHED
        assert EventType.AGENT_STEP_STARTED in types
        assert EventType.AGENT_STEP_FINISHED in types
        assert EventType.TOOL_CALL_STARTED in types
        assert EventType.TOOL_CALL_FINISHED in types

    def test_workspace_scoping_enforced(self, tmp_path) -> None:
        """Workspace rejects path traversal attempts."""
        responses = [
            _tool_call("file_read", {"path": "../../etc/passwd"}),
            _finish("Failed to escape"),
        ]
        lm = MockLMProvider(responses)
        event_log = SQLiteEventLog(":memory:")
        ws_config = WorkspaceConfig(root=str(tmp_path))

        rid, result = run_coding_agent(
            "Try to escape workspace",
            lm,
            ws_config,
            event_log=event_log,
        )

        # The agent should receive an error and then finish
        assert result == "Failed to escape"
        events = event_log.query_by_run(rid)
        # Tool call should have failed
        assert_has_event(events, EventType.TOOL_CALL_FINISHED, success=False)

    def test_budget_limits_respected(self, tmp_path) -> None:
        """Budget enforcement halts the agent."""
        responses = [_tool_call("file_write", {"path": f"f{i}.txt", "content": "x"}) for i in range(20)]
        lm = MockLMProvider(responses)
        event_log = SQLiteEventLog(":memory:")
        ws_config = WorkspaceConfig(root=str(tmp_path))
        budget = BudgetSpec(
            max_tokens=100_000,
            max_tool_calls=2,
            max_time_seconds=60.0,
            max_recursion_depth=5,
        )

        rid, result = run_coding_agent(
            "Write many files",
            lm,
            ws_config,
            event_log=event_log,
            budget_spec=budget,
        )

        assert result is None
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="BUDGET_EXCEEDED")

    def test_permission_denial_handled(self, tmp_path) -> None:
        """Agent receives feedback when permissions deny a tool."""
        responses = [
            _tool_call("file_write", {"path": "test.txt", "content": "data"}),
            _finish("Could not write"),
        ]
        lm = MockLMProvider(responses)
        event_log = SQLiteEventLog(":memory:")
        ws_config = WorkspaceConfig(root=str(tmp_path))
        policy = PermissionPolicy(
            rules=[
                PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
                PermissionRule(
                    side_effect=SideEffect.WRITE,
                    action=PolicyAction.DENY,
                    reason="Read-only mode",
                ),
            ],
            default_action=PolicyAction.DENY,
        )

        rid, result = run_coding_agent(
            "Write a file",
            lm,
            ws_config,
            event_log=event_log,
            permission_policy=policy,
        )

        assert result == "Could not write"
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.POLICY_DECISION, action="DENY")
