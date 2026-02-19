"""Unit tests for WorkspaceManifest — in-memory file tracking."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agentos.runtime.workspace_manifest import WorkspaceFileEntry, WorkspaceManifest


class TestWorkspaceManifest:
    def test_record_new_file(self) -> None:
        m = WorkspaceManifest()
        is_new, entry = m.record_file("report.md", 1024, "sha_abc", "Writer")
        assert is_new is True
        assert entry.path == "report.md"
        assert entry.size_bytes == 1024
        assert entry.sha256 == "sha_abc"
        assert entry.created_by_agent == "Writer"

    def test_record_existing_file(self) -> None:
        m = WorkspaceManifest()
        m.record_file("report.md", 1024, "sha_abc", "Writer")
        is_new, entry = m.record_file("report.md", 2048, "sha_def", "Editor")
        assert is_new is False
        assert entry.size_bytes == 2048
        assert entry.created_by_agent == "Editor"

    def test_list_files(self) -> None:
        m = WorkspaceManifest()
        m.record_file("b.txt", 100, "sha1", "Agent1")
        m.record_file("a.txt", 200, "sha2", "Agent2")
        files = m.list_files()
        assert len(files) == 2
        assert files[0].path == "a.txt"  # sorted
        assert files[1].path == "b.txt"

    def test_files_by_agent(self) -> None:
        m = WorkspaceManifest()
        m.record_file("a.txt", 100, "sha1", "Alice")
        m.record_file("b.txt", 200, "sha2", "Bob")
        m.record_file("c.txt", 300, "sha3", "Alice")
        alice_files = m.files_by_agent("Alice")
        assert len(alice_files) == 2
        assert all(f.created_by_agent == "Alice" for f in alice_files)
        bob_files = m.files_by_agent("Bob")
        assert len(bob_files) == 1

    def test_files_by_agent_empty(self) -> None:
        m = WorkspaceManifest()
        assert m.files_by_agent("Nobody") == []

    def test_get_file(self) -> None:
        m = WorkspaceManifest()
        m.record_file("report.md", 1024, "sha_abc")
        entry = m.get_file("report.md")
        assert entry is not None
        assert entry.path == "report.md"
        assert m.get_file("nonexistent.txt") is None

    def test_snapshot(self) -> None:
        m = WorkspaceManifest()
        m.record_file("x.md", 500, "sha_x", "Agent")
        snap = m.snapshot()
        assert snap["file_count"] == 1
        assert len(snap["files"]) == 1
        assert snap["files"][0]["path"] == "x.md"

    def test_snapshot_empty(self) -> None:
        m = WorkspaceManifest()
        snap = m.snapshot()
        assert snap["file_count"] == 0
        assert snap["files"] == []

    def test_scan_workspace(self, tmp_path: Path) -> None:
        # Create some files
        (tmp_path / "hello.txt").write_text("hello")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.md").write_text("# Title")

        m = WorkspaceManifest()
        m.scan_workspace(tmp_path)
        files = m.list_files()
        assert len(files) == 2
        paths = {f.path for f in files}
        assert "hello.txt" in paths
        assert "sub/nested.md" in paths

    def test_scan_skips_hidden_files(self, tmp_path: Path) -> None:
        (tmp_path / "visible.txt").write_text("ok")
        (tmp_path / "events.db").write_text("skip")
        (tmp_path / ".hidden").write_text("skip")

        m = WorkspaceManifest()
        m.scan_workspace(tmp_path)
        files = m.list_files()
        assert len(files) == 1
        assert files[0].path == "visible.txt"

    def test_scan_preserves_existing_entries(self, tmp_path: Path) -> None:
        (tmp_path / "report.md").write_text("content")
        m = WorkspaceManifest()
        m.record_file("report.md", 999, "known_sha", "Agent")
        m.scan_workspace(tmp_path)
        entry = m.get_file("report.md")
        assert entry is not None
        assert entry.size_bytes == 999  # preserved, not overwritten by scan
        assert entry.created_by_agent == "Agent"

    def test_thread_safety(self) -> None:
        m = WorkspaceManifest()
        errors: list[Exception] = []

        def writer(n: int) -> None:
            try:
                for i in range(50):
                    m.record_file(f"file_{n}_{i}.txt", i, f"sha_{n}_{i}", f"agent_{n}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        files = m.list_files()
        assert len(files) == 200  # 4 threads × 50 files
