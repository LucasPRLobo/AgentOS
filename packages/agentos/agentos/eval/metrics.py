"""Evaluation metrics — aggregate statistics from eval results."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from agentos.eval.eval_case import EvalOutcome, EvalResult


class EvalMetrics(BaseModel):
    """Aggregate metrics computed from a collection of eval results."""

    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    success_rate: float = Field(ge=0.0, le=1.0, default=0.0)
    total_duration_seconds: float = Field(ge=0.0, default=0.0)
    avg_duration_seconds: float = Field(ge=0.0, default=0.0)
    failure_types: dict[str, int] = Field(default_factory=dict)
    per_case_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)


def compute_metrics(results: list[EvalResult]) -> EvalMetrics:
    """Compute aggregate metrics from a list of eval results."""
    if not results:
        return EvalMetrics()

    total = len(results)
    passed = sum(1 for r in results if r.outcome == EvalOutcome.PASSED)
    failed = sum(1 for r in results if r.outcome == EvalOutcome.FAILED)
    errors = sum(1 for r in results if r.outcome == EvalOutcome.ERROR)
    skipped = sum(1 for r in results if r.outcome == EvalOutcome.SKIPPED)

    total_duration = sum(r.duration_seconds for r in results)
    executed = total - skipped
    avg_duration = total_duration / executed if executed > 0 else 0.0

    success_rate = passed / executed if executed > 0 else 0.0

    # Count failure types
    failure_types: Counter[str] = Counter()
    for r in results:
        if r.outcome in (EvalOutcome.FAILED, EvalOutcome.ERROR) and r.error_type:
            failure_types[r.error_type] += 1

    # Per-case metrics
    per_case: dict[str, dict[str, float]] = {}
    for r in results:
        if r.metrics:
            per_case[r.case_name] = dict(r.metrics)

    return EvalMetrics(
        total_cases=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        success_rate=success_rate,
        total_duration_seconds=total_duration,
        avg_duration_seconds=avg_duration,
        failure_types=dict(failure_types),
        per_case_metrics=per_case,
    )
