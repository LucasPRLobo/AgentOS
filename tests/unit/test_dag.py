"""Tests for DAG workflow — topological order, parallel execution, cycle detection."""

import threading
import time

import pytest

from agentos.core.errors import TaskExecutionError
from agentos.runtime.dag import DAGExecutor, DAGWorkflow
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.task import TaskNode, TaskState
from agentos.schemas.events import EventType


def _ok() -> str:
    return "ok"


def _fail() -> None:
    raise ValueError("boom")


def _slow(seconds: float = 0.05) -> str:
    time.sleep(seconds)
    return "done"


class TestDAGWorkflow:
    def test_validate_simple(self) -> None:
        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        dag = DAGWorkflow(name="test", tasks=[a, b])
        dag.validate()  # should not raise

    def test_validate_cycle(self) -> None:
        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        # Create cycle: a depends on b, b depends on a
        a.depends_on = [b]
        dag = DAGWorkflow(name="cycle", tasks=[a, b])
        with pytest.raises(TaskExecutionError, match="cycle"):
            dag.validate()

    def test_validate_missing_dep(self) -> None:
        outside = TaskNode(name="outside", callable=_ok)
        a = TaskNode(name="a", callable=_ok, depends_on=[outside])
        dag = DAGWorkflow(name="missing", tasks=[a])
        with pytest.raises(TaskExecutionError, match="not in the workflow"):
            dag.validate()

    def test_topological_order_linear(self) -> None:
        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        c = TaskNode(name="c", callable=_ok, depends_on=[b])
        dag = DAGWorkflow(name="linear", tasks=[c, a, b])  # shuffled input

        order = dag.topological_order()
        names = [t.name for t in order]
        assert names.index("a") < names.index("b")
        assert names.index("b") < names.index("c")

    def test_topological_order_diamond(self) -> None:
        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        c = TaskNode(name="c", callable=_ok, depends_on=[a])
        d = TaskNode(name="d", callable=_ok, depends_on=[b, c])
        dag = DAGWorkflow(name="diamond", tasks=[d, c, b, a])

        order = dag.topological_order()
        names = [t.name for t in order]
        assert names.index("a") < names.index("b")
        assert names.index("a") < names.index("c")
        assert names.index("b") < names.index("d")
        assert names.index("c") < names.index("d")


class TestDAGExecutor:
    def test_linear_execution(self) -> None:
        log = SQLiteEventLog()
        executor = DAGExecutor(log)

        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        c = TaskNode(name="c", callable=_ok, depends_on=[b])
        dag = DAGWorkflow(name="linear", tasks=[a, b, c])

        run_id = executor.run(dag)
        assert all(t.state == TaskState.SUCCEEDED for t in dag.tasks)

        events = log.query_by_run(run_id)
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[-1].event_type == EventType.RUN_FINISHED
        assert events[-1].payload["outcome"] == "SUCCEEDED"

    def test_diamond_execution(self) -> None:
        log = SQLiteEventLog()
        executor = DAGExecutor(log, max_parallel=2)

        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_ok, depends_on=[a])
        c = TaskNode(name="c", callable=_ok, depends_on=[a])
        d = TaskNode(name="d", callable=_ok, depends_on=[b, c])
        dag = DAGWorkflow(name="diamond", tasks=[a, b, c, d])

        run_id = executor.run(dag)
        assert all(t.state == TaskState.SUCCEEDED for t in dag.tasks)

    def test_parallel_execution(self) -> None:
        """Verify tasks actually run in parallel when possible."""
        log = SQLiteEventLog()
        executor = DAGExecutor(log, max_parallel=3)
        timestamps: dict[str, float] = {}
        lock = threading.Lock()

        def timed_task(name: str) -> str:
            with lock:
                timestamps[f"{name}_start"] = time.monotonic()
            time.sleep(0.05)
            with lock:
                timestamps[f"{name}_end"] = time.monotonic()
            return name

        a = TaskNode(name="a", callable=lambda: timed_task("a"))
        b = TaskNode(name="b", callable=lambda: timed_task("b"), depends_on=[a])
        c = TaskNode(name="c", callable=lambda: timed_task("c"), depends_on=[a])
        d = TaskNode(name="d", callable=lambda: timed_task("d"), depends_on=[b, c])
        dag = DAGWorkflow(name="parallel", tasks=[a, b, c, d])

        executor.run(dag)

        # b and c should overlap (both start after a finishes)
        assert timestamps["b_start"] < timestamps["c_end"]
        assert timestamps["c_start"] < timestamps["b_end"]

    def test_failure_stops_new_tasks(self) -> None:
        log = SQLiteEventLog()
        executor = DAGExecutor(log)

        a = TaskNode(name="a", callable=_ok)
        b = TaskNode(name="b", callable=_fail, depends_on=[a])
        c = TaskNode(name="c", callable=_ok, depends_on=[b])
        dag = DAGWorkflow(name="fail", tasks=[a, b, c])

        with pytest.raises(TaskExecutionError, match="b"):
            executor.run(dag)

        assert a.state == TaskState.SUCCEEDED
        assert b.state == TaskState.FAILED
        assert c.state == TaskState.PENDING

    def test_failure_emits_run_finished(self) -> None:
        log = SQLiteEventLog()
        executor = DAGExecutor(log)
        from agentos.core.identifiers import generate_run_id

        rid = generate_run_id()
        a = TaskNode(name="a", callable=_fail)
        dag = DAGWorkflow(name="fail-events", tasks=[a])

        with pytest.raises(TaskExecutionError):
            executor.run(dag, run_id=rid)

        events = log.query_by_run(rid)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert len(run_finished) == 1
        assert run_finished[0].payload["outcome"] == "FAILED"

    def test_empty_dag(self) -> None:
        log = SQLiteEventLog()
        executor = DAGExecutor(log)
        dag = DAGWorkflow(name="empty")

        run_id = executor.run(dag)
        events = log.query_by_run(run_id)
        assert len(events) == 2
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[1].event_type == EventType.RUN_FINISHED
