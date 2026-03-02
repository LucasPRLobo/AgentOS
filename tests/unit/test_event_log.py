"""Tests for EventLog ABC and SQLiteEventLog."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.schemas.events import Event, EventType


def _make_event(
    workflow_id: str = "wf-1",
    seq: int = 0,
    event_type: EventType = EventType.WORKFLOW_STARTED,
    payload: dict | None = None,
    metadata: dict | None = None,
) -> Event:
    return Event(
        event_type=event_type,
        workflow_id=workflow_id,
        seq=seq,
        payload=payload or {},
        metadata=metadata or {},
    )


class TestAppendAndReplay:
    def test_append_and_replay(self, event_log: SQLiteEventLog) -> None:
        e0 = _make_event(seq=0)
        e1 = _make_event(seq=1, event_type=EventType.TASK_STATE_CHANGED)
        event_log.append(e0)
        event_log.append(e1)

        events = event_log.replay("wf-1")
        assert len(events) == 2
        assert events[0].seq == 0
        assert events[1].seq == 1

    def test_replay_is_ordered(self, event_log: SQLiteEventLog) -> None:
        """Replay returns events in seq order even if appended out of order."""
        event_log.append(_make_event(seq=5))
        event_log.append(_make_event(seq=2))
        event_log.append(_make_event(seq=8))

        events = event_log.replay("wf-1")
        seqs = [e.seq for e in events]
        assert seqs == [2, 5, 8]


class TestWorkflowIsolation:
    def test_workflow_isolation(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(workflow_id="wf-A", seq=0))
        event_log.append(_make_event(workflow_id="wf-B", seq=0))

        a_events = event_log.replay("wf-A")
        b_events = event_log.replay("wf-B")
        assert len(a_events) == 1
        assert len(b_events) == 1
        assert a_events[0].workflow_id == "wf-A"
        assert b_events[0].workflow_id == "wf-B"


class TestQueryFilters:
    def test_query_filter_by_workflow(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(workflow_id="wf-X", seq=0))
        event_log.append(_make_event(workflow_id="wf-Y", seq=0))

        results = event_log.query(workflow_id="wf-X")
        assert len(results) == 1
        assert results[0].workflow_id == "wf-X"

    def test_query_filter_by_event_type(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(seq=0, event_type=EventType.WORKFLOW_STARTED))
        event_log.append(_make_event(seq=1, event_type=EventType.TASK_STATE_CHANGED))
        event_log.append(_make_event(seq=2, event_type=EventType.TASK_STATE_CHANGED))

        results = event_log.query(event_type=EventType.TASK_STATE_CHANGED)
        assert len(results) == 2
        assert all(e.event_type == EventType.TASK_STATE_CHANGED for e in results)

    def test_query_filter_by_since_seq(self, event_log: SQLiteEventLog) -> None:
        for i in range(10):
            event_log.append(_make_event(seq=i))

        results = event_log.query(since_seq=5)
        assert len(results) == 5
        assert results[0].seq == 5
        assert results[-1].seq == 9

    def test_query_combined_filters(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(seq=0, event_type=EventType.WORKFLOW_STARTED))
        event_log.append(_make_event(seq=1, event_type=EventType.TASK_STATE_CHANGED))
        event_log.append(_make_event(seq=2, event_type=EventType.TASK_STATE_CHANGED))
        event_log.append(_make_event(seq=3, event_type=EventType.WORKFLOW_COMPLETED))

        results = event_log.query(
            workflow_id="wf-1",
            event_type=EventType.TASK_STATE_CHANGED,
            since_seq=2,
        )
        assert len(results) == 1
        assert results[0].seq == 2


class TestLastSeq:
    def test_last_seq_empty_workflow(self, event_log: SQLiteEventLog) -> None:
        assert event_log.last_seq("nonexistent") == -1

    def test_last_seq_returns_max(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(seq=0))
        event_log.append(_make_event(seq=3))
        event_log.append(_make_event(seq=7))

        assert event_log.last_seq("wf-1") == 7


class TestDuplicateSeq:
    def test_duplicate_seq_raises_error(self, event_log: SQLiteEventLog) -> None:
        event_log.append(_make_event(seq=0))
        with pytest.raises(ValueError, match="Duplicate"):
            event_log.append(_make_event(seq=0))


class TestPayloadRoundTrip:
    def test_event_payload_round_trip(self, event_log: SQLiteEventLog) -> None:
        payload = {
            "task_id": "t1",
            "from_state": "pending",
            "to_state": "running",
            "nested": {"key": [1, 2, 3]},
        }
        event_log.append(_make_event(seq=0, payload=payload))

        events = event_log.replay("wf-1")
        assert events[0].payload == payload
        assert events[0].payload["nested"]["key"] == [1, 2, 3]


class TestConcurrentAppends:
    def test_concurrent_appends(self, event_log: SQLiteEventLog) -> None:
        """10 threads appending simultaneously — all present, no collisions."""
        errors: list[Exception] = []

        def append_event(seq: int) -> None:
            try:
                event_log.append(
                    _make_event(workflow_id="wf-concurrent", seq=seq)
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=append_event, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        events = event_log.replay("wf-concurrent")
        assert len(events) == 10
        assert sorted(e.seq for e in events) == list(range(10))


class TestDatabaseModes:
    def test_in_memory_log(self) -> None:
        log = SQLiteEventLog(":memory:")
        log.append(_make_event(seq=0))
        assert len(log.replay("wf-1")) == 1

    def test_file_backed_log(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        log = SQLiteEventLog(db_path)
        log.append(_make_event(seq=0))
        log.append(_make_event(seq=1))

        # Re-open to verify persistence
        log2 = SQLiteEventLog(db_path)
        events = log2.replay("wf-1")
        assert len(events) == 2
