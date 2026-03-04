"""Benchmarking engine — run same task across N agent backends, compare results."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from agentos.schemas.benchmark import (
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkStatus,
)


@dataclass
class BenchmarkReport:
    """Aggregated benchmark report."""

    run_id: str
    task_description: str
    results: dict[str, BenchmarkResult]
    fastest_backend: str | None = None
    cheapest_backend: str | None = None
    best_quality_backend: str | None = None

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "task_description": self.task_description,
            "results": {k: v.model_dump(mode="json") for k, v in self.results.items()},
            "fastest_backend": self.fastest_backend,
            "cheapest_backend": self.cheapest_backend,
            "best_quality_backend": self.best_quality_backend,
        }


class BenchmarkRunner:
    """Runs benchmark comparisons across multiple agent backends.

    In production, this would call actual adapters. For now, it provides
    the framework for recording and comparing results.
    """

    def __init__(self, config: BenchmarkConfig | None = None) -> None:
        self._config = config or BenchmarkConfig()
        self._runs: dict[str, BenchmarkRun] = {}

    def create_run(self, task_description: str, backends: list[str] | None = None) -> BenchmarkRun:
        """Create a new benchmark run."""
        run_id = str(uuid.uuid4())
        backend_list = backends or self._config.backends
        run = BenchmarkRun(
            run_id=run_id,
            task_description=task_description,
            backends=backend_list,
            results={
                b: BenchmarkResult(backend=b) for b in backend_list
            },
        )
        self._runs[run_id] = run
        return run

    def record_result(
        self,
        run_id: str,
        backend: str,
        duration_seconds: float,
        total_tokens: int,
        estimated_cost_usd: float,
        output_summary: str,
        quality_score: float | None = None,
        error: str | None = None,
    ) -> BenchmarkResult:
        """Record the result of running a task on a specific backend."""
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")
        if backend not in run.results:
            raise ValueError(f"Unknown backend: {backend}")

        result = run.results[backend]
        result.status = BenchmarkStatus.COMPLETED if error is None else BenchmarkStatus.FAILED
        result.duration_seconds = duration_seconds
        result.total_tokens = total_tokens
        result.estimated_cost_usd = estimated_cost_usd
        result.output_summary = output_summary
        result.quality_score = quality_score
        result.error = error

        # Check if all backends are done
        if all(r.status in (BenchmarkStatus.COMPLETED, BenchmarkStatus.FAILED) for r in run.results.values()):
            run.status = BenchmarkStatus.COMPLETED

        return result

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        return self._runs.get(run_id)

    def generate_report(self, run_id: str) -> BenchmarkReport:
        """Generate an aggregated comparison report."""
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")

        completed = {
            k: v for k, v in run.results.items()
            if v.status == BenchmarkStatus.COMPLETED
        }

        fastest = min(completed, key=lambda k: completed[k].duration_seconds) if completed else None
        cheapest = min(completed, key=lambda k: completed[k].estimated_cost_usd) if completed else None

        quality_results = {k: v for k, v in completed.items() if v.quality_score is not None}
        best_quality = max(quality_results, key=lambda k: quality_results[k].quality_score) if quality_results else None

        return BenchmarkReport(
            run_id=run_id,
            task_description=run.task_description,
            results=run.results,
            fastest_backend=fastest,
            cheapest_backend=cheapest,
            best_quality_backend=best_quality,
        )

    def list_runs(self) -> list[BenchmarkRun]:
        return list(self._runs.values())
