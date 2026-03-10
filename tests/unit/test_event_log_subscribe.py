"""Tests for EventLog subscribe/unsubscribe functionality."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType


@pytest.fixture
def log() -> SQLiteEventLog:
    return SQLiteEventLog(":memory:")


def _make_event(seq: int, workflow_id: str = "wf-1") -> Event:
    return Event(
        event_type=EventType.TASK_STATE_CHANGED,
        workflow_id=workflow_id,
        seq=seq,
        payload={"task_id": "t1", "from_state": "pending", "to_state": "running"},
    )


class TestSubscribe:
    def test_subscriber_receives_events(self, log):
        received = []
        log.subscribe(lambda e: received.append(e))
        log.append(_make_event(0))
        assert len(received) == 1
        assert received[0].seq == 0

    def test_multiple_subscribers(self, log):
        received_a = []
        received_b = []
        log.subscribe(lambda e: received_a.append(e))
        log.subscribe(lambda e: received_b.append(e))
        log.append(_make_event(0))
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_subscribe_returns_id(self, log):
        sub_id = log.subscribe(lambda e: None)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0


class TestUnsubscribe:
    def test_unsubscribed_stops_events(self, log):
        received = []
        sub_id = log.subscribe(lambda e: received.append(e))
        log.append(_make_event(0))
        assert len(received) == 1

        log.unsubscribe(sub_id)
        log.append(_make_event(1))
        assert len(received) == 1  # No new event received

    def test_unsubscribe_nonexistent(self, log):
        log.unsubscribe("nonexistent")  # Should not raise


class TestSubscriberErrorIsolation:
    def test_error_does_not_block_others(self, log):
        received = []

        def bad_callback(e):
            raise RuntimeError("subscriber error")

        log.subscribe(bad_callback)
        log.subscribe(lambda e: received.append(e))
        log.append(_make_event(0))
        # Second subscriber should still receive the event
        assert len(received) == 1

    def test_error_does_not_block_append(self, log):
        def bad_callback(e):
            raise RuntimeError("subscriber error")

        log.subscribe(bad_callback)
        log.append(_make_event(0))
        # Event should still be in the log
        events = log.query()
        assert len(events) == 1


class TestSubscribeWithConcurrency:
    def test_concurrent_appends_notify_subscriber(self, log):
        received = []
        lock = threading.Lock()

        def callback(e):
            with lock:
                received.append(e)

        log.subscribe(callback)

        def append_batch(start):
            for i in range(5):
                log.append(_make_event(start + i, f"wf-{start}"))

        threads = [threading.Thread(target=append_batch, args=(i * 5,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 15


class TestProgressCallback:
    def test_progress_callback_protocol(self):
        from agentos.adapters.base import ProgressCallback

        def my_callback(agent_id: str, progress: dict) -> None:
            pass

        assert isinstance(my_callback, ProgressCallback)

    def test_none_is_valid(self):
        """progress_callback=None should be accepted by adapters."""
        # This is a type-level check — None is a valid default
        from agentos.adapters.base import ProgressCallback
        assert not isinstance(None, ProgressCallback)
