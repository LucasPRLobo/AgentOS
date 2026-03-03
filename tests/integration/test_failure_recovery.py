"""Integration tests — failure recovery in DAG execution.

Tests: executor exceptions, budget exhaustion during DAG, subprocess errors,
partial predecessor context, cascading failures.
"""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


# ---------------------------------------------------------------------------
# Tests: Executor exceptions
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestExecutorExceptions:
    """DAGExecutor catches exceptions from task executors."""

    def test_valueerror_caught_task_failed(self, event_log, seq):
        wf = WorkflowDefinition(
            name="exc-test", tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
            }, agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f1",
        )

        def executor(name, config, predecessors=None):
            if name == "a":
                raise ValueError("Something went wrong")
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f1")

        assert result.status == "failed"
        assert "a" in result.failed_tasks
        assert "b" in result.skipped_tasks

    def test_runtime_error_caught(self, event_log, seq):
        wf = WorkflowDefinition(
            name="rterr", tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f2",
        )

        def executor(name, config, predecessors=None):
            raise RuntimeError("Crash!")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f2")

        assert result.status == "failed"
        assert "a" in result.failed_tasks

    def test_exception_emits_failed_event(self, event_log, seq):
        wf = WorkflowDefinition(
            name="evt-test", tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f3",
        )

        def executor(name, config, predecessors=None):
            raise Exception("Boom")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f3")

        # Verify FAILED state event was emitted
        events = event_log.query(workflow_id="f3", event_type=EventType.TASK_STATE_CHANGED)
        states = {(e.payload["task_id"], e.payload["to_state"]) for e in events}
        assert ("a", "running") in states
        assert ("a", "failed") in states


# ---------------------------------------------------------------------------
# Tests: Budget exhaustion during DAG execution
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestBudgetExhaustionInDAG:
    """Budget runs out during multi-task DAG execution."""

    def test_first_task_exhausts_budget_second_fails(self, event_log, seq):
        """Task A uses all budget → Task B fails when trying to apply."""
        wf = WorkflowDefinition(
            name="budget-exhaust",
            budget=BudgetSpec(max_tokens=500),
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f4",
        )

        def executor(name, config, predecessors=None):
            # Both tasks try to use 400 tokens — second will exceed 500 limit
            budget_mgr.apply("ag1", BudgetDelta(tokens=400))
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f4")

        # Task A succeeds (400 < 500), task B fails (800 > 500)
        assert result.status == "failed"
        assert "a" in result.completed_tasks
        assert "b" in result.failed_tasks

    def test_parallel_budget_contention(self, event_log, seq):
        """Multiple parallel tasks compete for limited budget."""
        wf = WorkflowDefinition(
            name="contention",
            budget=BudgetSpec(max_tokens=500),
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag2"),
                "c": TaskConfig(name="c", agent="ag3"),
            },
            agents={"ag1": {}, "ag2": {}, "ag3": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f5",
        )

        def executor(name, config, predecessors=None):
            budget_mgr.apply(config.agent, BudgetDelta(tokens=200))
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f5")

        # 3 × 200 = 600 > 500, so at least one task should fail
        assert len(result.failed_tasks) >= 1
        total_tokens = budget_mgr.total_usage.tokens_used
        assert total_tokens <= 600  # At most all 3 applied


# ---------------------------------------------------------------------------
# Tests: Cascading failure through deep chains
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestCascadingFailure:
    """Failure at any point cascades to skip all dependents."""

    def test_deep_chain_failure_cascades(self, event_log, seq):
        """A → B → C → D → E: B fails → C, D, E all skipped."""
        wf = WorkflowDefinition(
            name="deep-chain",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
                "c": TaskConfig(name="c", agent="ag1", depends_on=["b"]),
                "d": TaskConfig(name="d", agent="ag1", depends_on=["c"]),
                "e": TaskConfig(name="e", agent="ag1", depends_on=["d"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f6",
        )

        def executor(name, config, predecessors=None):
            if name == "b":
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f6")

        assert result.status == "failed"
        assert "a" in result.completed_tasks
        assert "b" in result.failed_tasks
        assert set(result.skipped_tasks) == {"c", "d", "e"}

    def test_partial_failure_independent_branches_continue(self, event_log, seq):
        """A → B (fails), A → C (succeeds): C still runs."""
        wf = WorkflowDefinition(
            name="partial-fail",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
                "c": TaskConfig(name="c", agent="ag1", depends_on=["a"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="f7",
        )
        lock = threading.Lock()
        executed = []

        def executor(name, config, predecessors=None):
            with lock:
                executed.append(name)
            if name == "b":
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("f7")

        assert result.status == "failed"
        assert "a" in result.completed_tasks
        assert "b" in result.failed_tasks
        assert "c" in result.completed_tasks  # Independent branch still runs
