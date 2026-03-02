"""EvalRunner — execute evaluation cases and collect results."""

from __future__ import annotations

import logging
import time

from agentos.eval.eval_case import EvalCase, EvalOutcome, EvalResult
from agentos.eval.metrics import EvalMetrics, compute_metrics

logger = logging.getLogger(__name__)


class EvalSuite:
    """A named collection of eval cases."""

    def __init__(self, name: str, cases: list[EvalCase] | None = None) -> None:
        self.name = name
        self.cases: list[EvalCase] = cases or []

    def add(self, case: EvalCase) -> None:
        self.cases.append(case)

    def filter_by_tag(self, tag: str) -> list[EvalCase]:
        return [c for c in self.cases if tag in c.tags]


class EvalRunner:
    """Executes eval cases, handles setup/teardown, and collects metrics."""

    def __init__(self) -> None:
        self._results: list[EvalResult] = []

    @property
    def results(self) -> list[EvalResult]:
        return list(self._results)

    def run_case(self, case: EvalCase) -> EvalResult:
        """Run a single eval case with setup/teardown and timing."""
        start = time.monotonic()
        try:
            case.setup()
            result = case.run()
        except Exception as exc:
            duration = time.monotonic() - start
            result = EvalResult(
                case_name=case.name,
                outcome=EvalOutcome.ERROR,
                duration_seconds=duration,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )
        else:
            result.duration_seconds = time.monotonic() - start
        finally:
            try:
                case.teardown()
            except Exception:
                logger.warning("Teardown failed for case '%s'", case.name)

        self._results.append(result)
        return result

    def run_suite(
        self, suite: EvalSuite, *, tag: str | None = None
    ) -> list[EvalResult]:
        """Run all cases in a suite (optionally filtered by tag)."""
        cases = suite.filter_by_tag(tag) if tag else suite.cases
        results: list[EvalResult] = []
        for case in cases:
            result = self.run_case(case)
            results.append(result)
        return results

    def compute_metrics(self) -> EvalMetrics:
        """Compute aggregate metrics from all results collected so far."""
        return compute_metrics(self._results)

    def reset(self) -> None:
        """Clear all collected results."""
        self._results.clear()
