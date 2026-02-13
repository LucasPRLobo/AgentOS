"""Integration tests for SQLiteEventLog contract guarantees."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import BaseEvent, EventType, RunStarted

pytestmark = pytest.mark.integration


class TestSequenceMonotonicity:
    """Verify that sequence numbers form a monotonically increasing series."""

    def test_append_10_events_seq_0_to_9(self, event_log, run_id):
        for i in range(10):
            event_log.append(
                BaseEvent(run_id=run_id, seq=i, event_type=EventType.RUN_STARTED, payload={})
            )

        events = event_log.query_by_run(run_id)
        seqs = [e.seq for e in events]
        assert seqs == list(range(10))


class TestPKUniqueness:
    """Verify that duplicate (run_id, seq) raises IntegrityError."""

    def test_duplicate_run_id_seq_raises(self, event_log, run_id):
        event_log.append(
            BaseEvent(run_id=run_id, seq=0, event_type=EventType.RUN_STARTED, payload={})
        )
        with pytest.raises(sqlite3.IntegrityError):
            event_log.append(
                BaseEvent(run_id=run_id, seq=0, event_type=EventType.RUN_FINISHED, payload={})
            )


class TestRunIsolation:
    """Verify that multiple runs don't cross-contaminate."""

    def test_separate_runs_are_isolated(self, event_log):
        rid_a = generate_run_id()
        rid_b = generate_run_id()

        event_log.append(RunStarted(run_id=rid_a, seq=0, payload={"workflow": "a"}))
        event_log.append(RunStarted(run_id=rid_b, seq=0, payload={"workflow": "b"}))
        event_log.append(
            BaseEvent(run_id=rid_a, seq=1, event_type=EventType.RUN_FINISHED, payload={})
        )

        events_a = event_log.query_by_run(rid_a)
        events_b = event_log.query_by_run(rid_b)

        assert len(events_a) == 2
        assert len(events_b) == 1
        assert all(e.run_id == rid_a for e in events_a)
        assert all(e.run_id == rid_b for e in events_b)


class TestThreadSafety:
    """Verify thread-safe parallel appends."""

    def test_parallel_append_no_gaps(self, event_log_file):
        """4 threads × 25 events = 100 events, no gaps in global set."""
        run_id = generate_run_id()
        errors: list[Exception] = []

        def append_batch(start: int, count: int) -> None:
            try:
                for i in range(count):
                    event_log_file.append(
                        BaseEvent(
                            run_id=run_id,
                            seq=start + i,
                            event_type=EventType.BUDGET_UPDATED,
                            payload={"thread_batch_start": start},
                        )
                    )
            except Exception as exc:
                errors.append(exc)

        threads = []
        for t in range(4):
            th = threading.Thread(target=append_batch, args=(t * 25, 25))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        assert not errors, f"Thread errors: {errors}"

        events = event_log_file.query_by_run(run_id)
        assert len(events) == 100

    def test_parallel_append_no_duplicates(self, event_log_file):
        """All 100 events have distinct seq values."""
        run_id = generate_run_id()

        def append_batch(start: int, count: int) -> None:
            for i in range(count):
                event_log_file.append(
                    BaseEvent(
                        run_id=run_id,
                        seq=start + i,
                        event_type=EventType.BUDGET_UPDATED,
                        payload={},
                    )
                )

        threads = []
        for t in range(4):
            th = threading.Thread(target=append_batch, args=(t * 25, 25))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        events = event_log_file.query_by_run(run_id)
        seqs = [e.seq for e in events]
        assert len(seqs) == len(set(seqs)), "Duplicate seq values found"


class TestFilePersistence:
    """Verify that file-backed log survives close and re-open."""

    def test_persistence_survives_reopen(self, tmp_path):
        db_path = tmp_path / "persist.db"
        run_id = generate_run_id()

        log1 = SQLiteEventLog(db_path)
        log1.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test"}))
        log1.close()

        log2 = SQLiteEventLog(db_path)
        events = log2.query_by_run(run_id)
        log2.close()

        assert len(events) == 1
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[0].payload["workflow"] == "test"
