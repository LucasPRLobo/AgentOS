"""Integration tests for V1.5 collaborative workflows.

Tests that combine branching, revision loops, and consultation
to verify they work together end-to-end.
"""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.replayer import WorkflowReplayer
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import (
    EdgeCondition,
    RetryPolicy,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.workflow_verifier import WorkflowVerifier


def _make_workflow(
    tasks: dict[str, TaskConfig],
    budget: BudgetSpec | None = None,
) -> WorkflowDefinition:
    return WorkflowDefinition(
        name="integration-test",
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
        workflow_id="int-test",
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
) -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id="test-agent",
        status=status,
        summary=summary,
    )


@pytest.mark.integration
class TestBranchingWithRevision:
    """Combines conditional branching with revision loops."""

    def test_branch_then_revise(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Implement → test (branch) → review (revise) → deploy."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name, f"Implementation v{call_counts[name]}")
            if name == "test":
                return TaskStatus.SUCCEEDED, _output(name, "All tests passed")
            if name == "review":
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Add logging", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name, "Approved")
            if name == "fix":
                return TaskStatus.SUCCEEDED, _output(name)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(
                name="implement",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "test": TaskConfig(
                name="test",
                depends_on=["implement"],
                conditions=[
                    EdgeCondition(target="deploy", expression="'passed' in summary.lower()"),
                    EdgeCondition(target="fix", expression="'fail' in summary.lower()"),
                ],
            ),
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review",
            ),
            "deploy": TaskConfig(name="deploy", depends_on=["test", "review"]),
            "fix": TaskConfig(name="fix", depends_on=["test"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("int-test")

        assert result.status == "succeeded"
        assert "deploy" in result.completed_tasks
        assert "fix" in result.skipped_tasks  # tests passed, fix branch skipped
        assert call_counts["implement"] == 2  # retried after review rejection
        assert call_counts["review"] == 2


@pytest.mark.integration
class TestConsultationWithBranching:
    """Combines consultation with conditional branching."""

    def test_consult_then_branch(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Research → consult → branch based on consultation output."""
        def executor(name, config, preds=None):
            if name == "research":
                return TaskStatus.SUCCEEDED, _output(name, "Initial findings")
            if name == "consult":
                return TaskStatus.SUCCEEDED, _output(name, "Confirmed: market is growing")
            if name in ("deep_dive", "pivot"):
                return TaskStatus.SUCCEEDED, _output(name)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "research": TaskConfig(name="research"),
            "consult": TaskConfig(
                name="consult",
                type="consultation",
                depends_on=["research"],
                consult_agent="expert",
                consult_question="Is the market growing?",
                conditions=[
                    EdgeCondition(target="deep_dive", expression="'growing' in summary"),
                    EdgeCondition(target="pivot", expression="'declining' in summary"),
                ],
            ),
            "deep_dive": TaskConfig(name="deep_dive", depends_on=["consult"]),
            "pivot": TaskConfig(name="pivot", depends_on=["consult"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("int-test")

        assert result.status == "succeeded"
        assert "deep_dive" in result.completed_tasks
        assert "pivot" in result.skipped_tasks


@pytest.mark.integration
class TestFullCollaborativeWorkflow:
    """All three features combined."""

    def test_implement_test_review_consult_deploy(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Full workflow: implement → test → review (retry) → consult → deploy."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "implement":
                return TaskStatus.SUCCEEDED, _output(name, f"Code v{call_counts[name]}")
            if name == "test":
                return TaskStatus.SUCCEEDED, _output(name, "Tests passed")
            if name == "review":
                if call_counts.get("review", 0) <= 1:
                    return TaskStatus.FAILED, _output(name, "Fix the edge cases", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name, "Approved")
            if name == "clarify":
                return TaskStatus.SUCCEEDED, _output(name, "Edge cases resolved")
            if name == "deploy":
                return TaskStatus.SUCCEEDED, _output(name, "Deployed")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "implement": TaskConfig(
                name="implement",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "test": TaskConfig(name="test", depends_on=["implement"]),
            "review": TaskConfig(
                name="review",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review code",
            ),
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                depends_on=["test"],
                consult_agent="tester",
                consult_question="What edge cases need attention?",
            ),
            "deploy": TaskConfig(
                name="deploy",
                depends_on=["review", "clarify"],
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("int-test")

        assert result.status == "succeeded"
        assert call_counts["implement"] == 2
        assert "deploy" in result.completed_tasks


@pytest.mark.integration
class TestReplayWithV15Events:
    """Verify that the replayer handles V1.5 events correctly."""

    def test_replay_branching_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Replayer correctly reconstructs state from branching events."""
        def executor(name, config, preds=None):
            if name == "root":
                return TaskStatus.SUCCEEDED, _output(name, "take path A")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "root": TaskConfig(
                name="root",
                conditions=[
                    EdgeCondition(target="a", expression="'path A' in summary"),
                    EdgeCondition(target="b", expression="'path B' in summary"),
                ],
            ),
            "a": TaskConfig(name="a", depends_on=["root"]),
            "b": TaskConfig(name="b", depends_on=["root"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("int-test")

        replayer = WorkflowReplayer(event_log)
        snapshot = replayer.replay("int-test")

        assert snapshot.status == "succeeded"
        assert "root" in snapshot.succeeded_tasks
        assert "a" in snapshot.succeeded_tasks
        assert "b" in snapshot.skipped_tasks

    def test_replay_revision_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Replayer correctly reconstructs state from retry events."""
        call_counts: dict[str, int] = {}

        def executor(name, config, preds=None):
            call_counts[name] = call_counts.get(name, 0) + 1
            if name == "task":
                return TaskStatus.SUCCEEDED, _output(name)
            if name == "gate":
                if call_counts[name] <= 1:
                    return TaskStatus.FAILED, _output(name, "Fix it", status=TaskStatus.FAILED)
                return TaskStatus.SUCCEEDED, _output(name)
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "task": TaskConfig(
                name="task",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "gate": TaskConfig(
                name="gate",
                type="approval_gate",
                depends_on=["task"],
                prompt="Check",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("int-test")

        replayer = WorkflowReplayer(event_log)
        snapshot = replayer.replay("int-test")

        assert snapshot.status == "succeeded"
        # Both task and gate end up succeeded after retry
        assert "task" in snapshot.succeeded_tasks
        assert "gate" in snapshot.succeeded_tasks

    def test_replay_consultation_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Replayer correctly handles MESSAGE_SENT/RECEIVED events."""
        def executor(name, config, preds=None):
            return TaskStatus.SUCCEEDED, _output(name, "Answered")

        wf = _make_workflow({
            "q": TaskConfig(
                name="q",
                type="consultation",
                consult_agent="agent",
                consult_question="Question?",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("int-test")

        replayer = WorkflowReplayer(event_log)
        snapshot = replayer.replay("int-test")

        assert snapshot.status == "succeeded"
        # Verify MESSAGE events are in the event list
        event_types = {e.event_type for e in snapshot.events}
        assert EventType.MESSAGE_SENT in event_types
        assert EventType.MESSAGE_RECEIVED in event_types


@pytest.mark.integration
class TestVerifierWithV15Features:
    """Verify that the workflow verifier validates V1.5 features."""

    def test_valid_branching_workflow(self) -> None:
        from agentos.schemas.agent import AgentConfig

        wf = WorkflowDefinition(
            name="test",
            agents={"dev": AgentConfig(adapter="tier1", model="test")},
            tasks={
                "root": TaskConfig(
                    name="root",
                    agent="dev",
                    conditions=[
                        EdgeCondition(target="a", expression="True"),
                    ],
                ),
                "a": TaskConfig(name="a", agent="dev", depends_on=["root"]),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert report.valid

    def test_condition_target_missing(self) -> None:
        from agentos.schemas.agent import AgentConfig

        wf = WorkflowDefinition(
            name="test",
            agents={"dev": AgentConfig(adapter="tier1", model="test")},
            tasks={
                "root": TaskConfig(
                    name="root",
                    agent="dev",
                    conditions=[
                        EdgeCondition(target="nonexistent", expression="True"),
                    ],
                ),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert not report.valid
        assert any(e.code == "condition_target_missing" for e in report.errors)

    def test_valid_combined_workflow(self) -> None:
        from agentos.schemas.agent import AgentConfig

        wf = WorkflowDefinition(
            name="combined",
            agents={
                "dev": AgentConfig(adapter="tier1", model="test"),
                "tester": AgentConfig(adapter="tier1", model="test"),
            },
            tasks={
                "implement": TaskConfig(
                    name="implement",
                    agent="dev",
                    retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
                ),
                "test": TaskConfig(
                    name="test",
                    agent="tester",
                    depends_on=["implement"],
                    conditions=[
                        EdgeCondition(target="deploy", expression="'pass' in summary"),
                    ],
                ),
                "review": TaskConfig(
                    name="review",
                    type="approval_gate",
                    depends_on=["implement"],
                    prompt="Review",
                ),
                "consult": TaskConfig(
                    name="consult",
                    type="consultation",
                    depends_on=["test"],
                    consult_agent="dev",
                    consult_question="Clarify approach?",
                ),
                "deploy": TaskConfig(
                    name="deploy",
                    agent="dev",
                    depends_on=["test", "review"],
                ),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert report.valid


@pytest.mark.integration
class TestBackwardCompatibility:
    """Ensure V1 workflows work unchanged with V1.5 code."""

    def test_v1_linear_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Simple A→B→C workflow still works."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "a": TaskConfig(name="a"),
            "b": TaskConfig(name="b", depends_on=["a"]),
            "c": TaskConfig(name="c", depends_on=["b"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("int-test")

        assert result.status == "succeeded"
        assert executed == ["a", "b", "c"]

    def test_v1_gate_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Gate workflow without retry_policy still fails on rejection."""
        def executor(name, config, preds=None):
            if name == "gate":
                return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        wf = _make_workflow({
            "task": TaskConfig(name="task"),
            "gate": TaskConfig(
                name="gate",
                type="approval_gate",
                depends_on=["task"],
                prompt="Approve?",
            ),
            "after": TaskConfig(name="after", depends_on=["gate"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("int-test")

        assert result.status == "failed"
        assert "gate" in result.failed_tasks
        assert "after" in result.skipped_tasks
