"""Tests for DAGExecutor."""

from __future__ import annotations

import threading
import time

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


def _make_workflow(
    tasks: dict[str, TaskConfig],
    budget: BudgetSpec | None = None,
) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="test-workflow",
        budget=budget or BudgetSpec(),
        tasks=tasks,
    )


def _success_executor(task_id: str, config: TaskConfig) -> TaskStatus:
    return TaskStatus.SUCCEEDED


def _fail_executor(task_id: str, config: TaskConfig) -> TaskStatus:
    return TaskStatus.FAILED


def _make_executor(
    workflow: WorkflowDefinition,
    event_log: SQLiteEventLog,
    seq: SeqCounter,
    task_executor=None,
) -> DAGExecutor:
    budget_mgr = BudgetManager(
        workflow_spec=workflow.budget,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )
    return DAGExecutor(
        workflow=workflow,
        event_log=event_log,
        seq=seq,
        budget_manager=budget_mgr,
        task_executor=task_executor or _success_executor,
    )


class TestLinearExecution:
    def test_linear_execution(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """A -> B -> C executes in order, all events emitted."""
        execution_order: list[str] = []

        def tracking_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            execution_order.append(task_id)
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
        })
        executor = _make_executor(wf, event_log, seq, tracking_executor)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert execution_order == ["a", "b", "c"]
        assert set(result.completed_tasks) == {"a", "b", "c"}


class TestParallelExecution:
    def test_parallel_execution(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """A and B run concurrently (no dependency between them)."""
        running = threading.Event()
        both_started = threading.Barrier(2, timeout=5)

        def parallel_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            both_started.wait()  # blocks until both threads reach here
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b"),
        })
        executor = _make_executor(wf, event_log, seq, parallel_executor)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"a", "b"}


class TestFanoutFanin:
    def test_fanout_fanin(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """A -> (B, C, D) -> E, E waits for all three."""
        execution_order: list[str] = []
        lock = threading.Lock()

        def tracking_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            with lock:
                execution_order.append(task_id)
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["a"]),
            "d": TaskConfig(name="d", depends_on=["a"]),
            "e": TaskConfig(name="e", depends_on=["b", "c", "d"]),
        })
        executor = _make_executor(wf, event_log, seq, tracking_executor)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert execution_order[0] == "a"
        assert execution_order[-1] == "e"
        assert set(execution_order[1:4]) == {"b", "c", "d"}


class TestValidation:
    def test_cycle_detection(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({
            "a": TaskConfig(name="a", depends_on=["c"]),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
        })
        executor = _make_executor(wf, event_log, seq)

        with pytest.raises(ValueError, match="cycle"):
            executor.run("test-wf")

    def test_missing_dependency(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({
            "a": TaskConfig(name="a", depends_on=["nonexistent"]),
        })
        executor = _make_executor(wf, event_log, seq)

        with pytest.raises(ValueError, match="does not exist"):
            executor.run("test-wf")


class TestFailureHandling:
    def test_task_failure_blocks_dependents(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """When B fails, C (depends on B) is not started."""
        executed: list[str] = []

        def selective_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            executed.append(task_id)
            if task_id == "b":
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
        })
        executor = _make_executor(wf, event_log, seq, selective_executor)
        result = executor.run("test-wf")

        assert result.status == "failed"
        assert "c" not in executed
        assert "b" in result.failed_tasks
        assert "c" in result.skipped_tasks


class TestConcurrencyLimit:
    def test_concurrency_limit(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """With limit=2, at most 2 tasks run simultaneously."""
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        def counting_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            nonlocal max_concurrent, current_concurrent
            with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            time.sleep(0.05)
            with lock:
                current_concurrent -= 1
            return TaskStatus.SUCCEEDED

        wf = _make_workflow(
            {
                "a": TaskConfig(name="a"),
                "b": TaskConfig(name="b"),
                "c": TaskConfig(name="c"),
                "d": TaskConfig(name="d"),
            },
            budget=BudgetSpec(max_concurrent_tasks=2),
        )
        executor = _make_executor(wf, event_log, seq, counting_executor)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert max_concurrent <= 2


class TestWorkflowEvents:
    def test_workflow_started_event(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({"a": TaskConfig(name="a")})
        executor = _make_executor(wf, event_log, seq)
        executor.run("test-wf")

        events = event_log.query(
            workflow_id="test-wf", event_type=EventType.WORKFLOW_STARTED
        )
        assert len(events) == 1
        assert events[0].payload["workflow_name"] == "test-workflow"
        assert events[0].payload["task_count"] == 1

    def test_workflow_completed_event(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({"a": TaskConfig(name="a")})
        executor = _make_executor(wf, event_log, seq)
        executor.run("test-wf")

        events = event_log.query(
            workflow_id="test-wf", event_type=EventType.WORKFLOW_COMPLETED
        )
        assert len(events) == 1
        assert events[0].payload["status"] == "succeeded"


class TestEdgeCases:
    def test_single_task(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({"solo": TaskConfig(name="solo")})
        executor = _make_executor(wf, event_log, seq)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert result.completed_tasks == ["solo"]

    def test_empty_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        wf = _make_workflow({})
        executor = _make_executor(wf, event_log, seq)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert result.completed_tasks == []

    def test_diamond_dag(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """A -> (B, C) -> D (classic diamond)."""
        execution_order: list[str] = []
        lock = threading.Lock()

        def tracking_executor(task_id: str, config: TaskConfig) -> TaskStatus:
            with lock:
                execution_order.append(task_id)
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["a"]),
            "d": TaskConfig(name="d", depends_on=["b", "c"]),
        })
        executor = _make_executor(wf, event_log, seq, tracking_executor)
        result = executor.run("test-wf")

        assert result.status == "succeeded"
        assert execution_order[0] == "a"
        assert execution_order[-1] == "d"
        assert set(execution_order[1:3]) == {"b", "c"}
