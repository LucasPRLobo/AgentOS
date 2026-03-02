"""SeqCounter correctness and thread-safety tests."""

from __future__ import annotations

import threading

from agentos.kernel.seq import SeqCounter


class TestSeqCounterBasic:
    def test_starts_at_zero(self, seq: SeqCounter):
        assert seq.current == 0

    def test_next_returns_sequential(self, seq: SeqCounter):
        assert seq.next() == 0
        assert seq.next() == 1
        assert seq.next() == 2

    def test_current_reflects_state(self, seq: SeqCounter):
        seq.next()
        seq.next()
        assert seq.current == 2

    def test_custom_start(self, seq_from_10: SeqCounter):
        assert seq_from_10.current == 10
        assert seq_from_10.next() == 10
        assert seq_from_10.next() == 11


class TestSeqCounterThreadSafety:
    def test_concurrent_increments(self):
        """Launch many threads, each calling next() — verify no duplicates."""
        counter = SeqCounter()
        results: list[int] = []
        lock = threading.Lock()
        n_threads = 50
        calls_per_thread = 100

        def worker():
            local = []
            for _ in range(calls_per_thread):
                local.append(counter.next())
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected_total = n_threads * calls_per_thread
        assert len(results) == expected_total
        assert len(set(results)) == expected_total  # No duplicates
        assert counter.current == expected_total

    def test_monotonic_per_thread(self):
        """Each thread's local sequence should be strictly increasing."""
        counter = SeqCounter()
        violations: list[str] = []
        n_threads = 20
        calls_per_thread = 50

        def worker(tid: int):
            prev = -1
            for _ in range(calls_per_thread):
                val = counter.next()
                if val <= prev:
                    violations.append(f"Thread {tid}: {val} <= {prev}")
                prev = val

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert violations == [], f"Monotonicity violations: {violations}"

    def test_no_gaps(self):
        """All values from 0 to N-1 should be produced."""
        counter = SeqCounter()
        results: list[int] = []
        lock = threading.Lock()

        def worker():
            local = []
            for _ in range(200):
                local.append(counter.next())
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == list(range(2000))
