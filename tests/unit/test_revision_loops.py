"""Tests for revision loops in DAGExecutor."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import (
    RetryPolicy,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
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
        task_executor=task_executor or (lambda *a: TaskStatus.SUCCEEDED),
    )


def _output(
    task_id: str,
    summary: str = "done",
    status: TaskStatus = TaskStatus.SUCCEEDED,
    **kwargs,
) -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id="test-agent",
        status=status,
        summary=summary,
        **kwargs,
    )


class TestGateRejectionRetry:
    def test_gate_rejection_retries_predecessor(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """When gate rejects and predecessor has retry_policy, predecessor is retried."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name, f"Iteration {call_counts[name]}")
            if name == "review":
                # Reject first time, approve second time
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Needs more tests", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name, "Approved")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(
                name="implement",
                retry_policy=RetryPolicy(max_retries=3, on="gate_rejected"),
            ),
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review code",
            ),
            "ship": TaskConfig(name="ship", depends_on=["review"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert call_counts["implement"] == 2  # ran twice
        assert call_counts["review"] == 2     # ran twice
        assert "ship" in result.completed_tasks

    def test_max_retries_exceeded(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """When max_retries is exceeded, workflow fails."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name, f"Attempt {call_counts[name]}")
            if name == "review":
                # Always reject
                return TaskStatus.FAILED, _output(name, "Still bad", status=TaskStatus.FAILED)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(
                name="implement",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review code",
            ),
            "ship": TaskConfig(name="ship", depends_on=["review"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "failed"
        # implement runs 3 times total (1 original + 2 retries)
        assert call_counts["implement"] == 3
        # review runs 3 times total
        assert call_counts["review"] == 3
        assert "ship" in result.skipped_tasks


class TestRetryEvents:
    def test_retry_events_emitted(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """TASK_RETRIED and REVISION_FEEDBACK events are emitted on retry."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "review":
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Add error handling", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name, "Good")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(
                name="implement",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        retry_events = event_log.query(
            workflow_id="test-wf", event_type=EventType.TASK_RETRIED
        )
        assert len(retry_events) == 1
        assert retry_events[0].payload["task_id"] == "implement"
        assert retry_events[0].payload["iteration"] == 2

        feedback_events = event_log.query(
            workflow_id="test-wf", event_type=EventType.REVISION_FEEDBACK
        )
        assert len(feedback_events) == 1
        assert "error handling" in feedback_events[0].payload["feedback"].lower()


class TestNoRetryWithoutPolicy:
    def test_gate_rejection_without_policy_fails(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Gate rejection without retry_policy on predecessor just fails."""
        def executor(name, config, preds=None):
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "review":
                return TaskStatus.FAILED, _output(name, "Rejected", status=TaskStatus.FAILED)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(name="implement"),  # no retry_policy
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review",
            ),
            "ship": TaskConfig(name="ship", depends_on=["review"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "failed"
        assert "review" in result.failed_tasks
        assert "ship" in result.skipped_tasks


class TestRetryPolicyValidation:
    def test_retry_policy_max_retries_1(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """max_retries=1 allows exactly 1 retry (2 total executions)."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "task":
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "gate":
                # Always reject
                return TaskStatus.FAILED, _output(name, "Bad", status=TaskStatus.FAILED)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "task": TaskConfig(
                name="task",
                retry_policy=RetryPolicy(max_retries=1, on="gate_rejected"),
            ),
            "gate": TaskConfig(
                name="gate",
                type="approval_gate",
                depends_on=["task"],
                prompt="Check",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "failed"
        assert call_counts["task"] == 2  # 1 original + 1 retry
        assert call_counts["gate"] == 2

    def test_retry_policy_wrong_trigger(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """retry_policy with wrong trigger doesn't retry on gate rejection."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "task":
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "gate":
                return TaskStatus.FAILED, _output(name, "No", status=TaskStatus.FAILED)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "task": TaskConfig(
                name="task",
                retry_policy=RetryPolicy(max_retries=3, on="validation_failed"),
            ),
            "gate": TaskConfig(
                name="gate",
                type="approval_gate",
                depends_on=["task"],
                prompt="Check",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "failed"
        assert call_counts["task"] == 1  # not retried


class TestValidationFailedRetry:
    def test_validation_failed_retries_task(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Tasks with retry_policy on=validation_failed retry on failure."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "task":
                # Fail first time, succeed second time
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Error", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name, "Fixed")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "task": TaskConfig(
                name="task",
                retry_policy=RetryPolicy(max_retries=2, on="validation_failed"),
            ),
            "next": TaskConfig(name="next", depends_on=["task"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert call_counts["task"] == 2
        assert "next" in result.completed_tasks


class TestRetryWithMultiplePredecessors:
    def test_only_retryable_predecessor_is_retried(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Gate with 2 predecessors: only one with retry_policy gets retried."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name in ("a", "b"):
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "gate":
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Fix A", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "a": TaskConfig(
                name="a",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "b": TaskConfig(name="b"),  # no retry policy
            "gate": TaskConfig(
                name="gate",
                type="approval_gate",
                depends_on=["a", "b"],
                prompt="Review",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert call_counts["a"] == 2  # retried
        assert call_counts["b"] == 1  # NOT retried


class TestRetryPolicyModel:
    def test_default_values(self):
        policy = RetryPolicy()
        assert policy.max_retries == 2
        assert policy.on == "gate_rejected"

    def test_custom_values(self):
        policy = RetryPolicy(max_retries=5, on="validation_failed")
        assert policy.max_retries == 5
        assert policy.on == "validation_failed"

    def test_max_retries_capped_at_10(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RetryPolicy(max_retries=11)

    def test_max_retries_min_1(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RetryPolicy(max_retries=0)
