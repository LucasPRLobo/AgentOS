"""Tests for the HTTP request tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agentplatform.tools.http_request import (
    HTTPRequestInput,
    HTTPRequestOutput,
    HTTPRequestTool,
)


class TestHTTPRequestToolInterface:
    def test_tool_name(self) -> None:
        tool = HTTPRequestTool()
        assert tool.name == "http_request"

    def test_side_effect_read(self) -> None:
        from agentos.tools.base import SideEffect

        tool = HTTPRequestTool()
        assert tool.side_effect == SideEffect.READ

    def test_schemas(self) -> None:
        tool = HTTPRequestTool()
        assert tool.input_schema is HTTPRequestInput
        assert tool.output_schema is HTTPRequestOutput


class TestHTTPRequestExecution:
    @patch("agentplatform.tools.http_request.urllib.request.urlopen")
    def test_get_request(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.status = 200
        mock_resp.getheaders.return_value = [("Content-Type", "application/json")]
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        tool = HTTPRequestTool()
        inp = HTTPRequestInput(url="https://api.example.com/data")
        result = tool.execute(inp)
        assert isinstance(result, HTTPRequestOutput)
        assert result.status_code == 200
        assert result.error is None
        assert "ok" in result.body
        assert result.elapsed_ms >= 0

    @patch("agentplatform.tools.http_request.urllib.request.urlopen")
    def test_post_with_body(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"id": 123}'
        mock_resp.status = 201
        mock_resp.getheaders.return_value = []
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        tool = HTTPRequestTool()
        inp = HTTPRequestInput(
            method="POST",
            url="https://api.example.com/items",
            headers={"Content-Type": "application/json"},
            body='{"name": "test"}',
        )
        result = tool.execute(inp)
        assert result.status_code == 201
        assert "123" in result.body

    @patch("agentplatform.tools.http_request.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        error = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None  # type: ignore
        )
        error.read = MagicMock(return_value=b"not found")
        mock_urlopen.side_effect = error

        tool = HTTPRequestTool()
        inp = HTTPRequestInput(url="https://example.com/missing")
        result = tool.execute(inp)
        assert result.status_code == 404

    @patch("agentplatform.tools.http_request.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        tool = HTTPRequestTool()
        inp = HTTPRequestInput(url="https://unreachable.example.com")
        result = tool.execute(inp)
        assert result.error is not None
        assert "failed" in result.error.lower()
