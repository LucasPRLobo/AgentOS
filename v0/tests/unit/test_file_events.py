"""Unit tests for FILE_CREATED / FILE_MODIFIED event types."""

from __future__ import annotations

from agentos.core.identifiers import generate_run_id
from agentos.schemas.events import (
    EventType,
    FileCreated,
    FileModified,
)


class TestFileEventTypes:
    def test_file_created_event_type_value(self) -> None:
        assert EventType.FILE_CREATED.value == "FileCreated"

    def test_file_modified_event_type_value(self) -> None:
        assert EventType.FILE_MODIFIED.value == "FileModified"

    def test_file_created_construction(self) -> None:
        run_id = generate_run_id()
        event = FileCreated(
            run_id=run_id,
            seq=0,
            payload={
                "file_path": "report.md",
                "size_bytes": 1024,
                "sha256": "abc123",
                "created_by_agent": "Writer",
            },
        )
        assert event.event_type == EventType.FILE_CREATED
        assert event.payload["file_path"] == "report.md"
        assert event.payload["created_by_agent"] == "Writer"

    def test_file_modified_construction(self) -> None:
        run_id = generate_run_id()
        event = FileModified(
            run_id=run_id,
            seq=1,
            payload={
                "file_path": "report.md",
                "size_bytes": 2048,
                "sha256": "def456",
                "created_by_agent": "Editor",
            },
        )
        assert event.event_type == EventType.FILE_MODIFIED
        assert event.payload["size_bytes"] == 2048
