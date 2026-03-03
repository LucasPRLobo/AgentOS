"""Tests for agentos.kernel.workspace — scoped workspace with file tracking."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace, WorkspaceError
from agentos.schemas.events import EventType
from agentos.schemas.workspace import FileManifestEntry, FileOperation, WorkspaceConfig


@pytest.fixture
def workspace_dir(tmp_path):
    """Return a temporary workspace root."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def workspace(workspace_dir, event_log, seq):
    """Standard read-write workspace."""
    config = WorkspaceConfig(root=str(workspace_dir))
    return Workspace(config, event_log, seq, workflow_id="test-wf")


@pytest.fixture
def readonly_workspace(workspace_dir, event_log, seq):
    """Read-only workspace."""
    config = WorkspaceConfig(root=str(workspace_dir), read_only=True)
    return Workspace(config, event_log, seq, workflow_id="test-wf")


@pytest.fixture
def restricted_workspace(workspace_dir, event_log, seq):
    """Workspace restricted to *.txt files only."""
    config = WorkspaceConfig(root=str(workspace_dir), allowed_patterns=["*.txt"])
    return Workspace(config, event_log, seq, workflow_id="test-wf")


class TestPathContainment:
    """Paths outside workspace root must be rejected."""

    def test_resolve_valid_path(self, workspace, workspace_dir):
        resolved = workspace.resolve_path("hello.txt")
        assert resolved == workspace_dir / "hello.txt"

    def test_resolve_nested_path(self, workspace, workspace_dir):
        resolved = workspace.resolve_path("sub/dir/file.py")
        assert resolved == workspace_dir / "sub" / "dir" / "file.py"

    def test_reject_parent_traversal(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes workspace root"):
            workspace.resolve_path("../outside.txt")

    def test_reject_absolute_path_outside(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes workspace root"):
            workspace.resolve_path("/etc/passwd")

    def test_reject_double_dot_in_middle(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes workspace root"):
            workspace.resolve_path("subdir/../../outside.txt")

    def test_dot_stays_in_root(self, workspace, workspace_dir):
        resolved = workspace.resolve_path("./hello.txt")
        assert resolved == workspace_dir / "hello.txt"


class TestWriteFile:
    """File write operations — tracking, events, and constraints."""

    def test_write_creates_file(self, workspace, workspace_dir):
        workspace.write_file("hello.txt", "Hello", agent_id="a1", task_id="t1")
        assert (workspace_dir / "hello.txt").read_text() == "Hello"

    def test_write_creates_subdirectories(self, workspace, workspace_dir):
        workspace.write_file("sub/dir/file.py", "# code", agent_id="a1", task_id="t1")
        assert (workspace_dir / "sub" / "dir" / "file.py").read_text() == "# code"

    def test_write_bytes(self, workspace, workspace_dir):
        workspace.write_file("data.bin", b"\x00\x01\x02", agent_id="a1", task_id="t1")
        assert (workspace_dir / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_write_emits_file_created_event(self, workspace, event_log):
        workspace.write_file("new.txt", "content", agent_id="a1", task_id="t1")
        events = event_log.query(event_type=EventType.FILE_CREATED)
        assert len(events) == 1
        assert events[0].payload["path"] == "new.txt"
        assert events[0].payload["operation"] == "created"
        assert events[0].payload["agent_id"] == "a1"

    def test_overwrite_emits_file_modified_event(self, workspace, event_log):
        workspace.write_file("file.txt", "v1", agent_id="a1", task_id="t1")
        workspace.write_file("file.txt", "v2", agent_id="a1", task_id="t1")
        events = event_log.query(event_type=EventType.FILE_MODIFIED)
        assert len(events) == 1
        assert events[0].payload["operation"] == "modified"

    def test_write_records_size(self, workspace, event_log):
        workspace.write_file("sized.txt", "12345", agent_id="a1", task_id="t1")
        events = event_log.query(event_type=EventType.FILE_CREATED)
        assert events[0].payload["size_bytes"] == 5

    def test_write_rejected_outside_root(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes workspace root"):
            workspace.write_file("../escape.txt", "bad", agent_id="a1", task_id="t1")


class TestReadFile:
    """File read operations."""

    def test_read_existing_file(self, workspace):
        workspace.write_file("greet.txt", "Hello", agent_id="a1", task_id="t1")
        assert workspace.read_file("greet.txt") == "Hello"

    def test_read_nonexistent_raises(self, workspace):
        with pytest.raises(WorkspaceError, match="File not found"):
            workspace.read_file("missing.txt")

    def test_read_outside_root_raises(self, workspace):
        with pytest.raises(WorkspaceError, match="escapes workspace root"):
            workspace.read_file("../../etc/passwd")


class TestDeleteFile:
    """File deletion operations."""

    def test_delete_removes_file(self, workspace, workspace_dir):
        workspace.write_file("doomed.txt", "bye", agent_id="a1", task_id="t1")
        assert (workspace_dir / "doomed.txt").exists()
        workspace.delete_file("doomed.txt", agent_id="a1", task_id="t1")
        assert not (workspace_dir / "doomed.txt").exists()

    def test_delete_emits_event(self, workspace, event_log):
        workspace.write_file("doomed.txt", "bye", agent_id="a1", task_id="t1")
        workspace.delete_file("doomed.txt", agent_id="a1", task_id="t1")
        # FILE_CREATED for write, FILE_MODIFIED for delete (no FILE_DELETED type yet)
        all_events = event_log.query(workflow_id="test-wf")
        delete_events = [
            e for e in all_events if e.payload.get("operation") == "deleted"
        ]
        assert len(delete_events) == 1
        assert delete_events[0].payload["path"] == "doomed.txt"

    def test_delete_records_in_manifest(self, workspace):
        workspace.write_file("doomed.txt", "bye", agent_id="a1", task_id="t1")
        workspace.delete_file("doomed.txt", agent_id="a1", task_id="t1")
        deleted = [e for e in workspace.manifest if e.operation == FileOperation.DELETED]
        assert len(deleted) == 1

    def test_delete_nonexistent_raises(self, workspace):
        with pytest.raises(WorkspaceError, match="File not found"):
            workspace.delete_file("ghost.txt", agent_id="a1", task_id="t1")


class TestReadOnlyWorkspace:
    """Read-only workspaces block all write operations."""

    def test_write_blocked(self, readonly_workspace):
        with pytest.raises(WorkspaceError, match="read-only"):
            readonly_workspace.write_file("nope.txt", "data", agent_id="a1", task_id="t1")

    def test_delete_blocked(self, readonly_workspace, workspace_dir):
        # Pre-create a file directly so we can try to delete it
        (workspace_dir / "existing.txt").write_text("here")
        with pytest.raises(WorkspaceError, match="read-only"):
            readonly_workspace.delete_file("existing.txt", agent_id="a1", task_id="t1")

    def test_read_allowed(self, readonly_workspace, workspace_dir):
        (workspace_dir / "readable.txt").write_text("ok")
        assert readonly_workspace.read_file("readable.txt") == "ok"


class TestAllowedPatterns:
    """Allowed patterns restrict which paths can be accessed."""

    def test_matching_pattern_allowed(self, restricted_workspace):
        restricted_workspace.write_file("notes.txt", "ok", agent_id="a1", task_id="t1")
        assert restricted_workspace.read_file("notes.txt") == "ok"

    def test_non_matching_pattern_blocked_write(self, restricted_workspace):
        with pytest.raises(WorkspaceError, match="does not match"):
            restricted_workspace.write_file("code.py", "bad", agent_id="a1", task_id="t1")

    def test_non_matching_pattern_blocked_read(self, restricted_workspace, workspace_dir):
        (workspace_dir / "secret.py").write_text("hidden")
        with pytest.raises(WorkspaceError, match="does not match"):
            restricted_workspace.read_file("secret.py")

    def test_non_matching_pattern_blocked_delete(self, restricted_workspace, workspace_dir):
        (workspace_dir / "keep.py").write_text("safe")
        with pytest.raises(WorkspaceError, match="does not match"):
            restricted_workspace.delete_file("keep.py", agent_id="a1", task_id="t1")

    def test_wildcard_allows_all(self, workspace):
        # Default workspace has ["**"] pattern
        workspace.write_file("any.py", "ok", agent_id="a1", task_id="t1")
        workspace.write_file("any.txt", "ok", agent_id="a1", task_id="t1")


class TestManifestQuery:
    """Query file manifest entries by task_id or agent_id."""

    def test_query_by_task_id(self, workspace):
        workspace.write_file("a.txt", "1", agent_id="a1", task_id="t1")
        workspace.write_file("b.txt", "2", agent_id="a1", task_id="t2")
        workspace.write_file("c.txt", "3", agent_id="a2", task_id="t1")

        t1_entries = workspace.query_manifest(task_id="t1")
        assert len(t1_entries) == 2
        assert {e.path for e in t1_entries} == {"a.txt", "c.txt"}

    def test_query_by_agent_id(self, workspace):
        workspace.write_file("a.txt", "1", agent_id="a1", task_id="t1")
        workspace.write_file("b.txt", "2", agent_id="a2", task_id="t1")

        a1_entries = workspace.query_manifest(agent_id="a1")
        assert len(a1_entries) == 1
        assert a1_entries[0].path == "a.txt"

    def test_query_combined_filters(self, workspace):
        workspace.write_file("a.txt", "1", agent_id="a1", task_id="t1")
        workspace.write_file("b.txt", "2", agent_id="a1", task_id="t2")
        workspace.write_file("c.txt", "3", agent_id="a2", task_id="t1")

        entries = workspace.query_manifest(task_id="t1", agent_id="a1")
        assert len(entries) == 1
        assert entries[0].path == "a.txt"

    def test_query_no_filters_returns_all(self, workspace):
        workspace.write_file("a.txt", "1", agent_id="a1", task_id="t1")
        workspace.write_file("b.txt", "2", agent_id="a2", task_id="t2")

        assert len(workspace.query_manifest()) == 2

    def test_query_empty_manifest(self, workspace):
        assert workspace.query_manifest(task_id="t1") == []


class TestListFiles:
    """List all files in the workspace."""

    def test_list_empty(self, workspace):
        assert workspace.list_files() == []

    def test_list_after_writes(self, workspace):
        workspace.write_file("a.txt", "1", agent_id="a1", task_id="t1")
        workspace.write_file("sub/b.txt", "2", agent_id="a1", task_id="t1")
        files = workspace.list_files()
        assert "a.txt" in files
        assert "sub/b.txt" in files


class TestCleanup:
    """Workspace cleanup removes the root directory."""

    def test_cleanup_removes_root(self, workspace, workspace_dir):
        workspace.write_file("file.txt", "data", agent_id="a1", task_id="t1")
        assert workspace_dir.exists()
        workspace.cleanup()
        assert not workspace_dir.exists()

    def test_cleanup_nonexistent_root_is_noop(self, event_log, seq, tmp_path):
        config = WorkspaceConfig(root=str(tmp_path / "nonexistent"))
        ws = Workspace(config, event_log, seq, workflow_id="test-wf")
        ws.cleanup()  # Should not raise


class TestEnsureRoot:
    """ensure_root creates the root directory."""

    def test_creates_missing_root(self, event_log, seq, tmp_path):
        root = tmp_path / "new_workspace"
        config = WorkspaceConfig(root=str(root))
        ws = Workspace(config, event_log, seq, workflow_id="test-wf")
        assert not root.exists()
        ws.ensure_root()
        assert root.exists()

    def test_idempotent_on_existing(self, workspace, workspace_dir):
        assert workspace_dir.exists()
        workspace.ensure_root()  # Should not raise
        assert workspace_dir.exists()
