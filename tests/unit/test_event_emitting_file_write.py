"""Unit tests for EventEmittingFileWriteTool wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from agentos.core.identifiers import RunId, generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.workspace_manifest import WorkspaceManifest
from agentos.schemas.events import EventType
from agentos.tools.base import BaseTool, SideEffect
from agentplatform.tools.workspace_aware import EventEmittingFileWriteTool


class _FakeWriteInput(BaseModel):
    path: str = ""
    content: str = ""


class _FakeWriteOutput(BaseModel):
    path: str = ""
    bytes_written: int = 0
    sha256: str = ""


class _FakeFileWriteTool(BaseTool):
    """Minimal fake file_write tool for testing."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _FakeWriteInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _FakeWriteOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        if self._should_fail:
            raise RuntimeError("Write failed")
        return _FakeWriteOutput(
            path=getattr(input_data, "path", "test.txt"),
            bytes_written=42,
            sha256="sha_test_123",
        )


@pytest.fixture()
def event_log() -> SQLiteEventLog:
    return SQLiteEventLog(":memory:")


@pytest.fixture()
def manifest() -> WorkspaceManifest:
    return WorkspaceManifest()


@pytest.fixture()
def run_id() -> RunId:
    return generate_run_id()


class TestEventEmittingFileWriteTool:
    def test_new_file_emits_file_created(self, event_log, manifest, run_id) -> None:
        inner = _FakeFileWriteTool()
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Writer",
        )
        output = wrapper.execute(_FakeWriteInput(path="report.md", content="hello"))
        assert output.path == "report.md"

        events = event_log.replay(run_id)
        assert len(events) == 1
        assert events[0].event_type == EventType.FILE_CREATED
        assert events[0].payload["file_path"] == "report.md"
        assert events[0].payload["created_by_agent"] == "Writer"

    def test_existing_file_emits_file_modified(self, event_log, manifest, run_id) -> None:
        # Pre-record the file
        manifest.record_file("report.md", 100, "old_sha", "Writer")

        inner = _FakeFileWriteTool()
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Editor",
        )
        wrapper.execute(_FakeWriteInput(path="report.md", content="updated"))

        events = event_log.replay(run_id)
        assert len(events) == 1
        assert events[0].event_type == EventType.FILE_MODIFIED

    def test_manifest_updated_after_write(self, event_log, manifest, run_id) -> None:
        inner = _FakeFileWriteTool()
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Writer",
        )
        wrapper.execute(_FakeWriteInput(path="data.csv", content="a,b,c"))

        entry = manifest.get_file("data.csv")
        assert entry is not None
        assert entry.size_bytes == 42
        assert entry.created_by_agent == "Writer"

    def test_error_no_event_emitted(self, event_log, manifest, run_id) -> None:
        inner = _FakeFileWriteTool(should_fail=True)
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Writer",
        )
        with pytest.raises(RuntimeError, match="Write failed"):
            wrapper.execute(_FakeWriteInput(path="bad.txt"))

        events = event_log.replay(run_id)
        assert len(events) == 0

    def test_delegates_properties(self, event_log, manifest, run_id) -> None:
        inner = _FakeFileWriteTool()
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Writer",
        )
        assert wrapper.name == "file_write"
        assert wrapper.version == "1.0.0"
        assert wrapper.side_effect == SideEffect.WRITE
        assert wrapper.input_schema is _FakeWriteInput
        assert wrapper.output_schema is _FakeWriteOutput

    def test_multiple_writes_increment_seq(self, event_log, manifest, run_id) -> None:
        inner = _FakeFileWriteTool()
        wrapper = EventEmittingFileWriteTool(
            inner=inner,
            event_log=event_log,
            manifest=manifest,
            run_id_getter=lambda: run_id,
            agent_name="Writer",
        )
        wrapper.execute(_FakeWriteInput(path="a.txt", content="a"))
        wrapper.execute(_FakeWriteInput(path="b.txt", content="b"))

        events = event_log.replay(run_id)
        assert len(events) == 2
        assert events[0].seq == 0
        assert events[1].seq == 1
