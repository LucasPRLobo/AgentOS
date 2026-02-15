"""Tests for agent action parsing."""

from __future__ import annotations

import pytest

from agentos.lm.agent_action import AgentActionType, parse_agent_action


class TestParseAgentAction:
    """Test parse_agent_action with various input formats."""

    def test_parse_tool_call(self) -> None:
        raw = '{"action": "tool_call", "tool": "file_read", "input": {"path": "main.py"}, "reasoning": "need to read"}'
        action = parse_agent_action(raw)
        assert action.action == AgentActionType.TOOL_CALL
        assert action.tool == "file_read"
        assert action.input == {"path": "main.py"}
        assert action.reasoning == "need to read"

    def test_parse_finish(self) -> None:
        raw = '{"action": "finish", "result": "All done.", "reasoning": "task complete"}'
        action = parse_agent_action(raw)
        assert action.action == AgentActionType.FINISH
        assert action.result == "All done."
        assert action.reasoning == "task complete"

    def test_parse_json_in_markdown_code_block(self) -> None:
        raw = '```json\n{"action": "finish", "result": "Done."}\n```'
        action = parse_agent_action(raw)
        assert action.action == AgentActionType.FINISH
        assert action.result == "Done."

    def test_parse_json_in_plain_code_block(self) -> None:
        raw = 'Here is my action:\n```\n{"action": "tool_call", "tool": "grep", "input": {"pattern": "foo"}}\n```'
        action = parse_agent_action(raw)
        assert action.action == AgentActionType.TOOL_CALL
        assert action.tool == "grep"

    def test_invalid_json_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_agent_action("this is not json at all")

    def test_missing_action_field_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Missing 'action' field"):
            parse_agent_action('{"tool": "file_read"}')

    def test_json_with_surrounding_text(self) -> None:
        raw = 'I will read the file.\n{"action": "tool_call", "tool": "file_read", "input": {"path": "x.py"}}\nDone.'
        action = parse_agent_action(raw)
        assert action.action == AgentActionType.TOOL_CALL
        assert action.tool == "file_read"
