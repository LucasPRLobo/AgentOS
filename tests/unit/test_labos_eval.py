"""Tests for LabOS evaluation cases."""

from agentos.eval.eval_case import EvalOutcome
from agentos.eval.runner import EvalRunner, EvalSuite

from labos.eval.replication_eval import (
    DAGPipelineEval,
    DatasetDeterminismEval,
    ReviewerValidationEval,
    TrainingDeterminismEval,
)
from labos.tools.dataset import DatasetTool

import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    DatasetTool.clear_cache()
    yield
    DatasetTool.clear_cache()


class TestDatasetDeterminismEval:
    def test_passes(self) -> None:
        case = DatasetDeterminismEval()
        assert case.name == "dataset_determinism"
        assert "determinism" in case.tags

        result = case.run()
        assert result.outcome == EvalOutcome.PASSED
        assert result.metrics["checksums_match"] == 1.0


class TestTrainingDeterminismEval:
    def test_passes(self) -> None:
        case = TrainingDeterminismEval()
        result = case.run()
        assert result.outcome == EvalOutcome.PASSED
        assert result.metrics["metrics_match"] == 1.0
        assert result.metrics["run1_accuracy"] == result.metrics["run2_accuracy"]


class TestDAGPipelineEval:
    def test_passes(self) -> None:
        case = DAGPipelineEval()
        result = case.run()
        assert result.outcome == EvalOutcome.PASSED
        assert result.metrics["total_events"] > 0


class TestReviewerValidationEval:
    def test_passes(self) -> None:
        case = ReviewerValidationEval()
        result = case.run()
        assert result.outcome == EvalOutcome.PASSED
        assert result.metrics["valid_passes"] == 1.0
        assert result.metrics["invalid_rejected"] == 1.0


class TestEvalSuiteIntegration:
    def test_full_suite(self) -> None:
        suite = EvalSuite(
            name="labos_replication",
            cases=[
                DatasetDeterminismEval(),
                TrainingDeterminismEval(),
                DAGPipelineEval(),
                ReviewerValidationEval(),
            ],
        )
        runner = EvalRunner()
        results = runner.run_suite(suite)
        assert len(results) == 4
        assert all(r.outcome == EvalOutcome.PASSED for r in results)

        metrics = runner.compute_metrics()
        assert metrics.total_cases == 4
        assert metrics.passed == 4
        assert metrics.success_rate == 1.0
