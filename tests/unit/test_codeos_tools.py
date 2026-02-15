"""Tests for CodeOS tools."""

from __future__ import annotations

import pytest

from agentos.runtime.workspace import Workspace, WorkspaceConfig
from codeos.domain.schemas import (
    FileReadInput,
    FileWriteInput,
    GrepInput,
    RunCommandInput,
)
from codeos.tools.file_read import FileReadTool
from codeos.tools.file_write import FileWriteTool
from codeos.tools.grep import GrepTool
from codeos.tools.run_command import RunCommandTool


@pytest.fixture()
def workspace(tmp_path) -> Workspace:
    config = WorkspaceConfig(
        root=str(tmp_path),
        allowed_patterns=["**"],
        allowed_commands=["echo", "ls", "cat"],
    )
    return Workspace(config)


class TestFileReadTool:
    def test_read_file(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "test.txt").write_text("line1\nline2\nline3\n")
        tool = FileReadTool(workspace)
        output = tool.execute(FileReadInput(path="test.txt"))
        assert output.lines == 3
        assert output.total_lines == 3
        assert "line1" in output.content

    def test_read_with_offset_and_limit(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "big.txt").write_text("\n".join(f"line{i}" for i in range(10)))
        tool = FileReadTool(workspace)
        output = tool.execute(FileReadInput(path="big.txt", offset=2, limit=3))
        assert output.lines == 3
        assert "line2" in output.content
        assert "line4" in output.content

    def test_read_file_not_found(self, workspace: Workspace) -> None:
        tool = FileReadTool(workspace)
        with pytest.raises(FileNotFoundError):
            tool.execute(FileReadInput(path="nonexistent.txt"))

    def test_read_outside_workspace(self, workspace: Workspace) -> None:
        tool = FileReadTool(workspace)
        with pytest.raises(ValueError, match="outside workspace root"):
            tool.execute(FileReadInput(path="../../etc/passwd"))


class TestFileWriteTool:
    def test_write_file(self, workspace: Workspace, tmp_path) -> None:
        tool = FileWriteTool(workspace)
        output = tool.execute(FileWriteInput(path="new.txt", content="hello world"))
        assert output.path == "new.txt"
        assert output.bytes_written == 11
        assert len(output.sha256) == 64
        assert (tmp_path / "new.txt").read_text() == "hello world"

    def test_write_creates_parent_dirs(self, workspace: Workspace, tmp_path) -> None:
        tool = FileWriteTool(workspace)
        tool.execute(FileWriteInput(path="sub/dir/file.txt", content="nested"))
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"

    def test_write_outside_workspace(self, workspace: Workspace) -> None:
        tool = FileWriteTool(workspace)
        with pytest.raises(ValueError, match="outside workspace root"):
            tool.execute(FileWriteInput(path="../../evil.txt", content="bad"))


class TestGrepTool:
    def test_grep_finds_matches(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "a.py").write_text("def foo():\n    pass\n")
        (tmp_path / "b.py").write_text("x = 1\ndef bar():\n    return x\n")
        tool = GrepTool(workspace)
        output = tool.execute(GrepInput(pattern="def ", path="."))
        assert len(output.matches) == 2

    def test_grep_with_glob_filter(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "a.py").write_text("match here\n")
        (tmp_path / "b.txt").write_text("match here\n")
        tool = GrepTool(workspace)
        output = tool.execute(GrepInput(pattern="match", path=".", glob="*.py"))
        assert len(output.matches) == 1
        assert output.matches[0].file == "a.py"

    def test_grep_no_matches(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "empty.txt").write_text("nothing relevant\n")
        tool = GrepTool(workspace)
        output = tool.execute(GrepInput(pattern="zzz_nonexistent"))
        assert output.matches == []


class TestRunCommandTool:
    def test_run_echo(self, workspace: Workspace) -> None:
        tool = RunCommandTool(workspace)
        output = tool.execute(RunCommandInput(command="echo hello"))
        assert output.stdout.strip() == "hello"
        assert output.exit_code == 0
        assert output.timed_out is False

    def test_disallowed_command(self, workspace: Workspace) -> None:
        tool = RunCommandTool(workspace)
        with pytest.raises(PermissionError, match="Command not allowed"):
            tool.execute(RunCommandInput(command="rm -rf /"))
