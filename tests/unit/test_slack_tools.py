"""Tests for Slack integration tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agentplatform.tools.slack import (
    SlackMessage,
    SlackPostInput,
    SlackPostOutput,
    SlackPostTool,
    SlackReadInput,
    SlackReadOutput,
    SlackReadTool,
)


class TestSlackPostTool:
    def test_tool_name(self) -> None:
        tool = SlackPostTool()
        assert tool.name == "slack_post"

    def test_side_effect_write(self) -> None:
        from agentos.tools.base import SideEffect

        tool = SlackPostTool()
        assert tool.side_effect == SideEffect.WRITE

    def test_missing_token_returns_error(self) -> None:
        tool = SlackPostTool()
        inp = SlackPostInput(channel="#general", text="hello")
        result = tool.execute(inp)
        assert isinstance(result, SlackPostOutput)
        assert result.error is not None
        assert "not configured" in result.error

    @patch("agentplatform.tools.slack._slack_api")
    def test_successful_post(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"ok": True, "ts": "1234.5678", "channel": "C123"}

        tool = SlackPostTool(bot_token="xoxb-test")
        inp = SlackPostInput(channel="#general", text="hello")
        result = tool.execute(inp)
        assert result.ok is True
        assert result.ts == "1234.5678"
        assert result.error is None

    @patch("agentplatform.tools.slack._slack_api")
    def test_api_error(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {"ok": False, "error": "channel_not_found"}

        tool = SlackPostTool(bot_token="xoxb-test")
        inp = SlackPostInput(channel="#nonexistent", text="hello")
        result = tool.execute(inp)
        assert result.ok is False
        assert "channel_not_found" in (result.error or "")


class TestSlackReadTool:
    def test_tool_name(self) -> None:
        tool = SlackReadTool()
        assert tool.name == "slack_read"

    def test_side_effect_read(self) -> None:
        from agentos.tools.base import SideEffect

        tool = SlackReadTool()
        assert tool.side_effect == SideEffect.READ

    def test_missing_token_returns_error(self) -> None:
        tool = SlackReadTool()
        inp = SlackReadInput(channel="C123")
        result = tool.execute(inp)
        assert isinstance(result, SlackReadOutput)
        assert result.error is not None

    @patch("agentplatform.tools.slack._slack_api")
    def test_successful_read(self, mock_api: MagicMock) -> None:
        mock_api.return_value = {
            "ok": True,
            "messages": [
                {"user": "U123", "text": "hello", "ts": "1234.5678"},
                {"user": "U456", "text": "world", "ts": "1234.5679"},
            ],
            "has_more": False,
        }

        tool = SlackReadTool(bot_token="xoxb-test")
        inp = SlackReadInput(channel="C123")
        result = tool.execute(inp)
        assert result.error is None
        assert len(result.messages) == 2
        assert result.messages[0].text == "hello"
        assert result.has_more is False
