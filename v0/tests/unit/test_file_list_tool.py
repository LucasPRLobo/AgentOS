"""Tests for the file list tool."""

from __future__ import annotations

import pytest

from agentplatform.tools.file_list import (
    FileListInput,
    FileListOutput,
    FileListTool,
)


class TestFileListToolInterface:
    def test_tool_name(self) -> None:
        tool = FileListTool()
        assert tool.name == "file_list"

    def test_side_effect_read(self) -> None:
        from agentos.tools.base import SideEffect

        tool = FileListTool()
        assert tool.side_effect == SideEffect.READ


class TestFileListExecution:
    def test_list_directory(self, tmp_path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.py").write_text("world")
        (tmp_path / "sub").mkdir()

        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path=".")
        result = tool.execute(inp)
        assert isinstance(result, FileListOutput)
        assert result.error is None
        assert result.total >= 3
        names = {e.name for e in result.entries}
        assert "a.txt" in names
        assert "b.py" in names

    def test_glob_pattern(self, tmp_path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.py").write_text("world")

        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path=".", pattern="*.py")
        result = tool.execute(inp)
        assert result.total == 1
        assert result.entries[0].name == "b.py"

    def test_recursive(self, tmp_path) -> None:
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        (sub / "inner.txt").write_text("inner")
        (tmp_path / "top.txt").write_text("top")

        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path=".", pattern="*.txt", recursive=True)
        result = tool.execute(inp)
        assert result.total == 2
        paths = {e.path for e in result.entries}
        assert any("inner.txt" in p for p in paths)

    def test_nonexistent_directory(self, tmp_path) -> None:
        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path="nonexistent")
        result = tool.execute(inp)
        assert result.error is not None
        assert "Not a directory" in result.error

    def test_path_traversal_blocked(self, tmp_path) -> None:
        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path="../../etc")
        result = tool.execute(inp)
        assert result.error is not None
        assert "outside workspace" in result.error

    def test_max_entries_truncation(self, tmp_path) -> None:
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text(str(i))

        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path=".", pattern="*.txt", max_entries=3)
        result = tool.execute(inp)
        assert result.total == 3
        assert result.truncated is True

    def test_file_type_detection(self, tmp_path) -> None:
        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()

        tool = FileListTool(workspace_dir=tmp_path)
        inp = FileListInput(path=".")
        result = tool.execute(inp)
        types = {e.name: e.type for e in result.entries}
        assert types["file.txt"] == "file"
        assert types["subdir"] == "directory"
