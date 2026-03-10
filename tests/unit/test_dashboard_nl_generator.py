"""Tests for the NL workflow generator."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from agentos.dashboard.nl_generator import (
    generate_workflow_yaml,
    _postfix_workflow,
    _strip_fences,
    _generate_via_cli,
    SYSTEM_PROMPT,
)


class TestNlGenerator:
    """Tests for generate_workflow_yaml."""

    def test_system_prompt_has_examples(self):
        assert "agents:" in SYSTEM_PROMPT
        assert "tasks:" in SYSTEM_PROMPT
        assert "depends_on" in SYSTEM_PROMPT
        assert "tier2_claude_code" in SYSTEM_PROMPT

    @patch.dict(os.environ, {"AGENTOS_NL_USE_API": "1"})
    def test_generate_via_api(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="name: test-workflow\nversion: '1.0'\nagents: {}\ntasks: {}")]
        mock_client.messages.create.return_value = mock_response

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = generate_workflow_yaml("Make a test workflow")

        assert "name: test-workflow" in result
        mock_client.messages.create.assert_called_once()

    @patch("subprocess.run")
    def test_generate_via_cli(self, mock_run):
        import json
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "name: cli-workflow\nversion: '1.0'\nagents: {}\ntasks: {}"}),
        )

        # Default (no AGENTOS_NL_USE_API) should use CLI
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTOS_NL_USE_API", None)
            result = generate_workflow_yaml("test")

        assert "name: cli-workflow" in result
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "--print" in cmd

    @patch("subprocess.run")
    def test_cli_timeout_raises(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="claude", timeout=120)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTOS_NL_USE_API", None)
            with pytest.raises(RuntimeError, match="timed out"):
                generate_workflow_yaml("test")

    def test_strip_fences(self):
        assert _strip_fences("```yaml\nname: test\n```") == "name: test"
        assert _strip_fences("name: test") == "name: test"
        assert _strip_fences("```\nfoo\nbar\n```") == "foo\nbar"

    def test_postfix_forces_tier2(self):
        yaml_in = "name: test\nagents:\n  a1:\n    adapter: tier1\n    tools: [web_search]\ntasks: {}"
        result = _postfix_workflow(yaml_in)
        assert "tier2_claude_code" in result
        assert "tier1" not in result

    def test_postfix_adds_required_tools(self):
        yaml_in = "name: test\nagents:\n  a1:\n    adapter: tier2_claude_code\n    tools: [web_search]\ntasks: {}"
        result = _postfix_workflow(yaml_in)
        assert "file_read" in result
        assert "file_write" in result

    def test_postfix_fixes_gate_type(self):
        yaml_in = "name: test\nagents: {}\ntasks:\n  g1:\n    type: approval\n    agent: foo"
        result = _postfix_workflow(yaml_in)
        assert "approval_gate" in result
        import yaml as y
        data = y.safe_load(result)
        assert "agent" not in data["tasks"]["g1"]

    def test_postfix_adds_default_budget(self):
        yaml_in = "name: test\nagents:\n  a1:\n    adapter: tier2_claude_code\n    tools: []\ntasks: {}"
        result = _postfix_workflow(yaml_in)
        import yaml as y
        data = y.safe_load(result)
        assert data["agents"]["a1"]["budget"]["max_tokens"] == 100000
        assert data["agents"]["a1"]["budget"]["max_cost_usd"] == 2.0

    @patch.dict(os.environ, {"AGENTOS_NL_USE_API": "1"})
    def test_api_error_raises_runtime_error(self):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API down")

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            with pytest.raises(RuntimeError, match="Workflow generation failed"):
                generate_workflow_yaml("test")
