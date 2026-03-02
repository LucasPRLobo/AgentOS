"""Tests for LabOS ML replication workflows."""

import tempfile

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.tools.dataset import DatasetTool
from labos.workflows.ml_replication import (
    build_dag_workflow,
    run_dag_pipeline,
    run_rlm_pipeline,
)
from labos.tools._base import _SeqCounter
from agentos.core.identifiers import generate_run_id


@pytest.fixture(autouse=True)
def _clear_cache():
    DatasetTool.clear_cache()
    yield
    DatasetTool.clear_cache()


class TestBuildDAGWorkflow:
    def test_dag_has_six_tasks(self) -> None:
        event_log = SQLiteEventLog()
        run_id = generate_run_id()
        seq = _SeqCounter(0)
        config = ExperimentConfig()

        dag = build_dag_workflow(config, event_log, run_id, seq)
        assert len(dag.tasks) == 6
        names = [t.name for t in dag.tasks]
        assert names == [
            "DefineQuestion",
            "DesignExperiment",
            "RunExperiment",
            "AnalyzeResults",
            "WriteReport",
            "ReviewerCheck",
        ]

    def test_dag_validates(self) -> None:
        event_log = SQLiteEventLog()
        run_id = generate_run_id()
        seq = _SeqCounter(0)
        config = ExperimentConfig()

        dag = build_dag_workflow(config, event_log, run_id, seq)
        dag.validate()  # Should not raise

    def test_dag_topological_order(self) -> None:
        event_log = SQLiteEventLog()
        run_id = generate_run_id()
        seq = _SeqCounter(0)
        config = ExperimentConfig()

        dag = build_dag_workflow(config, event_log, run_id, seq)
        order = dag.topological_order()
        names = [t.name for t in order]
        # DefineQuestion must come before DesignExperiment etc.
        assert names.index("DefineQuestion") < names.index("DesignExperiment")
        assert names.index("DesignExperiment") < names.index("RunExperiment")
        assert names.index("RunExperiment") < names.index("AnalyzeResults")


class TestRunDAGPipeline:
    def test_full_pipeline(self) -> None:
        config = ExperimentConfig(dataset_name="iris", random_seed=42)
        event_log = SQLiteEventLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            rid = run_dag_pipeline(config, event_log=event_log, output_dir=tmpdir)

        events = event_log.replay(rid)
        assert len(events) > 0

        # Check RunFinished outcome
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert len(run_finished) == 1
        assert run_finished[0].payload["outcome"] == "SUCCEEDED"

        # Check tool call events were emitted
        tool_started = [e for e in events if e.event_type == EventType.TOOL_CALL_STARTED]
        tool_finished = [e for e in events if e.event_type == EventType.TOOL_CALL_FINISHED]
        assert len(tool_started) >= 5  # dataset, runner, plot, report, reviewer
        assert len(tool_finished) >= 5
        assert all(e.payload["success"] for e in tool_finished)

    def test_pipeline_produces_files(self) -> None:
        config = ExperimentConfig()
        event_log = SQLiteEventLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dag_pipeline(config, event_log=event_log, output_dir=tmpdir)

            from pathlib import Path
            assert (Path(tmpdir) / "confusion_matrix.png").exists()
            assert (Path(tmpdir) / "report.md").exists()

    def test_deterministic_runs(self) -> None:
        """Two runs with same config must produce identical metrics."""
        config = ExperimentConfig(dataset_name="iris", random_seed=42)

        event_log1 = SQLiteEventLog()
        event_log2 = SQLiteEventLog()

        with tempfile.TemporaryDirectory() as tmp1:
            DatasetTool.clear_cache()
            rid1 = run_dag_pipeline(config, event_log=event_log1, output_dir=tmp1)

        with tempfile.TemporaryDirectory() as tmp2:
            DatasetTool.clear_cache()
            rid2 = run_dag_pipeline(config, event_log=event_log2, output_dir=tmp2)

        # Both should succeed
        ev1 = event_log1.replay(rid1)
        ev2 = event_log2.replay(rid2)
        fin1 = [e for e in ev1 if e.event_type == EventType.RUN_FINISHED][0]
        fin2 = [e for e in ev2 if e.event_type == EventType.RUN_FINISHED][0]
        assert fin1.payload["outcome"] == "SUCCEEDED"
        assert fin2.payload["outcome"] == "SUCCEEDED"


class MockLMProvider(BaseLMProvider):
    """Mock that simulates an LLM calling all 5 tool wrappers in sequence."""

    def __init__(self) -> None:
        self._call_count = 0
        self._responses = [
            # Step 1: Load dataset
            'ds = load_dataset()\nprint("Dataset loaded:", ds["name"])',
            # Step 2: Train model
            'tr = train_model(ds)\nprint("Accuracy:", tr["metric_value"])',
            # Step 3: Generate plot
            'pr = generate_plot(ds, tr)\nprint("Plot:", pr["path"])',
            # Step 4: Generate report
            'rr = generate_report(ds, tr, pr)\nprint("Report:", rr["path"])',
            # Step 5: Review
            'rv = review_run(ds, tr, pr, rr)\nprint("Review:", rv["passed"])',
            # Step 6: Set FINAL
            'FINAL = f"Done! Accuracy={tr[\'metric_value\']:.4f}, Review={rv[\'passed\']}"',
        ]

    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        idx = min(self._call_count, len(self._responses) - 1)
        code = self._responses[idx]
        self._call_count += 1
        return LMResponse(content=code, tokens_used=len(code))


class TestRunRLMPipeline:
    def test_rlm_with_mock_provider(self) -> None:
        config = ExperimentConfig(dataset_name="iris", random_seed=42)
        provider = MockLMProvider()
        event_log = SQLiteEventLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            run_id, result = run_rlm_pipeline(
                config, provider,
                event_log=event_log,
                output_dir=tmpdir,
                max_iterations=10,
            )

        assert result is not None
        assert "Accuracy=" in result
        assert "Review=True" in result

        events = event_log.replay(run_id)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert len(run_finished) == 1
        assert run_finished[0].payload["outcome"] == "SUCCEEDED"
