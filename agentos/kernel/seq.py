"""Thread-safe monotonic sequence counter."""

from __future__ import annotations

import threading


class SeqCounter:
    """Shared monotonic sequence counter for a workflow execution.

    Passed to all components (executor, budget manager, gate manager).
    Each call to next() returns a unique, monotonically increasing integer.
    Thread-safe for parallel task execution.
    """

    def __init__(self, start: int = 0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            seq = self._value
            self._value += 1
            return seq

    @property
    def current(self) -> int:
        return self._value
