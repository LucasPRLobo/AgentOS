"""Concurrency control — semaphore-based limiters for tasks and tools."""

from __future__ import annotations

import threading


class ConcurrencyLimiter:
    """Semaphore-based limiter for controlling parallel execution.

    Supports a global max-parallel limit and optional per-tool limits.
    """

    def __init__(
        self,
        max_parallel: int = 1,
        per_tool_limits: dict[str, int] | None = None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self._global_semaphore = threading.Semaphore(max_parallel)
        self._max_parallel = max_parallel
        self._tool_semaphores: dict[str, threading.Semaphore] = {}
        for name, limit in (per_tool_limits or {}).items():
            if limit < 1:
                raise ValueError(f"Per-tool limit for '{name}' must be >= 1")
            self._tool_semaphores[name] = threading.Semaphore(limit)
        self._active_count = 0
        self._lock = threading.Lock()

    @property
    def max_parallel(self) -> int:
        return self._max_parallel

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    def acquire(self, tool_name: str | None = None) -> None:
        """Acquire a slot. Blocks until a slot is available."""
        self._global_semaphore.acquire()
        with self._lock:
            self._active_count += 1

        if tool_name and tool_name in self._tool_semaphores:
            self._tool_semaphores[tool_name].acquire()

    def release(self, tool_name: str | None = None) -> None:
        """Release a slot."""
        if tool_name and tool_name in self._tool_semaphores:
            self._tool_semaphores[tool_name].release()

        with self._lock:
            self._active_count -= 1
        self._global_semaphore.release()

    def try_acquire(self, tool_name: str | None = None) -> bool:
        """Try to acquire a slot without blocking. Returns True if acquired."""
        acquired = self._global_semaphore.acquire(blocking=False)
        if not acquired:
            return False

        if tool_name and tool_name in self._tool_semaphores:
            tool_acquired = self._tool_semaphores[tool_name].acquire(blocking=False)
            if not tool_acquired:
                self._global_semaphore.release()
                return False

        with self._lock:
            self._active_count += 1
        return True
