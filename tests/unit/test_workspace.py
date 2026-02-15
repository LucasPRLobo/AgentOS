"""Tests for the Workspace abstraction."""

from __future__ import annotations

import pytest

from agentos.runtime.workspace import Workspace, WorkspaceConfig


@pytest.fixture()
def workspace(tmp_path) -> Workspace:
    """Create a workspace rooted at a temp directory."""
    config = WorkspaceConfig(
        root=str(tmp_path),
        allowed_patterns=["*.py", "src/**"],
        allowed_commands=["python", "git", "pytest"],
    )
    return Workspace(config)


@pytest.fixture()
def workspace_default(tmp_path) -> Workspace:
    """Create a workspace with default (permissive) patterns."""
    config = WorkspaceConfig(root=str(tmp_path))
    return Workspace(config)


class TestWorkspacePathResolution:
    def test_path_within_root_allowed(self, workspace: Workspace, tmp_path) -> None:
        # Create a file so path resolution works
        (tmp_path / "test.py").touch()
        resolved = workspace.resolve_path("test.py")
        assert resolved == tmp_path / "test.py"

    def test_path_outside_root_rejected(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="outside workspace root"):
            workspace.resolve_path("../../etc/passwd")

    def test_path_traversal_rejected(self, workspace: Workspace) -> None:
        with pytest.raises(ValueError, match="outside workspace root"):
            workspace.resolve_path("../../../tmp/evil")

    def test_resolve_nested_path(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "src").mkdir()
        resolved = workspace.resolve_path("src/main.py")
        assert resolved == tmp_path / "src" / "main.py"


class TestWorkspacePathAllowed:
    def test_allowed_pattern_matches(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "test.py").touch()
        assert workspace.is_path_allowed("test.py") is True

    def test_allowed_pattern_no_match(self, workspace: Workspace, tmp_path) -> None:
        (tmp_path / "readme.txt").touch()
        assert workspace.is_path_allowed("readme.txt") is False

    def test_path_outside_root_not_allowed(self, workspace: Workspace) -> None:
        assert workspace.is_path_allowed("../../etc/passwd") is False

    def test_default_pattern_allows_all(self, workspace_default: Workspace, tmp_path) -> None:
        (tmp_path / "anything.txt").touch()
        assert workspace_default.is_path_allowed("anything.txt") is True


class TestWorkspaceCommands:
    def test_allowed_command(self, workspace: Workspace) -> None:
        assert workspace.is_command_allowed("python script.py") is True
        assert workspace.is_command_allowed("git status") is True
        assert workspace.is_command_allowed("pytest tests/") is True

    def test_disallowed_command(self, workspace: Workspace) -> None:
        assert workspace.is_command_allowed("rm -rf /") is False
        assert workspace.is_command_allowed("curl http://evil.com") is False

    def test_empty_allowlist_blocks_all(self, tmp_path) -> None:
        config = WorkspaceConfig(root=str(tmp_path), allowed_commands=[])
        ws = Workspace(config)
        assert ws.is_command_allowed("python") is False

    def test_empty_command_blocked(self, workspace: Workspace) -> None:
        assert workspace.is_command_allowed("") is False


class TestWorkspaceReadOnly:
    def test_read_only_flag(self, tmp_path) -> None:
        config = WorkspaceConfig(root=str(tmp_path), read_only=True)
        ws = Workspace(config)
        assert ws.config.read_only is True

    def test_not_read_only_by_default(self, tmp_path) -> None:
        config = WorkspaceConfig(root=str(tmp_path))
        ws = Workspace(config)
        assert ws.config.read_only is False
