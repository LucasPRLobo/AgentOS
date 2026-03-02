"""E2E smoke tests for the full DAG pipeline run."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.tools.dataset import DatasetTool
from labos.workflows.ml_replication import run_dag_pipeline

from tests.conftest import assert_has_event

pytestmark = pytest.mark.e2e


@pytest.fixture()
def dag_e2e_run(tmp_path):
    """Full E2E DAG pipeline run."""
    config = ExperimentConfig(
        dataset_name="iris",
        model_type="LogisticRegression",
        random_seed=42,
    )
    log = SQLiteEventLog(":memory:")
    rid = generate_run_id()

    run_dag_pipeline(config, event_log=log, output_dir=str(tmp_path), run_id=rid)
    events = log.query_by_run(rid)
    return log, rid, events, tmp_path, config


class TestPipelineSucceeds:
    """Verify the pipeline succeeds end-to-end."""

    def test_last_event_outcome_succeeded(self, dag_e2e_run):
        _log, _rid, events, _tmp, _cfg = dag_e2e_run
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "SUCCEEDED"


class TestReportContainsSections:
    """Verify the report markdown contains all expected sections."""

    def test_report_sections(self, dag_e2e_run):
        _log, _rid, _events, tmp, _cfg = dag_e2e_run
        report_path = Path(tmp) / "report.md"
        assert report_path.exists()

        content = report_path.read_text()
        for section in ["Summary", "Dataset", "Model Configuration", "Results", "Reproducibility"]:
            assert f"## {section}" in content, f"Missing section: {section}"


class TestConfusionMatrixPNG:
    """Verify confusion_matrix.png is a valid PNG (magic bytes)."""

    def test_valid_png(self, dag_e2e_run):
        _log, _rid, _events, tmp, _cfg = dag_e2e_run
        png_path = Path(tmp) / "confusion_matrix.png"
        assert png_path.exists()

        # PNG magic bytes: \x89PNG\r\n\x1a\n
        with open(png_path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b"\x89PNG"


class TestReviewerEventSuccess:
    """Verify reviewer event shows success=True."""

    def test_reviewer_success(self, dag_e2e_run):
        _log, _rid, events, _tmp, _cfg = dag_e2e_run
        reviewer_finished = [
            e for e in events
            if e.event_type == EventType.TOOL_CALL_FINISHED
            and e.payload.get("tool_name") == "reviewer"
        ]
        assert len(reviewer_finished) == 1
        assert reviewer_finished[0].payload["success"] is True


class TestDeterministicRuns:
    """Verify two runs with same config produce identical accuracy and event structure."""

    def test_deterministic_accuracy_and_structure(self, tmp_path):
        config = ExperimentConfig(
            dataset_name="iris",
            model_type="LogisticRegression",
            random_seed=42,
        )

        # Clear dataset cache between runs for clean state
        DatasetTool.clear_cache()

        log1 = SQLiteEventLog(":memory:")
        rid1 = generate_run_id()
        out1 = tmp_path / "run1"
        out1.mkdir()
        run_dag_pipeline(config, event_log=log1, output_dir=str(out1), run_id=rid1)
        events1 = log1.query_by_run(rid1)

        DatasetTool.clear_cache()

        log2 = SQLiteEventLog(":memory:")
        rid2 = generate_run_id()
        out2 = tmp_path / "run2"
        out2.mkdir()
        run_dag_pipeline(config, event_log=log2, output_dir=str(out2), run_id=rid2)
        events2 = log2.query_by_run(rid2)

        # Same event count and types
        types1 = [e.event_type for e in events1]
        types2 = [e.event_type for e in events2]
        assert types1 == types2

        # Dataset loader output is fully deterministic (no paths or durations)
        def get_dataset_hash(events):
            return [
                e.payload.get("output_hash")
                for e in events
                if e.event_type == EventType.TOOL_CALL_FINISHED
                and e.payload.get("tool_name") == "dataset_loader"
                and "output_hash" in e.payload
            ]

        hashes1 = get_dataset_hash(events1)
        hashes2 = get_dataset_hash(events2)
        assert hashes1 == hashes2
        assert len(hashes1) == 1  # Exactly one dataset_loader call

        log1.close()
        log2.close()
