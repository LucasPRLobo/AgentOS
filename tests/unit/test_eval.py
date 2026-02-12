"""Tests for evaluation harness — EvalCase, EvalRunner, metrics."""

import pytest

from agentos.eval.eval_case import EvalCase, EvalOutcome, EvalResult
from agentos.eval.metrics import EvalMetrics, compute_metrics
from agentos.eval.runner import EvalRunner, EvalSuite


# --- Test eval cases ---


class PassingCase(EvalCase):
    @property
    def name(self) -> str:
        return "passing"

    @property
    def tags(self) -> list[str]:
        return ["fast"]

    def run(self) -> EvalResult:
        return EvalResult(
            case_name=self.name,
            outcome=EvalOutcome.PASSED,
            duration_seconds=0.0,
            metrics={"accuracy": 0.95},
        )


class FailingCase(EvalCase):
    @property
    def name(self) -> str:
        return "failing"

    @property
    def tags(self) -> list[str]:
        return ["slow"]

    def run(self) -> EvalResult:
        return EvalResult(
            case_name=self.name,
            outcome=EvalOutcome.FAILED,
            duration_seconds=0.0,
            error_message="assertion failed",
            error_type="AssertionError",
        )


class ErrorCase(EvalCase):
    @property
    def name(self) -> str:
        return "error"

    def run(self) -> EvalResult:
        raise RuntimeError("unexpected crash")


class SetupTracker(EvalCase):
    """Tracks setup/teardown calls."""

    def __init__(self) -> None:
        self.setup_called = False
        self.teardown_called = False

    @property
    def name(self) -> str:
        return "tracker"

    def setup(self) -> None:
        self.setup_called = True

    def teardown(self) -> None:
        self.teardown_called = True

    def run(self) -> EvalResult:
        return EvalResult(
            case_name=self.name,
            outcome=EvalOutcome.PASSED,
            duration_seconds=0.0,
        )


class SkippedCase(EvalCase):
    @property
    def name(self) -> str:
        return "skipped"

    def run(self) -> EvalResult:
        return EvalResult(
            case_name=self.name,
            outcome=EvalOutcome.SKIPPED,
            duration_seconds=0.0,
        )


# --- Tests ---


class TestEvalCase:
    def test_passing_case(self) -> None:
        case = PassingCase()
        result = case.run()
        assert result.outcome == EvalOutcome.PASSED
        assert result.case_name == "passing"

    def test_tags(self) -> None:
        assert PassingCase().tags == ["fast"]
        assert FailingCase().tags == ["slow"]

    def test_default_tags_empty(self) -> None:
        assert ErrorCase().tags == []


class TestEvalResult:
    def test_serialization_round_trip(self) -> None:
        result = EvalResult(
            case_name="test",
            outcome=EvalOutcome.PASSED,
            duration_seconds=1.5,
            metrics={"acc": 0.9},
        )
        restored = EvalResult.model_validate_json(result.model_dump_json())
        assert restored.case_name == "test"
        assert restored.outcome == EvalOutcome.PASSED
        assert restored.metrics["acc"] == 0.9


class TestEvalRunner:
    def test_run_passing_case(self) -> None:
        runner = EvalRunner()
        result = runner.run_case(PassingCase())
        assert result.outcome == EvalOutcome.PASSED
        assert len(runner.results) == 1

    def test_run_error_case(self) -> None:
        runner = EvalRunner()
        result = runner.run_case(ErrorCase())
        assert result.outcome == EvalOutcome.ERROR
        assert result.error_message == "unexpected crash"
        assert result.error_type == "RuntimeError"

    def test_setup_teardown_called(self) -> None:
        runner = EvalRunner()
        tracker = SetupTracker()
        runner.run_case(tracker)
        assert tracker.setup_called is True
        assert tracker.teardown_called is True

    def test_teardown_on_error(self) -> None:
        """Teardown should still run even if the case errors."""

        class ErrorWithTeardown(EvalCase):
            def __init__(self) -> None:
                self.teardown_called = False

            @property
            def name(self) -> str:
                return "err_td"

            def teardown(self) -> None:
                self.teardown_called = True

            def run(self) -> EvalResult:
                raise ValueError("boom")

        case = ErrorWithTeardown()
        runner = EvalRunner()
        runner.run_case(case)
        assert case.teardown_called is True

    def test_duration_measured(self) -> None:
        import time

        class SlowCase(EvalCase):
            @property
            def name(self) -> str:
                return "slow"

            def run(self) -> EvalResult:
                time.sleep(0.02)
                return EvalResult(
                    case_name=self.name,
                    outcome=EvalOutcome.PASSED,
                    duration_seconds=0.0,
                )

        runner = EvalRunner()
        result = runner.run_case(SlowCase())
        assert result.duration_seconds >= 0.01

    def test_reset(self) -> None:
        runner = EvalRunner()
        runner.run_case(PassingCase())
        assert len(runner.results) == 1
        runner.reset()
        assert len(runner.results) == 0


