"""Tests for the event log — append, query, ordering, persistence."""

import tempfile
from pathlib import Path

from agentos.core.identifiers import RunId, generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import (
    EventType,
    RunFinished,
    RunStarted,
    TaskFinished,
    TaskStarted,
)


class TestSQLiteEventLogInMemory:
    def test_append_and_query(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        event = RunStarted(run_id=run_id, seq=0, payload={"reason": "test"})
        log.append(event)

        events = log.query_by_run(run_id)
        assert len(events) == 1
        assert events[0].run_id == run_id
        assert events[0].event_type == EventType.RUN_STARTED

    def test_ordering(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()

        log.append(RunStarted(run_id=run_id, seq=0))
        log.append(TaskStarted(run_id=run_id, seq=1))
        log.append(TaskFinished(run_id=run_id, seq=2))
        log.append(RunFinished(run_id=run_id, seq=3))

        events = log.query_by_run(run_id)
        assert len(events) == 4
        assert [e.seq for e in events] == [0, 1, 2, 3]

    def test_query_by_type(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()

        log.append(RunStarted(run_id=run_id, seq=0))
        log.append(TaskStarted(run_id=run_id, seq=1))
        log.append(TaskFinished(run_id=run_id, seq=2))
        log.append(RunFinished(run_id=run_id, seq=3))

        task_events = log.query_by_type(run_id, EventType.TASK_STARTED)
        assert len(task_events) == 1
        assert task_events[0].seq == 1

    def test_replay_returns_full_stream(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()

        log.append(RunStarted(run_id=run_id, seq=0))
        log.append(TaskStarted(run_id=run_id, seq=1))
        log.append(RunFinished(run_id=run_id, seq=2))

        replay = log.replay(run_id)
        assert len(replay) == 3
        assert [e.event_type for e in replay] == [
            EventType.RUN_STARTED,
            EventType.TASK_STARTED,
            EventType.RUN_FINISHED,
        ]

    def test_separate_runs(self) -> None:
        log = SQLiteEventLog()
        run_a = generate_run_id()
        run_b = generate_run_id()

        log.append(RunStarted(run_id=run_a, seq=0))
        log.append(RunStarted(run_id=run_b, seq=0))
        log.append(RunFinished(run_id=run_a, seq=1))

        assert len(log.query_by_run(run_a)) == 2
        assert len(log.query_by_run(run_b)) == 1

    def test_empty_query(self) -> None:
        log = SQLiteEventLog()
        events = log.query_by_run(RunId("nonexistent"))
        assert events == []


class TestSQLiteEventLogPersistence:
    def test_data_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            run_id = generate_run_id()

            log1 = SQLiteEventLog(db_path)
            log1.append(RunStarted(run_id=run_id, seq=0))
            log1.append(RunFinished(run_id=run_id, seq=1))
            log1.close()

            log2 = SQLiteEventLog(db_path)
            events = log2.query_by_run(run_id)
            assert len(events) == 2
            assert events[0].event_type == EventType.RUN_STARTED
            assert events[1].event_type == EventType.RUN_FINISHED
            log2.close()
