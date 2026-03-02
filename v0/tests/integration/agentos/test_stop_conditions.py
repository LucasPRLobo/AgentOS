"""Integration tests for stop condition detection and event emission."""

from __future__ import annotations

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from tests.conftest import assert_has_event

pytestmark = pytest.mark.integration


class TestRepeatedToolCalls:
    """Verify repeated identical tool calls trigger stop condition."""

    def test_five_identical_calls_triggers(self, event_log, run_id):
        checker = StopConditionChecker(
            event_log, run_id, max_repeated_tool_calls=5
        )

        for _ in range(5):
            checker.record_tool_call("my_tool", "same_hash")

        reason = checker.check(seq=0)
        assert reason is not None
        assert "Repeated identical tool call" in reason

        events = event_log.query_by_run(run_id)
        assert_has_event(events, EventType.STOP_CONDITION)


class TestConsecutiveFailures:
    """Verify consecutive failures trigger stop condition."""

    def test_three_consecutive_failures_triggers(self, event_log, run_id):
        checker = StopConditionChecker(
            event_log, run_id, max_consecutive_failures=3
        )

        for _ in range(3):
            checker.record_task_failure()

        reason = checker.check(seq=0)
        assert reason is not None
        assert "consecutive failures" in reason.lower()

        events = event_log.query_by_run(run_id)
        assert_has_event(events, EventType.STOP_CONDITION)


class TestNoProgress:
    """Verify no-progress state triggers stop condition."""

    def test_ten_steps_no_progress_triggers(self, event_log, run_id):
        checker = StopConditionChecker(
            event_log, run_id, max_no_progress_steps=10
        )

        for _ in range(10):
            checker.record_step()

        reason = checker.check(seq=0)
        assert reason is not None
        assert "No progress" in reason

        events = event_log.query_by_run(run_id)
        assert_has_event(events, EventType.STOP_CONDITION)


class TestStopConditionEventEmitted:
    """Verify StopCondition event is emitted in the log."""

    def test_stop_condition_event_in_log(self, event_log, run_id):
        checker = StopConditionChecker(
            event_log, run_id,
            max_repeated_tool_calls=3,
        )

        for _ in range(3):
            checker.record_tool_call("echo", "hash123")

        reason = checker.check(seq=42)

        events = event_log.query_by_run(run_id)
        evt = assert_has_event(events, EventType.STOP_CONDITION)
        assert evt.seq == 42
        assert "reason" in evt.payload
        assert evt.payload["reason"] == reason
