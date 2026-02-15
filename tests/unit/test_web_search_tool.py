"""Tests for the web search tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agentplatform.tools.web_search import (
    WebSearchInput,
    WebSearchOutput,
    WebSearchTool,
)


class TestWebSearchToolInterface:
    def test_tool_name(self) -> None:
        tool = WebSearchTool()
        assert tool.name == "web_search"

    def test_tool_version(self) -> None:
        tool = WebSearchTool()
        assert tool.version == "1.0.0"

    def test_side_effect_read(self) -> None:
        from agentos.tools.base import SideEffect

        tool = WebSearchTool()
        assert tool.side_effect == SideEffect.READ

    def test_input_schema(self) -> None:
        tool = WebSearchTool()
        assert tool.input_schema is WebSearchInput

    def test_output_schema(self) -> None:
        tool = WebSearchTool()
        assert tool.output_schema is WebSearchOutput


class TestWebSearchBrave:
    def test_missing_api_key_returns_error(self) -> None:
        tool = WebSearchTool()
        inp = WebSearchInput(query="test", engine="brave")
        result = tool.execute(inp)
        assert isinstance(result, WebSearchOutput)
        assert result.error is not None
        assert "API key" in result.error

    @patch("agentplatform.tools.web_search.urllib.request.urlopen")
    def test_successful_search(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "web": {
                "results": [
                    {"title": "Result 1", "url": "https://example.com/1", "description": "Snippet 1"},
                    {"title": "Result 2", "url": "https://example.com/2", "description": "Snippet 2"},
                ]
            }
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        tool = WebSearchTool(brave_api_key="test-key")
        inp = WebSearchInput(query="python tutorial", max_results=5, engine="brave")
        result = tool.execute(inp)
        assert isinstance(result, WebSearchOutput)
        assert result.error is None
        assert len(result.results) == 2
        assert result.results[0].title == "Result 1"
        assert result.engine == "brave"

    @patch("agentplatform.tools.web_search.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        tool = WebSearchTool(brave_api_key="test-key")
        inp = WebSearchInput(query="test", engine="brave")
        result = tool.execute(inp)
        assert result.error is not None
        assert "failed" in result.error.lower()


class TestWebSearchGoogle:
    def test_missing_credentials_returns_error(self) -> None:
        tool = WebSearchTool()
        inp = WebSearchInput(query="test", engine="google")
        result = tool.execute(inp)
        assert result.error is not None
        assert "not configured" in result.error

    @patch("agentplatform.tools.web_search.urllib.request.urlopen")
    def test_successful_search(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "items": [
                {"title": "Google 1", "link": "https://example.com/g1", "snippet": "G snippet"},
            ]
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        tool = WebSearchTool(google_api_key="gkey", google_cx="cx123")
        inp = WebSearchInput(query="test", engine="google")
        result = tool.execute(inp)
        assert result.error is None
        assert len(result.results) == 1
        assert result.results[0].url == "https://example.com/g1"
        assert result.engine == "google"
