"""Tests for StopConditionChecker — repeat detection, failure loops, no-progress."""

from agentos.core.identifiers import generate_run_id
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType


class TestRepeatedToolCalls:
    def test_no_repeats(self) -> None:
        log = SQLiteEventLog()
        checker = StopConditionChecker(log, generate_run_id(), max_repeated_tool_calls=3)
        checker.record_tool_call("tool_a", "hash1")
        checker.record_tool_call("tool_a", "hash2")
        assert checker.check(seq=0) is None

    def test_repeated_triggers(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        checker = StopConditionChecker(log, run_id, max_repeated_tool_calls=3)
        for _ in range(3):
            checker.record_tool_call("tool_a", "same_hash")

        reason = checker.check(seq=0)
        assert reason is not None
        assert "Repeated identical tool call" in reason
        assert "tool_a:same_hash" in reason

    def test_different_hashes_ok(self) -> None:
        log = SQLiteEventLog()
        checker = StopConditionChecker(log, generate_run_id(), max_repeated_tool_calls=3)
        for i in range(5):
            checker.record_tool_call("tool_a", f"hash_{i}")
        assert checker.check(seq=0) is None


class TestConsecutiveFailures:
    def test_no_failures(self) -> None:
        log = SQLiteEventLog()
        checker = StopConditionChecker(log, generate_run_id(), max_consecutive_failures=3)
        checker.record_task_success()
        assert checker.check(seq=0) is None

    def test_failures_trigger(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        checker = StopConditionChecker(log, run_id, max_consecutive_failures=3)
        for _ in range(3):
            checker.record_task_failure()

        reason = checker.check(seq=0)
        assert reason is not None
        assert "consecutive failures" in reason

    def test_success_resets_counter(self) -> None:
        log = SQLiteEventLog()
        checker = StopConditionChecker(log, generate_run_id(), max_consecutive_failures=3)
        checker.record_task_failure()
        checker.record_task_failure()
        checker.record_task_success()  # resets
        checker.record_task_failure()
        assert checker.check(seq=0) is None


class TestNoProgress:
    def test_progress_resets(self) -> None:
        log = SQLiteEventLog()
        checker = StopConditionChecker(log, generate_run_id(), max_no_progress_steps=5)
        for _ in range(4):
            checker.record_step()
        checker.record_task_success()  # resets
        assert checker.check(seq=0) is None

    def test_no_progress_triggers(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        checker = StopConditionChecker(log, run_id, max_no_progress_steps=5)
        for _ in range(5):
            checker.record_step()

        reason = checker.check(seq=0)
        assert reason is not None
        assert "No progress" in reason


class TestStopConditionEvents:
    def test_emits_event_on_trigger(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        checker = StopConditionChecker(log, run_id, max_consecutive_failures=2)
        checker.record_task_failure()
        checker.record_task_failure()

        checker.check(seq=0)

        events = log.query_by_type(run_id, EventType.STOP_CONDITION)
        assert len(events) == 1
        assert "consecutive failures" in events[0].payload["reason"]

    def test_no_event_when_ok(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        checker = StopConditionChecker(log, run_id)
        checker.record_task_success()
        checker.check(seq=0)

        events = log.query_by_type(run_id, EventType.STOP_CONDITION)
        assert len(events) == 0
