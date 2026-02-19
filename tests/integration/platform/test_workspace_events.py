"""Integration tests for workspace snapshot events and file event tracking."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.workspace_manifest import WorkspaceManifest
from agentos.schemas.events import (
    EventType,
    FileCreated,
    FileModified,
    WorkspaceSnapshot,
)


@pytest.mark.integration
class TestWorkspaceSnapshotEvents:
    def test_pre_and_post_snapshots(self) -> None:
        """Two WORKSPACE_SNAPSHOT events can be recorded for a run."""
        event_log = SQLiteEventLog(":memory:")
        run_id = generate_run_id()
        manifest = WorkspaceManifest()

        # Pre-run snapshot (empty workspace)
        event_log.append(
            WorkspaceSnapshot(
                run_id=run_id,
                seq=0,
                payload={"phase": "pre_run", **manifest.snapshot()},
            )
        )

        # Simulate agent creating files
        manifest.record_file("outline.md", 4300, "sha_outline", "Outliner")
        event_log.append(
            FileCreated(
                run_id=run_id,
                seq=1,
                payload={
                    "file_path": "outline.md",
                    "size_bytes": 4300,
                    "sha256": "sha_outline",
                    "created_by_agent": "Outliner",
                },
            )
        )

        # Post-run snapshot (with files)
        event_log.append(
            WorkspaceSnapshot(
                run_id=run_id,
                seq=2,
                payload={"phase": "post_run", **manifest.snapshot()},
            )
        )

        events = event_log.replay(run_id)
        assert len(events) == 3

        # Pre-run snapshot
        pre = events[0]
        assert pre.event_type == EventType.WORKSPACE_SNAPSHOT
        assert pre.payload["phase"] == "pre_run"
        assert pre.payload["file_count"] == 0

        # File event
        assert events[1].event_type == EventType.FILE_CREATED

        # Post-run snapshot
        post = events[2]
        assert post.event_type == EventType.WORKSPACE_SNAPSHOT
        assert post.payload["phase"] == "post_run"
        assert post.payload["file_count"] == 1
        assert post.payload["files"][0]["path"] == "outline.md"

    def test_post_snapshot_includes_all_files(self) -> None:
        """Post-run snapshot captures all files created during the run."""
        event_log = SQLiteEventLog(":memory:")
        run_id = generate_run_id()
        manifest = WorkspaceManifest()

        manifest.record_file("a.md", 100, "sha_a", "Agent1")
        manifest.record_file("b.md", 200, "sha_b", "Agent2")
        manifest.record_file("a.md", 150, "sha_a2", "Agent3")  # Modified

        event_log.append(
            WorkspaceSnapshot(
                run_id=run_id,
                seq=0,
                payload={"phase": "post_run", **manifest.snapshot()},
            )
        )

        events = event_log.replay(run_id)
        snap = events[0]
        assert snap.payload["file_count"] == 2  # a.md and b.md (a.md updated)

    def test_pre_snapshot_captures_existing_files(self, tmp_path: Path) -> None:
        """scan_workspace picks up pre-existing files for pre-run snapshot."""
        (tmp_path / "existing.txt").write_text("hello")
        manifest = WorkspaceManifest()
        manifest.scan_workspace(tmp_path)

        snap = manifest.snapshot()
        assert snap["file_count"] == 1
        assert snap["files"][0]["path"] == "existing.txt"
