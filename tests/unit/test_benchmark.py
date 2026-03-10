"""Tests for benchmarking engine."""

from __future__ import annotations

import pytest

from agentos.intelligence.benchmark import BenchmarkRunner, BenchmarkReport
from agentos.schemas.benchmark import BenchmarkConfig, BenchmarkRun, BenchmarkStatus


@pytest.fixture
def runner() -> BenchmarkRunner:
    return BenchmarkRunner(BenchmarkConfig(backends=["backend-a", "backend-b"]))


class TestBenchmarkRun:
    def test_create_run(self, runner):
        run = runner.create_run("Summarize this document")
        assert run.run_id
        assert run.task_description == "Summarize this document"
        assert len(run.backends) == 2
        assert "backend-a" in run.results
        assert "backend-b" in run.results

    def test_create_run_custom_backends(self, runner):
        run = runner.create_run("Test task", backends=["custom-1", "custom-2", "custom-3"])
        assert len(run.backends) == 3

    def test_run_starts_pending(self, runner):
        run = runner.create_run("Test")
        assert run.status == BenchmarkStatus.PENDING
        for result in run.results.values():
            assert result.status == BenchmarkStatus.PENDING

    def test_get_run(self, runner):
        run = runner.create_run("Test")
        retrieved = runner.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.run_id == run.run_id

    def test_get_nonexistent_run(self, runner):
        assert runner.get_run("nonexistent") is None

    def test_list_runs(self, runner):
        runner.create_run("Run 1")
        runner.create_run("Run 2")
        assert len(runner.list_runs()) == 2


class TestRecordResult:
    def test_record_success(self, runner):
        run = runner.create_run("Test")
        result = runner.record_result(
            run.run_id, "backend-a",
            duration_seconds=5.2,
            total_tokens=1500,
            estimated_cost_usd=0.05,
            output_summary="Task completed successfully",
            quality_score=0.85,
        )
        assert result.status == BenchmarkStatus.COMPLETED
        assert result.duration_seconds == 5.2
        assert result.total_tokens == 1500
        assert result.quality_score == 0.85

    def test_record_failure(self, runner):
        run = runner.create_run("Test")
        result = runner.record_result(
            run.run_id, "backend-a",
            duration_seconds=1.0,
            total_tokens=0,
            estimated_cost_usd=0.0,
            output_summary="",
            error="Timeout exceeded",
        )
        assert result.status == BenchmarkStatus.FAILED
        assert result.error == "Timeout exceeded"

    def test_run_completes_when_all_done(self, runner):
        run = runner.create_run("Test")
        runner.record_result(run.run_id, "backend-a", 1.0, 100, 0.01, "done")
        assert run.status == BenchmarkStatus.PENDING  # Only one done
        runner.record_result(run.run_id, "backend-b", 2.0, 200, 0.02, "done")
        assert run.status == BenchmarkStatus.COMPLETED

    def test_unknown_run_raises(self, runner):
        with pytest.raises(ValueError, match="Unknown run"):
            runner.record_result("bad-id", "x", 1.0, 0, 0.0, "")

    def test_unknown_backend_raises(self, runner):
        run = runner.create_run("Test")
        with pytest.raises(ValueError, match="Unknown backend"):
            runner.record_result(run.run_id, "nonexistent", 1.0, 0, 0.0, "")


class TestReport:
    def test_generate_report(self, runner):
        run = runner.create_run("Test")
        runner.record_result(run.run_id, "backend-a", 5.0, 1000, 0.10, "done", quality_score=0.8)
        runner.record_result(run.run_id, "backend-b", 3.0, 800, 0.15, "done", quality_score=0.9)
        report = runner.generate_report(run.run_id)
        assert report.fastest_backend == "backend-b"
        assert report.cheapest_backend == "backend-a"
        assert report.best_quality_backend == "backend-b"

    def test_report_with_failure(self, runner):
        run = runner.create_run("Test")
        runner.record_result(run.run_id, "backend-a", 5.0, 1000, 0.10, "done", quality_score=0.8)
        runner.record_result(run.run_id, "backend-b", 1.0, 0, 0.0, "", error="Failed")
        report = runner.generate_report(run.run_id)
        assert report.fastest_backend == "backend-a"
        assert report.cheapest_backend == "backend-a"

    def test_report_no_quality_scores(self, runner):
        run = runner.create_run("Test")
        runner.record_result(run.run_id, "backend-a", 5.0, 1000, 0.10, "done")
        runner.record_result(run.run_id, "backend-b", 3.0, 800, 0.15, "done")
        report = runner.generate_report(run.run_id)
        assert report.best_quality_backend is None

    def test_report_to_dict(self, runner):
        run = runner.create_run("Test")
        runner.record_result(run.run_id, "backend-a", 5.0, 1000, 0.10, "done")
        runner.record_result(run.run_id, "backend-b", 3.0, 800, 0.15, "done")
        report = runner.generate_report(run.run_id)
        d = report.to_dict()
        assert d["run_id"] == run.run_id
        assert "results" in d
        assert "fastest_backend" in d

    def test_unknown_run_raises(self, runner):
        with pytest.raises(ValueError):
            runner.generate_report("bad-id")


class TestSchemaRoundTrip:
    def test_benchmark_run_serialization(self):
        run = BenchmarkRun(
            run_id="r1",
            task_description="Test",
            backends=["a", "b"],
        )
        data = run.model_dump(mode="json")
        restored = BenchmarkRun.model_validate(data)
        assert restored.run_id == "r1"

    def test_benchmark_config_serialization(self):
        config = BenchmarkConfig(backends=["a", "b"], timeout_seconds=600)
        data = config.model_dump(mode="json")
        restored = BenchmarkConfig.model_validate(data)
        assert restored.timeout_seconds == 600
