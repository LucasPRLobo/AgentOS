"""Tests for the sandboxed code execution tool."""

from __future__ import annotations

import sys

import pytest

from agentplatform.tools.code_execute import (
    CodeExecuteInput,
    CodeExecuteOutput,
    CodeExecuteTool,
)


class TestCodeExecuteToolInterface:
    def test_tool_name(self) -> None:
        tool = CodeExecuteTool()
        assert tool.name == "code_execute"

    def test_side_effect_write(self) -> None:
        from agentos.tools.base import SideEffect

        tool = CodeExecuteTool()
        assert tool.side_effect == SideEffect.WRITE

    def test_schemas(self) -> None:
        tool = CodeExecuteTool()
        assert tool.input_schema is CodeExecuteInput
        assert tool.output_schema is CodeExecuteOutput


class TestCodeExecutePython:
    def test_simple_print(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(language="python", code="print('hello')")
        result = tool.execute(inp)
        assert isinstance(result, CodeExecuteOutput)
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_stderr_output(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(
            language="python",
            code="import sys; sys.stderr.write('warning\\n')",
        )
        result = tool.execute(inp)
        assert result.exit_code == 0
        assert "warning" in result.stderr

    def test_exit_code_nonzero(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(language="python", code="exit(42)")
        result = tool.execute(inp)
        assert result.exit_code == 42

    def test_syntax_error(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(language="python", code="def :")
        result = tool.execute(inp)
        assert result.exit_code != 0
        assert "SyntaxError" in result.stderr

    def test_timeout(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(
            language="python",
            code="import time; time.sleep(60)",
            timeout_seconds=1,
        )
        result = tool.execute(inp)
        assert result.timed_out is True

    def test_workspace_dir_is_cwd(self, tmp_path) -> None:
        tool = CodeExecuteTool(workspace_dir=tmp_path)
        inp = CodeExecuteInput(
            language="python",
            code="import os; print(os.getcwd())",
        )
        result = tool.execute(inp)
        assert str(tmp_path) in result.stdout


class TestCodeExecuteRestrictions:
    def test_restricted_env(self) -> None:
        env = CodeExecuteTool._restricted_env()
        assert "PYTHONDONTWRITEBYTECODE" in env
        # Should have a minimal set of keys
        assert len(env) <= 10
