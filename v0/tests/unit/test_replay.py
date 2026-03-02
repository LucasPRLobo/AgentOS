"""Tests for ReplayEngine — strict replay, re-execution, run comparison."""

from typing import Any

from agentos.core.identifiers import RunId, generate_run_id
from agentos.observability.replay import ReplayEngine, ReplayMode, ReplayResult
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import (
    EventType,
    RunFinished,
    RunStarted,
    TaskFinished,
    TaskStarted,
    ToolCallFinished,
    ToolCallStarted,
)


def _populate_successful_run(log: SQLiteEventLog, run_id: RunId) -> None:
    """Helper to populate a complete successful run with tool calls."""
    log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test"}))
    log.append(
        TaskStarted(
            run_id=run_id, seq=1, payload={"task_id": "t1", "task_name": "compute"}
        )
    )
    log.append(
        ToolCallStarted(
            run_id=run_id,
            seq=2,
            payload={
                "tool_name": "add",
                "side_effect": "PURE",
                "input": {"a": 1, "b": 2},
            },
        )
    )
    log.append(
        ToolCallFinished(
            run_id=run_id,
            seq=3,
            payload={"tool_name": "add", "output": {"result": 3}, "success": True},
        )
    )
    log.append(
        TaskFinished(
            run_id=run_id,
            seq=4,
            payload={"task_id": "t1", "task_name": "compute", "state": "SUCCEEDED"},
        )
    )
    log.append(
        RunFinished(
            run_id=run_id,
            seq=5,
            payload={"workflow": "test", "outcome": "SUCCEEDED"},
        )
    )


def _populate_failed_run(log: SQLiteEventLog, run_id: RunId) -> None:
    """Helper to populate a failed run."""
    log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test"}))
    log.append(
        TaskStarted(
            run_id=run_id, seq=1, payload={"task_id": "t1", "task_name": "bad"}
        )
    )
    log.append(
        TaskFinished(
            run_id=run_id,
            seq=2,
            payload={
                "task_id": "t1",
                "task_name": "bad",
                "state": "FAILED",
                "error": "boom",
            },
        )
    )
    log.append(
        RunFinished(
            run_id=run_id,
            seq=3,
            payload={"workflow": "test", "outcome": "FAILED", "failed_task": "bad"},
        )
    )


class TestReplayStrict:
    def test_replay_successful_run(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        engine = ReplayEngine(log)
        result = engine.replay(run_id)

        assert result.success is True
        assert len(result.events) == 6
        assert result.run_id == run_id

    def test_replay_extracts_tool_outputs(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        engine = ReplayEngine(log)
        result = engine.replay(run_id)

        assert 3 in result.tool_outputs
        assert result.tool_outputs[3]["output"] == {"result": 3}

    def test_replay_failed_run(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_failed_run(log, run_id)

        engine = ReplayEngine(log)
        result = engine.replay(run_id)

        assert result.success is False

    def test_replay_nonexistent_run(self) -> None:
        log = SQLiteEventLog()
        engine = ReplayEngine(log)
        result = engine.replay(RunId("nonexistent"))

        assert result.success is False
        assert result.error is not None
        assert "No events" in result.error

    def test_task_events_property(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        result = ReplayEngine(log).replay(run_id)
        task_events = result.task_events
        assert len(task_events) == 2
        assert task_events[0].event_type == EventType.TASK_STARTED
        assert task_events[1].event_type == EventType.TASK_FINISHED

    def test_tool_call_events_property(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        result = ReplayEngine(log).replay(run_id)
        tc_events = result.tool_call_events
        assert len(tc_events) == 2


class TestReplayReexecute:
    def test_reexecute_pure_tool(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        def executor(tool_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
            if tool_name == "add":
                return {"result": input_data["a"] + input_data["b"]}
            return {}

        engine = ReplayEngine(log)
        result = engine.replay(run_id, mode=ReplayMode.REEXECUTE, tool_executor=executor)

        assert result.success is True
        assert result.tool_outputs[3].get("reexecuted") is True
        assert result.tool_outputs[3]["output"] == {"result": 3}

    def test_reexecute_failure(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_successful_run(log, run_id)

        def failing_executor(tool_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("re-execution failed")

        engine = ReplayEngine(log)
        result = engine.replay(
            run_id, mode=ReplayMode.REEXECUTE, tool_executor=failing_executor
        )

        assert result.success is False
        assert result.error is not None
        assert "re-execution failed" in result.error


class TestRunComparison:
    def test_same_structure(self) -> None:
        log = SQLiteEventLog()
        run_a = generate_run_id()
        run_b = generate_run_id()
        _populate_successful_run(log, run_a)
        _populate_successful_run(log, run_b)

        engine = ReplayEngine(log)
        comparison = engine.compare_runs(run_a, run_b)

        assert comparison.same_structure is True
        assert comparison.events_a_count == 6
        assert comparison.events_b_count == 6

    def test_different_structure(self) -> None:
        log = SQLiteEventLog()
        run_a = generate_run_id()
        run_b = generate_run_id()
        _populate_successful_run(log, run_a)
        _populate_failed_run(log, run_b)

        engine = ReplayEngine(log)
        comparison = engine.compare_runs(run_a, run_b)

        assert comparison.same_structure is False
        assert comparison.events_a_count != comparison.events_b_count
