"""Tests for conditional branching in DAGExecutor."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import (
    Confidence,
    EdgeCondition,
    Finding,
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


def _output(task_id: str, summary: str = "done", **kwargs) -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id="test-agent",
        status=TaskStatus.SUCCEEDED,
        summary=summary,
        **kwargs,
    )


class TestConditionalBranchTrue:
    def test_condition_true_activates_target(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """When condition is True, the target task runs."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            if name == "run_tests":
                return TaskStatus.SUCCEEDED, _output(name, "All tests passed")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "run_tests": TaskConfig(
                name="run_tests",
                conditions=[
                    EdgeCondition(target="deploy", expression="'passed' in summary.lower()"),
                ],
            ),
            "deploy": TaskConfig(name="deploy", depends_on=["run_tests"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert "deploy" in executed
        assert "deploy" in result.completed_tasks

    def test_condition_false_skips_target(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """When condition is False, the target task is SKIPPED."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            if name == "run_tests":
                return TaskStatus.SUCCEEDED, _output(name, "Some tests failed badly")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "run_tests": TaskConfig(
                name="run_tests",
                conditions=[
                    EdgeCondition(target="deploy", expression="'passed' in summary.lower()"),
                ],
            ),
            "deploy": TaskConfig(name="deploy", depends_on=["run_tests"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "deploy" not in executed
        assert "deploy" in result.skipped_tasks


class TestConditionalBranchMultiple:
    def test_multiple_conditions_select_correct_branch(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Multiple conditions: one true, one false → correct path taken."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            if name == "run_tests":
                return TaskStatus.SUCCEEDED, _output(name, "Tests failed with errors")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "run_tests": TaskConfig(
                name="run_tests",
                conditions=[
                    EdgeCondition(target="deploy", expression="'passed' in summary.lower()"),
                    EdgeCondition(target="fix_code", expression="'fail' in summary.lower()"),
                ],
            ),
            "deploy": TaskConfig(name="deploy", depends_on=["run_tests"]),
            "fix_code": TaskConfig(name="fix_code", depends_on=["run_tests"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "deploy" in result.skipped_tasks
        assert "fix_code" in result.completed_tasks or "fix_code" in executed

    def test_both_conditions_true(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Both conditions true → both targets run."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "all good")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="a", expression="True"),
                    EdgeCondition(target="b", expression="True"),
                ],
            ),
            "a": TaskConfig(name="a", depends_on=["root"]),
            "b": TaskConfig(name="b", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "a" in result.completed_tasks
        assert "b" in result.completed_tasks

    def test_both_conditions_false(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Both conditions false → both targets skipped."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "nothing")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="a", expression="False"),
                    EdgeCondition(target="b", expression="False"),
                ],
            ),
            "a": TaskConfig(name="a", depends_on=["root"]),
            "b": TaskConfig(name="b", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "a" in result.skipped_tasks
        assert "b" in result.skipped_tasks


class TestSkippedCascade:
    def test_skipped_task_cascades_to_dependents(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """SKIPPED propagates: if B is skipped, C (depends on B) is also skipped."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "nothing relevant")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="b", expression="False"),
                ],
            ),
            "b": TaskConfig(name="b", depends_on=["root"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "b" in result.skipped_tasks
        assert "c" in result.skipped_tasks

    def test_deep_skip_cascade(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Cascade propagates multiple levels: A -> B -> C -> D, B skipped."""
        def executor(name, config, preds=None):
            if name == "a":
                return TaskStatus.SUCCEEDED, _output(name, "skip path")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "a": TaskConfig(
                name="a",
                conditions=[EdgeCondition(target="b", expression="False")],
            ),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
            "d": TaskConfig(name="d", depends_on=["c"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "b" in result.skipped_tasks
        assert "c" in result.skipped_tasks
        assert "d" in result.skipped_tasks


class TestBranchEvents:
    def test_branch_evaluated_event_emitted(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """BRANCH_EVALUATED events are emitted for each condition."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "tests passed")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="a", expression="'passed' in summary"),
                ],
            ),
            "a": TaskConfig(name="a", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        events = event_log.query(
            workflow_id="test-wf", event_type=EventType.BRANCH_EVALUATED
        )
        assert len(events) == 1
        assert events[0].payload["task_id"] == "root"
        assert events[0].payload["target"] == "a"
        assert events[0].payload["result"] is True


class TestNoConditionsBackwardCompat:
    def test_no_conditions_works_as_before(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Tasks without conditions behave exactly as V1."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert executed == ["a", "b"]


class TestConditionWithFindings:
    def test_condition_on_findings(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Conditions can check key_findings content."""
        def executor(name, config, preds=None):
            if name == "analyze":
                return TaskStatus.SUCCEEDED, _output(
                    name,
                    summary="Analysis complete",
                    key_findings=[
                        Finding(finding="High risk detected", confidence=Confidence.HIGH),
                    ],
                )
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "analyze": TaskConfig(
                name="analyze",
                conditions=[
                    EdgeCondition(
                        target="escalate",
                        expression="any('risk' in f for f in findings)",
                    ),
                ],
            ),
            "escalate": TaskConfig(name="escalate", depends_on=["analyze"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "escalate" in result.completed_tasks


class TestConditionExpressionError:
    def test_invalid_expression_skips_target(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Invalid expression evaluates to False, target is skipped."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "ok")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="a", expression="invalid_syntax!!!"),
                ],
            ),
            "a": TaskConfig(name="a", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert "a" in result.skipped_tasks


class TestWorkflowStatusWithSkips:
    def test_workflow_succeeds_when_only_skips(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """A workflow with some skipped tasks but no failures is 'succeeded'."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "only one path")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="path_a", expression="True"),
                    EdgeCondition(target="path_b", expression="False"),
                ],
            ),
            "path_a": TaskConfig(name="path_a", depends_on=["root"]),
            "path_b": TaskConfig(name="path_b", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        # Skipped is not failed
        assert result.status == "succeeded"
        assert "path_a" in result.completed_tasks
        assert "path_b" in result.skipped_tasks
        assert result.failed_tasks == []
