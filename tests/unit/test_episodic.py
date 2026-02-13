"""Tests for EpisodicStore — run summary derivation and caching."""

from agentos.core.identifiers import RunId, generate_run_id
from agentos.memory.episodic import EpisodicStore
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import (
    RunFinished,
    RunStarted,
    TaskFinished,
    TaskStarted,
    ToolCallFinished,
    ToolCallStarted,
)


def _populate_run(log: SQLiteEventLog, run_id: RunId, *, fail: bool = False) -> None:
    log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test-wf"}))
    log.append(TaskStarted(run_id=run_id, seq=1, payload={"task_id": "t1", "task_name": "step1"}))
    log.append(
        ToolCallStarted(run_id=run_id, seq=2, payload={"tool_name": "add", "input": {"a": 1}})
    )
    log.append(
        ToolCallFinished(run_id=run_id, seq=3, payload={"tool_name": "add", "success": True})
    )

    if fail:
        log.append(
            TaskFinished(
                run_id=run_id,
                seq=4,
                payload={"task_id": "t1", "task_name": "step1", "state": "FAILED", "error": "err"},
            )
        )
        log.append(
            RunFinished(
                run_id=run_id,
                seq=5,
                payload={"workflow": "test-wf", "outcome": "FAILED", "failed_task": "step1"},
            )
        )
    else:
        log.append(
            TaskFinished(
                run_id=run_id,
                seq=4,
                payload={"task_id": "t1", "task_name": "step1", "state": "SUCCEEDED"},
            )
        )
        log.append(
            RunFinished(
                run_id=run_id, seq=5, payload={"workflow": "test-wf", "outcome": "SUCCEEDED"}
            )
        )


class TestEpisodicStore:
    def test_summarize_successful_run(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_run(log, run_id)

        store = EpisodicStore(log)
        summary = store.summarize(run_id)

        assert summary.run_id == run_id
        assert summary.workflow_name == "test-wf"
        assert summary.outcome == "SUCCEEDED"
        assert summary.total_events == 6
        assert summary.task_count == 1
        assert summary.tasks_succeeded == 1
        assert summary.tasks_failed == 0
        assert summary.tool_calls == 1
        assert summary.started_at is not None
        assert summary.finished_at is not None
        assert summary.failed_task is None

    def test_summarize_failed_run(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_run(log, run_id, fail=True)

        store = EpisodicStore(log)
        summary = store.summarize(run_id)

        assert summary.outcome == "FAILED"
        assert summary.tasks_failed == 1
        assert summary.failed_task == "step1"

    def test_summarize_nonexistent_run(self) -> None:
        log = SQLiteEventLog()
        store = EpisodicStore(log)
        summary = store.summarize(RunId("nope"))

        assert summary.outcome == "UNKNOWN"
        assert summary.total_events == 0

    def test_caching(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_run(log, run_id)

        store = EpisodicStore(log)
        s1 = store.summarize(run_id)
        s2 = store.summarize(run_id)
        assert s1 is s2  # same object from cache

    def test_invalidate(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        _populate_run(log, run_id)

        store = EpisodicStore(log)
        s1 = store.summarize(run_id)
        store.invalidate(run_id)
        s2 = store.summarize(run_id)
        assert s1 is not s2  # new object after invalidation
        assert s1 == s2  # but same content

    def test_list_runs(self) -> None:
        log = SQLiteEventLog()
        r1 = generate_run_id()
        r2 = generate_run_id()
        _populate_run(log, r1)
        _populate_run(log, r2, fail=True)

        store = EpisodicStore(log)
        summaries = store.list_runs([r1, r2])

        assert len(summaries) == 2
        assert summaries[0].outcome == "SUCCEEDED"
        assert summaries[1].outcome == "FAILED"

    def test_multi_task_run(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()

        log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "multi"}))
        log.append(
            TaskStarted(run_id=run_id, seq=1, payload={"task_id": "t1", "task_name": "a"})
        )
        log.append(
            TaskFinished(
                run_id=run_id, seq=2, payload={"task_id": "t1", "task_name": "a", "state": "SUCCEEDED"}
            )
        )
        log.append(
            TaskStarted(run_id=run_id, seq=3, payload={"task_id": "t2", "task_name": "b"})
        )
        log.append(
            TaskFinished(
                run_id=run_id, seq=4, payload={"task_id": "t2", "task_name": "b", "state": "SUCCEEDED"}
            )
        )
        log.append(
            RunFinished(run_id=run_id, seq=5, payload={"workflow": "multi", "outcome": "SUCCEEDED"})
        )

        store = EpisodicStore(log)
        summary = store.summarize(run_id)

        assert summary.task_count == 2
        assert summary.tasks_succeeded == 2
