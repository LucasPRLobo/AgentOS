"""Tests for Pydantic schemas — serialization round-trips and validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agentos.core.identifiers import (
    ArtifactId,
    RunId,
    TaskId,
    generate_artifact_id,
    generate_run_id,
    generate_task_id,
)
from agentos.schemas.artifact import ArtifactMeta
from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage
from agentos.schemas.events import (
    BaseEvent,
    EventType,
    RunFinished,
    RunStarted,
    TaskFinished,
    TaskStarted,
    ToolCallFinished,
    ToolCallStarted,
)
from agentos.schemas.tool_call import ToolCallRecord


class TestBudgetSpec:
    def test_valid_spec(self) -> None:
        spec = BudgetSpec(
            max_tokens=1000,
            max_tool_calls=50,
            max_time_seconds=300.0,
            max_recursion_depth=10,
        )
        assert spec.max_tokens == 1000
        assert spec.max_parallel == 1  # default

    def test_invalid_zero_tokens(self) -> None:
        with pytest.raises(ValidationError):
            BudgetSpec(
                max_tokens=0,
                max_tool_calls=50,
                max_time_seconds=300.0,
                max_recursion_depth=10,
            )

    def test_round_trip(self) -> None:
        spec = BudgetSpec(
            max_tokens=1000,
            max_tool_calls=50,
            max_time_seconds=300.0,
            max_recursion_depth=10,
        )
        restored = BudgetSpec.model_validate_json(spec.model_dump_json())
        assert restored == spec


class TestBudgetUsage:
    def test_defaults(self) -> None:
        usage = BudgetUsage()
        assert usage.tokens_used == 0
        assert usage.tool_calls_used == 0

    def test_exceeds_tokens(self) -> None:
        spec = BudgetSpec(
            max_tokens=100,
            max_tool_calls=50,
            max_time_seconds=300.0,
            max_recursion_depth=10,
        )
        usage = BudgetUsage(tokens_used=100)
        assert usage.exceeds(spec) == "max_tokens"

    def test_not_exceeded(self) -> None:
        spec = BudgetSpec(
            max_tokens=100,
            max_tool_calls=50,
            max_time_seconds=300.0,
            max_recursion_depth=10,
        )
        usage = BudgetUsage(tokens_used=50)
        assert usage.exceeds(spec) is None


class TestBudgetDelta:
    def test_defaults(self) -> None:
        delta = BudgetDelta()
        assert delta.tokens == 0
        assert delta.tool_calls == 0

    def test_round_trip(self) -> None:
        delta = BudgetDelta(tokens=100, tool_calls=1, time_seconds=1.5)
        restored = BudgetDelta.model_validate_json(delta.model_dump_json())
        assert restored == delta


class TestBaseEvent:
    def test_create_event(self) -> None:
        run_id = generate_run_id()
        event = BaseEvent(
            run_id=run_id,
            seq=0,
            event_type=EventType.RUN_STARTED,
        )
        assert event.run_id == run_id
        assert event.seq == 0
        assert event.event_type == EventType.RUN_STARTED

    def test_event_has_timestamp(self) -> None:
        event = BaseEvent(
            run_id=RunId("test-run"),
            seq=0,
            event_type=EventType.RUN_STARTED,
        )
        assert isinstance(event.timestamp, datetime)

    def test_event_round_trip(self) -> None:
        event = RunStarted(
            run_id=RunId("test-run"),
            seq=0,
            payload={"reason": "test"},
        )
        restored = RunStarted.model_validate_json(event.model_dump_json())
        assert restored.run_id == event.run_id
        assert restored.payload == event.payload

    def test_invalid_negative_seq(self) -> None:
        with pytest.raises(ValidationError):
            BaseEvent(
                run_id=RunId("test"),
                seq=-1,
                event_type=EventType.RUN_STARTED,
            )


class TestConcreteEvents:
    def test_run_started_type(self) -> None:
        event = RunStarted(run_id=RunId("r"), seq=0)
        assert event.event_type == EventType.RUN_STARTED

    def test_run_finished_type(self) -> None:
        event = RunFinished(run_id=RunId("r"), seq=1)
        assert event.event_type == EventType.RUN_FINISHED

    def test_task_started_type(self) -> None:
        event = TaskStarted(run_id=RunId("r"), seq=2)
        assert event.event_type == EventType.TASK_STARTED

    def test_task_finished_type(self) -> None:
        event = TaskFinished(run_id=RunId("r"), seq=3)
        assert event.event_type == EventType.TASK_FINISHED

    def test_tool_call_started_type(self) -> None:
        event = ToolCallStarted(run_id=RunId("r"), seq=4)
        assert event.event_type == EventType.TOOL_CALL_STARTED

    def test_tool_call_finished_type(self) -> None:
        event = ToolCallFinished(run_id=RunId("r"), seq=5)
        assert event.event_type == EventType.TOOL_CALL_FINISHED


class TestToolCallRecord:
    def test_create_record(self) -> None:
        record = ToolCallRecord(
            tool_name="my_tool",
            input_hash="abc123",
        )
        assert record.tool_name == "my_tool"
        assert record.success is False

    def test_round_trip(self) -> None:
        now = datetime.now(timezone.utc)
        record = ToolCallRecord(
            tool_name="my_tool",
            tool_version="1.0.0",
            input_hash="abc",
            output_hash="def",
            started_at=now,
            finished_at=now,
            success=True,
        )
        restored = ToolCallRecord.model_validate_json(record.model_dump_json())
        assert restored.tool_name == record.tool_name
        assert restored.success is True


class TestArtifactMeta:
    def test_create_artifact(self) -> None:
        meta = ArtifactMeta(
            id=generate_artifact_id(),
            path="outputs/result.csv",
            sha256="deadbeef" * 8,
            produced_by_task=generate_task_id(),
        )
        assert meta.mime_type == "application/octet-stream"

    def test_round_trip(self) -> None:
        meta = ArtifactMeta(
            id=ArtifactId("art-1"),
            path="outputs/model.pt",
            sha256="a" * 64,
            produced_by_task=TaskId("task-1"),
            mime_type="application/x-pytorch",
        )
        restored = ArtifactMeta.model_validate_json(meta.model_dump_json())
        assert restored == meta
