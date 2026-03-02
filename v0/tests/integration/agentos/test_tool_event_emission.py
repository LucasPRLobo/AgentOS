"""Integration tests for tool event emission via execute_with_events."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agentos.core.identifiers import generate_run_id
from agentos.integrity.hashing import hash_dict
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType
from agentos.tools.base import BaseTool, SideEffect

from tests.conftest import assert_has_event

pytestmark = pytest.mark.integration


# ── Minimal test tool ──────────────────────────────────────────────


class _AddInput(BaseModel):
    a: int
    b: int


class _AddOutput(BaseModel):
    result: int


class _AddTool(BaseTool):
    @property
    def name(self) -> str:
        return "add"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _AddInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _AddOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, _AddInput) else _AddInput.model_validate(
            input_data.model_dump()
        )
        return _AddOutput(result=data.a + data.b)


class _FailingTool(BaseTool):
    @property
    def name(self) -> str:
        return "failing"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _AddInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _AddOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        raise ValueError("Intentional failure")


# Import the bridge
from labos.tools._base import _SeqCounter, execute_with_events


class TestToolEventEmission:
    """Verify ToolCallStarted + ToolCallFinished events are emitted correctly."""

    def test_pure_tool_emits_started_and_finished(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        seq = _SeqCounter(0)

        tool = _AddTool()
        inp = _AddInput(a=2, b=3)
        output = execute_with_events(tool, inp, log, rid, seq)

        events = log.query_by_run(rid)
        assert len(events) == 2
        assert events[0].event_type == EventType.TOOL_CALL_STARTED
        assert events[1].event_type == EventType.TOOL_CALL_FINISHED
        assert events[1].payload["success"] is True
        log.close()

    def test_input_hash_matches(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        seq = _SeqCounter(0)

        tool = _AddTool()
        inp = _AddInput(a=10, b=20)
        execute_with_events(tool, inp, log, rid, seq)

        events = log.query_by_run(rid)
        started = events[0]
        expected_hash = hash_dict(inp.model_dump())
        assert started.payload["input_hash"] == expected_hash
        log.close()

    def test_output_hash_matches(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        seq = _SeqCounter(0)

        tool = _AddTool()
        inp = _AddInput(a=5, b=7)
        output = execute_with_events(tool, inp, log, rid, seq)

        events = log.query_by_run(rid)
        finished = events[1]
        expected_hash = hash_dict(output.model_dump())
        assert finished.payload["output_hash"] == expected_hash
        log.close()

    def test_failed_tool_emits_error_event(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        seq = _SeqCounter(0)

        tool = _FailingTool()
        inp = _AddInput(a=1, b=2)

        with pytest.raises(ValueError, match="Intentional failure"):
            execute_with_events(tool, inp, log, rid, seq)

        events = log.query_by_run(rid)
        assert len(events) == 2
        finished = events[1]
        assert finished.payload["success"] is False
        assert "Intentional failure" in finished.payload["error"]
        log.close()
