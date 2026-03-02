"""Integration tests for the LabOS DAG pipeline event stream and artifacts."""

from __future__ import annotations

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.workflows.ml_replication import run_dag_pipeline

from tests.conftest import assert_has_event

pytestmark = pytest.mark.integration


@pytest.fixture()
def dag_run(tmp_path):
    """Run the DAG pipeline once and return (event_log, run_id, events)."""
    config = ExperimentConfig(
        dataset_name="iris",
        model_type="LogisticRegression",
        random_seed=42,
    )
    log = SQLiteEventLog(":memory:")
    rid = generate_run_id()

    run_dag_pipeline(config, event_log=log, output_dir=str(tmp_path), run_id=rid)

    events = log.query_by_run(rid)
    return log, rid, events, tmp_path


class TestDAGEventCount:
    """Verify the exact number of events produced by the DAG pipeline."""

    def test_exactly_24_events(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        # RunStarted(1) + 6*(TaskStarted+TaskFinished)(12) + tools(10) + RunFinished(1) = 24
        assert len(events) == 24


class TestDAGEventSequence:
    """Verify the macro event sequence."""

    def test_starts_with_run_started_ends_with_run_finished(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[-1].event_type == EventType.RUN_FINISHED

    def test_six_task_pairs(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        task_started = [e for e in events if e.event_type == EventType.TASK_STARTED]
        task_finished = [e for e in events if e.event_type == EventType.TASK_FINISHED]
        assert len(task_started) == 6
        assert len(task_finished) == 6


class TestDAGToolCallEvents:
    """Verify ToolCallStarted events for all 5 tools."""

    def test_all_five_tools_called(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        tool_started = [e for e in events if e.event_type == EventType.TOOL_CALL_STARTED]
        tool_names = [e.payload["tool_name"] for e in tool_started]

        expected_tools = {"dataset_loader", "python_runner", "plot_generator", "report_generator", "reviewer"}
        assert set(tool_names) == expected_tools


class TestDAGArtifacts:
    """Verify artifacts exist with non-empty hashes."""

    def test_artifacts_have_hashes(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        tool_finished = [e for e in events if e.event_type == EventType.TOOL_CALL_FINISHED]

        for evt in tool_finished:
            assert evt.payload["success"] is True
            # Tools that produce output hashes
            if "output_hash" in evt.payload:
                assert len(evt.payload["output_hash"]) == 64  # SHA-256 hex length


class TestDAGReviewerPasses:
    """Verify the reviewer tool passes (no missing fields)."""

    def test_reviewer_success(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        reviewer_finished = [
            e for e in events
            if e.event_type == EventType.TOOL_CALL_FINISHED
            and e.payload.get("tool_name") == "reviewer"
        ]
        assert len(reviewer_finished) == 1
        assert reviewer_finished[0].payload["success"] is True


class TestDAGSideEffectClassifications:
    """Verify side-effect classifications are correct for each tool."""

    def test_side_effect_classifications(self, dag_run):
        _log, _rid, events, _tmp = dag_run
        tool_started = [e for e in events if e.event_type == EventType.TOOL_CALL_STARTED]

        expected_side_effects = {
            "dataset_loader": "READ",
            "python_runner": "PURE",
            "plot_generator": "WRITE",
            "report_generator": "WRITE",
            "reviewer": "PURE",
        }

        for evt in tool_started:
            name = evt.payload["tool_name"]
            assert evt.payload["side_effect"] == expected_side_effects[name], (
                f"Tool {name}: expected {expected_side_effects[name]}, "
                f"got {evt.payload['side_effect']}"
            )
