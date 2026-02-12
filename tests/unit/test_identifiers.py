"""Tests for core identifier types and generation."""

from agentos.core.identifiers import (
    ArtifactId,
    RunId,
    TaskId,
    ToolCallId,
    generate_artifact_id,
    generate_id,
    generate_run_id,
    generate_task_id,
    generate_tool_call_id,
)


class TestGenerateId:
    def test_returns_string(self) -> None:
        assert isinstance(generate_id(), str)

    def test_unique_ids(self) -> None:
        ids = {generate_id() for _ in range(100)}
        assert len(ids) == 100

    def test_uuid4_format(self) -> None:
        id_ = generate_id()
        parts = id_.split("-")
        assert len(parts) == 5
        assert len(id_) == 36


class TestTypedIdGenerators:
    def test_generate_run_id(self) -> None:
        rid = generate_run_id()
        assert isinstance(rid, str)
        assert RunId.__supertype__ is str

    def test_generate_task_id(self) -> None:
        tid = generate_task_id()
        assert isinstance(tid, str)
        assert TaskId.__supertype__ is str

    def test_generate_tool_call_id(self) -> None:
        tcid = generate_tool_call_id()
        assert isinstance(tcid, str)
        assert ToolCallId.__supertype__ is str

    def test_generate_artifact_id(self) -> None:
        aid = generate_artifact_id()
        assert isinstance(aid, str)
        assert ArtifactId.__supertype__ is str
