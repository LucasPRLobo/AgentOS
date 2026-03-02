"""Tests for linear workflow — execution, state transitions, failure handling, event emission."""

import pytest

from agentos.core.errors import TaskExecutionError
from agentos.core.identifiers import generate_run_id
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.task import TaskNode, TaskState
from agentos.runtime.workflow import Workflow, WorkflowExecutor
from agentos.schemas.events import EventType


def _succeeding_task() -> str:
    return "ok"


def _failing_task() -> None:
    raise ValueError("boom")


def _counter_factory() -> tuple[list[int], callable]:
    calls: list[int] = []

    def task() -> int:
        val = len(calls)
        calls.append(val)
        return val

    return calls, task


class TestWorkflow:
    def test_add_task(self) -> None:
        wf = Workflow(name="test")
        wf.add_task(TaskNode(name="t1", callable=_succeeding_task))
        assert len(wf.tasks) == 1

    def test_initial_state(self) -> None:
        wf = Workflow(name="test", tasks=[TaskNode(name="t1", callable=_succeeding_task)])
        assert wf.tasks[0].state == TaskState.PENDING


class TestWorkflowExecutor:
    def test_linear_execution(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)

        calls, task_fn = _counter_factory()
        wf = Workflow(name="linear", tasks=[
            TaskNode(name="step1", callable=task_fn),
            TaskNode(name="step2", callable=task_fn),
            TaskNode(name="step3", callable=task_fn),
        ])

        run_id = executor.run(wf)

        # All tasks succeeded
        assert all(t.state == TaskState.SUCCEEDED for t in wf.tasks)
        assert [t.result for t in wf.tasks] == [0, 1, 2]
        assert len(calls) == 3

        # Events were emitted
        events = log.query_by_run(run_id)
        assert len(events) > 0

        # First event is RunStarted, last is RunFinished
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[-1].event_type == EventType.RUN_FINISHED

    def test_event_sequence(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)

        wf = Workflow(name="seq", tasks=[
            TaskNode(name="only", callable=_succeeding_task),
        ])

        run_id = executor.run(wf)
        events = log.query_by_run(run_id)

        expected_types = [
            EventType.RUN_STARTED,
            EventType.TASK_STARTED,
            EventType.TASK_FINISHED,
            EventType.RUN_FINISHED,
        ]
        assert [e.event_type for e in events] == expected_types

    def test_failure_stops_execution(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)

        wf = Workflow(name="fail", tasks=[
            TaskNode(name="ok", callable=_succeeding_task),
            TaskNode(name="bad", callable=_failing_task),
            TaskNode(name="never", callable=_succeeding_task),
        ])

        with pytest.raises(TaskExecutionError, match="bad"):
            executor.run(wf)

        assert wf.tasks[0].state == TaskState.SUCCEEDED
        assert wf.tasks[1].state == TaskState.FAILED
        assert wf.tasks[2].state == TaskState.PENDING  # never reached

    def test_failure_emits_events(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)
        run_id = generate_run_id()

        wf = Workflow(name="fail-events", tasks=[
            TaskNode(name="bad", callable=_failing_task),
        ])

        with pytest.raises(TaskExecutionError):
            executor.run(wf, run_id=run_id)

        events = log.query_by_run(run_id)
        types = [e.event_type for e in events]

        assert EventType.RUN_STARTED in types
        assert EventType.TASK_STARTED in types
        assert EventType.TASK_FINISHED in types
        assert EventType.RUN_FINISHED in types

        # RunFinished should indicate failure
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED][0]
        assert run_finished.payload["outcome"] == "FAILED"

    def test_custom_run_id(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)
        custom_id = generate_run_id()

        wf = Workflow(name="custom", tasks=[
            TaskNode(name="t", callable=_succeeding_task),
        ])

        returned_id = executor.run(wf, run_id=custom_id)
        assert returned_id == custom_id

    def test_empty_workflow(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)
        wf = Workflow(name="empty")

        run_id = executor.run(wf)
        events = log.query_by_run(run_id)

        assert len(events) == 2
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[1].event_type == EventType.RUN_FINISHED
        assert events[1].payload["outcome"] == "SUCCEEDED"

    def test_task_results_stored(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)

        wf = Workflow(name="results", tasks=[
            TaskNode(name="t", callable=lambda: {"key": "value"}),
        ])

        executor.run(wf)
        assert wf.tasks[0].result == {"key": "value"}

    def test_task_error_stored(self) -> None:
        log = SQLiteEventLog()
        executor = WorkflowExecutor(log)

        wf = Workflow(name="err", tasks=[
            TaskNode(name="t", callable=_failing_task),
        ])

        with pytest.raises(TaskExecutionError):
            executor.run(wf)

        assert wf.tasks[0].error is not None
        assert isinstance(wf.tasks[0].error, ValueError)
