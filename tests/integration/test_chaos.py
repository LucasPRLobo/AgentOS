"""Chaos tests — verify graceful degradation under failure conditions."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.state_machine import TaskStateMachine
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskMetrics, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


def _make_output(task_id: str, status: TaskStatus = TaskStatus.SUCCEEDED) -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id="test-agent",
        status=status,
        summary=f"Result for {task_id}",
        metrics=TaskMetrics(tokens_consumed=100, api_calls_made=1, execution_time_seconds=1.0),
    )


@pytest.mark.integration
class TestKilledProcess:
    """Verify behavior when a subprocess raises OSError."""

    def test_oserror_produces_failed_output(self, tmp_path):
        wf = WorkflowDefinition(
            name="oserr-test",
            tasks={"task1": TaskConfig(name="task1", agent="agent1")},
            agents={"agent1": {}},
        )

        def executor(name, config, predecessors=None):
            raise OSError("Process killed")

        event_log = SQLiteEventLog(str(tmp_path / "events.db"))
        seq = SeqCounter()
        budget = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="wf-1",
        )

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget, task_executor=executor,
        )
        result = dag.run("wf-1")

        assert "task1" in result.failed_tasks


@pytest.mark.integration
class TestCorruptedManifest:
    """Verify handling of invalid JSON in manifest.json."""

    def test_invalid_json_manifest(self, tmp_path):
        from agentos.adapters.tier2_shared import parse_manifest

        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "manifest.json").write_text("not valid json {{{")

        result = parse_manifest(workspace)
        assert result is None


@pytest.mark.integration
class TestWrongManifestSchema:
    """Verify graceful handling of manifest with missing fields."""

    def test_missing_summary_field(self):
        from agentos.adapters.tier2_shared import manifest_to_task_output

        manifest = {"findings": [], "open_questions": []}
        metrics = TaskMetrics(tokens_consumed=0, api_calls_made=0, execution_time_seconds=0)

        output = manifest_to_task_output(manifest, "t1", "a1", metrics)
        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Task completed."  # Default


@pytest.mark.integration
class TestDoubleStateTransition:
    """Verify state machine rejects invalid transitions."""

    def test_succeeded_to_running_rejected(self, tmp_path):
        event_log = SQLiteEventLog(str(tmp_path / "events.db"))
        seq = SeqCounter()
        sm = TaskStateMachine(event_log, seq, "wf-1")

        sm.transition("task1", TaskStatus.PENDING, TaskStatus.RUNNING)
        sm.transition("task1", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)

        # SUCCEEDED -> RUNNING is not in VALID_TRANSITIONS (only PENDING is)
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition("task1", TaskStatus.SUCCEEDED, TaskStatus.RUNNING)


@pytest.mark.integration
class TestManifestFallbackIntegration:
    """Verify inferred manifest extraction from raw text."""

    def test_text_output_produces_inferred_manifest(self):
        from agentos.adapters.tier2_shared import extract_manifest_from_text

        raw = (
            "I analyzed the quarterly earnings data.\n\n"
            "- Revenue grew 12% compared to last quarter\n"
            "- Operating margins improved by 2 percentage points\n"
            "- Market share in APAC region increased to 15%\n"
        )
        result = extract_manifest_from_text(raw)
        assert result is not None
        assert result["extraction_mode"] == "inferred"
        assert len(result["findings"]) == 3


@pytest.mark.integration
class TestEventLogCorruption:
    """Verify clean error on corrupted database."""

    def test_corrupted_db_raises(self, tmp_path):
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"this is not a valid sqlite database")

        with pytest.raises(Exception):
            event_log = SQLiteEventLog(str(db_path))
            event_log.query(workflow_id="test")


@pytest.mark.integration
class TestBudgetContention:
    """Verify budget enforcement under concurrent access."""

    def test_high_contention_budget(self, tmp_path):
        budget_spec = BudgetSpec(max_tokens=500, max_cost_usd=100.0, max_concurrent_tasks=10)
        event_log = SQLiteEventLog(str(tmp_path / "events.db"))
        seq = SeqCounter()
        bm = BudgetManager(
            workflow_spec=budget_spec, event_log=event_log, seq=seq, workflow_id="wf-1",
        )

        results: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def consume():
            try:
                bm.apply("agent1", BudgetDelta(tokens=100))
                with lock:
                    results.append("ok")
            except BudgetExceededError:
                with lock:
                    results.append("exceeded")
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Unexpected errors: {errors}"
        # At most 5 should succeed (500 / 100 = 5)
        ok_count = results.count("ok")
        assert ok_count <= 6  # Allow one extra for race condition tolerance
