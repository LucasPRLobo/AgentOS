"""Stop conditions — detect runaway execution and emit stop events."""

from __future__ import annotations

from collections import Counter

from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import StopCondition


class StopConditionChecker:
    """Detects conditions that should halt workflow execution.

    Checks for:
    - Recursion depth exceeded
    - Repeated identical tool calls
    - Excessive consecutive failures
    - No-progress state (no successful tasks in N attempts)
    """

    def __init__(
        self,
        event_log: EventLog,
        run_id: RunId,
        *,
        max_repeated_tool_calls: int = 5,
        max_consecutive_failures: int = 3,
        max_no_progress_steps: int = 10,
    ) -> None:
        self._event_log = event_log
        self._run_id = run_id
        self._max_repeated_tool_calls = max_repeated_tool_calls
        self._max_consecutive_failures = max_consecutive_failures
        self._max_no_progress_steps = max_no_progress_steps

        self._tool_call_history: list[str] = []
        self._consecutive_failures = 0
        self._steps_since_progress = 0

    def record_tool_call(self, tool_name: str, input_hash: str) -> None:
        """Record a tool call for repeat detection."""
        self._tool_call_history.append(f"{tool_name}:{input_hash}")

    def record_task_success(self) -> None:
        """Record a successful task, resetting failure/no-progress counters."""
        self._consecutive_failures = 0
        self._steps_since_progress = 0

    def record_task_failure(self) -> None:
        """Record a failed task."""
        self._consecutive_failures += 1
        self._steps_since_progress += 1

    def record_step(self) -> None:
        """Record a step that made no progress (e.g., skipped task)."""
        self._steps_since_progress += 1

    def check(self, seq: int) -> str | None:
        """Check all stop conditions. Returns reason string if triggered, None otherwise.

        If triggered, emits a StopCondition event.
        """
        reason = self._check_repeated_tool_calls()
        if reason is None:
            reason = self._check_consecutive_failures()
        if reason is None:
            reason = self._check_no_progress()

        if reason is not None:
            self._event_log.append(
                StopCondition(
                    run_id=self._run_id,
                    seq=seq,
                    payload={"reason": reason},
                )
            )
        return reason

    def _check_repeated_tool_calls(self) -> str | None:
        if not self._tool_call_history:
            return None
        counts = Counter(self._tool_call_history)
        for call_key, count in counts.items():
            if count >= self._max_repeated_tool_calls:
                return f"Repeated identical tool call: {call_key} ({count} times)"
        return None

    def _check_consecutive_failures(self) -> str | None:
        if self._consecutive_failures >= self._max_consecutive_failures:
            return (
                f"Excessive consecutive failures: "
                f"{self._consecutive_failures} failures in a row"
            )
        return None

    def _check_no_progress(self) -> str | None:
        if self._steps_since_progress >= self._max_no_progress_steps:
            return (
                f"No progress: {self._steps_since_progress} steps "
                f"without a successful task"
            )
        return None
