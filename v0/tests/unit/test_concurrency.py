"""Tests for ConcurrencyLimiter — global and per-tool limits."""

import threading
import time

import pytest

from agentos.governance.concurrency import ConcurrencyLimiter


class TestConcurrencyLimiter:
    def test_basic_acquire_release(self) -> None:
        limiter = ConcurrencyLimiter(max_parallel=2)
        limiter.acquire()
        assert limiter.active_count == 1
        limiter.acquire()
        assert limiter.active_count == 2
        limiter.release()
        assert limiter.active_count == 1
        limiter.release()
        assert limiter.active_count == 0

    def test_blocks_at_limit(self) -> None:
        limiter = ConcurrencyLimiter(max_parallel=1)
        limiter.acquire()

        acquired = limiter.try_acquire()
        assert acquired is False
        assert limiter.active_count == 1

        limiter.release()
        acquired = limiter.try_acquire()
        assert acquired is True
        limiter.release()

    def test_parallel_threads(self) -> None:
        limiter = ConcurrencyLimiter(max_parallel=2)
        max_seen = [0]
        lock = threading.Lock()

        def worker() -> None:
            limiter.acquire()
            with lock:
                count = limiter.active_count
                if count > max_seen[0]:
                    max_seen[0] = count
            time.sleep(0.02)
            limiter.release()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_seen[0] <= 2
        assert limiter.active_count == 0

    def test_invalid_max_parallel(self) -> None:
        with pytest.raises(ValueError, match="max_parallel"):
            ConcurrencyLimiter(max_parallel=0)


class TestPerToolLimits:
    def test_per_tool_limit(self) -> None:
        limiter = ConcurrencyLimiter(max_parallel=5, per_tool_limits={"slow_tool": 1})

        limiter.acquire(tool_name="slow_tool")
        assert limiter.active_count == 1

        # Second acquire of same tool should fail (non-blocking)
        acquired = limiter.try_acquire(tool_name="slow_tool")
        assert acquired is False

        # Different tool (no per-tool limit) should succeed
        limiter.acquire(tool_name="fast_tool")
        assert limiter.active_count == 2

        limiter.release(tool_name="fast_tool")
        limiter.release(tool_name="slow_tool")
        assert limiter.active_count == 0

    def test_invalid_per_tool_limit(self) -> None:
        with pytest.raises(ValueError, match="Per-tool limit"):
            ConcurrencyLimiter(max_parallel=2, per_tool_limits={"bad": 0})

    def test_try_acquire_tool(self) -> None:
        limiter = ConcurrencyLimiter(max_parallel=3, per_tool_limits={"t": 2})

        assert limiter.try_acquire(tool_name="t") is True
        assert limiter.try_acquire(tool_name="t") is True
        assert limiter.try_acquire(tool_name="t") is False  # per-tool limit

        limiter.release(tool_name="t")
        assert limiter.try_acquire(tool_name="t") is True

        limiter.release(tool_name="t")
        limiter.release(tool_name="t")
