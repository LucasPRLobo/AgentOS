"""E2E tests for STRICT replay mode."""

from __future__ import annotations

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.observability.replay import ReplayEngine, ReplayMode
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.tools.dataset import DatasetTool
from labos.workflows.ml_replication import run_dag_pipeline

pytestmark = [pytest.mark.e2e, pytest.mark.replay]


@pytest.fixture()
def recorded_run(tmp_path):
    """Run DAG pipeline and return log + run_id for replay."""
    config = ExperimentConfig(
        dataset_name="iris",
        model_type="LogisticRegression",
        random_seed=42,
    )
    log = SQLiteEventLog(":memory:")
    rid = generate_run_id()
    run_dag_pipeline(config, event_log=log, output_dir=str(tmp_path), run_id=rid)
    return log, rid


class TestStrictReplay:
    """Verify STRICT replay reproduces the same events."""

    def test_strict_replay_same_events(self, recorded_run):
        log, rid = recorded_run
        engine = ReplayEngine(log)

        result = engine.replay(rid, mode=ReplayMode.STRICT)

        original_events = log.query_by_run(rid)
        assert len(result.events) == len(original_events)

        # Event types must match
        original_types = [e.event_type for e in original_events]
        replay_types = [e.event_type for e in result.events]
        assert original_types == replay_types
        log.close()

    def test_tool_output_hashes_match(self, recorded_run):
        log, rid = recorded_run
        engine = ReplayEngine(log)

        result = engine.replay(rid, mode=ReplayMode.STRICT)

        # All ToolCallFinished events should be in tool_outputs
        original_finished = [
            e for e in log.query_by_run(rid)
            if e.event_type == EventType.TOOL_CALL_FINISHED
        ]

        for event in original_finished:
            assert event.seq in result.tool_outputs
            replayed = result.tool_outputs[event.seq]
            # The replayed output should contain the same output_hash
            if "output_hash" in event.payload:
                assert replayed.get("output_hash") == event.payload["output_hash"]
        log.close()

    def test_compare_runs_same_structure(self, tmp_path):
        config = ExperimentConfig(
            dataset_name="iris",
            model_type="LogisticRegression",
            random_seed=42,
        )

        log = SQLiteEventLog(":memory:")

        DatasetTool.clear_cache()
        rid1 = generate_run_id()
        out1 = tmp_path / "cmp1"
        out1.mkdir()
        run_dag_pipeline(config, event_log=log, output_dir=str(out1), run_id=rid1)

        DatasetTool.clear_cache()
        rid2 = generate_run_id()
        out2 = tmp_path / "cmp2"
        out2.mkdir()
        run_dag_pipeline(config, event_log=log, output_dir=str(out2), run_id=rid2)

        engine = ReplayEngine(log)
        comparison = engine.compare_runs(rid1, rid2)

        assert comparison.same_structure is True
        assert comparison.events_a_count == comparison.events_b_count
        log.close()