class TestEvalSuite:
    def test_run_suite(self) -> None:
        suite = EvalSuite(name="test-suite", cases=[PassingCase(), FailingCase()])
        runner = EvalRunner()
        results = runner.run_suite(suite)
        assert len(results) == 2

    def test_filter_by_tag(self) -> None:
        suite = EvalSuite(
            name="tagged", cases=[PassingCase(), FailingCase(), ErrorCase()]
        )
        runner = EvalRunner()
        results = runner.run_suite(suite, tag="fast")
        assert len(results) == 1
        assert results[0].case_name == "passing"

    def test_add_case(self) -> None:
        suite = EvalSuite(name="dynamic")
        suite.add(PassingCase())
        assert len(suite.cases) == 1


class TestMetrics:
    def test_compute_basic(self) -> None:
        results = [
            EvalResult(case_name="a", outcome=EvalOutcome.PASSED, duration_seconds=1.0),
            EvalResult(case_name="b", outcome=EvalOutcome.PASSED, duration_seconds=2.0),
            EvalResult(
                case_name="c",
                outcome=EvalOutcome.FAILED,
                duration_seconds=0.5,
                error_type="AssertionError",
            ),
        ]
        metrics = compute_metrics(results)

        assert metrics.total_cases == 3
        assert metrics.passed == 2
        assert metrics.failed == 1
        assert metrics.errors == 0
        assert metrics.success_rate == pytest.approx(2.0 / 3.0)
        assert metrics.total_duration_seconds == pytest.approx(3.5)
        assert metrics.avg_duration_seconds == pytest.approx(3.5 / 3.0)

    def test_failure_types(self) -> None:
        results = [
            EvalResult(
                case_name="a",
                outcome=EvalOutcome.FAILED,
                duration_seconds=0.0,
                error_type="AssertionError",
            ),
            EvalResult(
                case_name="b",
                outcome=EvalOutcome.ERROR,
                duration_seconds=0.0,
                error_type="RuntimeError",
            ),
            EvalResult(
                case_name="c",
                outcome=EvalOutcome.FAILED,
                duration_seconds=0.0,
                error_type="AssertionError",
            ),
        ]
        metrics = compute_metrics(results)

        assert metrics.failure_types["AssertionError"] == 2
        assert metrics.failure_types["RuntimeError"] == 1

    def test_per_case_metrics(self) -> None:
        results = [
            EvalResult(
                case_name="a",
                outcome=EvalOutcome.PASSED,
                duration_seconds=0.0,
                metrics={"accuracy": 0.95, "f1": 0.9},
            ),
        ]
        metrics = compute_metrics(results)
        assert metrics.per_case_metrics["a"]["accuracy"] == 0.95

    def test_empty_results(self) -> None:
        metrics = compute_metrics([])
        assert metrics.total_cases == 0
        assert metrics.success_rate == 0.0

    def test_skipped_excluded_from_rate(self) -> None:
        results = [
            EvalResult(case_name="a", outcome=EvalOutcome.PASSED, duration_seconds=1.0),
            EvalResult(case_name="b", outcome=EvalOutcome.SKIPPED, duration_seconds=0.0),
        ]
        metrics = compute_metrics(results)
        assert metrics.total_cases == 2
        assert metrics.skipped == 1
        assert metrics.success_rate == pytest.approx(1.0)  # 1 passed / 1 executed

    def test_runner_compute_metrics(self) -> None:
        runner = EvalRunner()
        runner.run_case(PassingCase())
        runner.run_case(FailingCase())

        metrics = runner.compute_metrics()
        assert metrics.total_cases == 2
        assert metrics.passed == 1
        assert metrics.failed == 1
        assert metrics.success_rate == pytest.approx(0.5)
