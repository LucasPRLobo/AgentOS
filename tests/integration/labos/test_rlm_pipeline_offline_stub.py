"""Integration tests for the LabOS RLM pipeline with offline mock LM provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.workflows.ml_replication import run_rlm_pipeline

from tests.conftest import MockLMProvider, assert_has_event

pytestmark = pytest.mark.integration


# The mock LM must generate valid Python code that calls the injected functions
# in the correct order, then sets FINAL.
_RLM_SCRIPTED_RESPONSES = [
    # Step 1: Load dataset
    'dataset_record = load_dataset()\nprint("Dataset loaded:", dataset_record["name"])',
    # Step 2: Train model
    'training_result = train_model(dataset_record)\nprint("Accuracy:", training_result["metric_value"])',
    # Step 3: Generate plot
    'plot_record = generate_plot(dataset_record, training_result)\nprint("Plot:", plot_record["path"])',
    # Step 4: Generate report
    'report_record = generate_report(dataset_record, training_result, plot_record)\nprint("Report:", report_record["path"])',
    # Step 5: Review
    'review_result = review_run(dataset_record, training_result, plot_record, report_record)\nprint("Review:", review_result["passed"])',
    # Step 6: Set FINAL
    'FINAL = f"Replication complete. Accuracy: {training_result[\'metric_value\']:.4f}"',
]


@pytest.fixture()
def rlm_run(tmp_path):
    """Run the RLM pipeline with scripted mock responses."""
    config = ExperimentConfig(
        dataset_name="iris",
        model_type="LogisticRegression",
        random_seed=42,
    )
    log = SQLiteEventLog(":memory:")
    provider = MockLMProvider(responses=_RLM_SCRIPTED_RESPONSES)

    run_id, final_result = run_rlm_pipeline(
        config,
        provider,
        event_log=log,
        output_dir=str(tmp_path),
        max_iterations=20,
    )

    events = log.query_by_run(run_id)
    return log, run_id, events, final_result, tmp_path


class TestRLMCompletion:
    """Verify the RLM pipeline completes with scripted mock."""

    def test_rlm_completes_with_final(self, rlm_run):
        _log, _rid, events, final_result, _tmp = rlm_run
        assert final_result is not None
        assert "Accuracy" in final_result

        # RunFinished should show SUCCEEDED
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "SUCCEEDED"


class TestRLMIterationEvents:
    """Verify RLMIterationStarted/Finished events are present."""

    def test_iteration_events_present(self, rlm_run):
        _log, _rid, events, _final, _tmp = rlm_run

        iter_started = [e for e in events if e.event_type == EventType.RLM_ITERATION_STARTED]
        iter_finished = [e for e in events if e.event_type == EventType.RLM_ITERATION_FINISHED]

        assert len(iter_started) >= 6  # At least 6 iterations for 6 steps
        assert len(iter_finished) >= 6
        assert len(iter_started) == len(iter_finished)


class TestRLMArtifacts:
    """Verify artifacts (PNG + MD) are written to output_dir."""

    def test_png_and_md_artifacts(self, rlm_run):
        _log, _rid, _events, _final, tmp = rlm_run

        png_files = list(Path(tmp).glob("*.png"))
        md_files = list(Path(tmp).glob("*.md"))

        assert len(png_files) >= 1, "No PNG files found"
        assert len(md_files) >= 1, "No MD files found"

        # Verify PNG is non-empty
        for png in png_files:
            assert png.stat().st_size > 0


class TestRLMFinalContainsAccuracy:
    """Verify FINAL string contains an accuracy value."""

    def test_final_contains_accuracy(self, rlm_run):
        _log, _rid, _events, final_result, _tmp = rlm_run
        assert final_result is not None
        # Should contain a decimal number (accuracy)
        assert any(c.isdigit() for c in final_result)
        assert "Accuracy" in final_result
