"""Tests for consultation tasks in DAGExecutor."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, WorkflowResult
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
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


def _output(task_id: str, summary: str = "done") -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id="test-agent",
        status=TaskStatus.SUCCEEDED,
        summary=summary,
    )


class TestConsultationExecution:
    def test_consultation_task_runs(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Consultation tasks execute via the task executor."""
        executed: list[str] = []

        def executor(name, config, preds=None):
            executed.append(name)
            return TaskStatus.SUCCEEDED, _output(name, "Answered the question")

        wf = _make_workflow({
            "research": TaskConfig(name="research"),
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                depends_on=["research"],
                consult_agent="researcher",
                consult_question="What data sources did you use?",
            ),
            "analysis": TaskConfig(name="analysis", depends_on=["clarify"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "succeeded"
        assert "clarify" in executed
        assert "analysis" in result.completed_tasks

    def test_consultation_receives_predecessor_context(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Consultation tasks receive predecessor outputs as context."""
        received_preds: list[list[TaskOutput]] = []

        def executor(name, config, preds=None):
            if name == "clarify":
                received_preds.append(preds or [])
            if name == "research":
                return TaskStatus.SUCCEEDED, _output(name, "Research findings here")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "research": TaskConfig(name="research"),
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                depends_on=["research"],
                consult_agent="researcher",
                consult_question="Clarify your findings",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        assert len(received_preds) == 1
        assert len(received_preds[0]) == 1
        assert received_preds[0][0].summary == "Research findings here"


class TestConsultationEvents:
    def test_message_sent_event(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """MESSAGE_SENT event is emitted before consultation runs."""
        def executor(name, config, preds=None):
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                consult_agent="expert",
                consult_question="What is the best approach?",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        events = event_log.query(
            workflow_id="test-wf", event_type=EventType.MESSAGE_SENT
        )
        assert len(events) == 1
        assert events[0].payload["task_id"] == "clarify"
        assert events[0].payload["consult_agent"] == "expert"
        assert events[0].payload["question"] == "What is the best approach?"

    def test_message_received_event(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """MESSAGE_RECEIVED event is emitted after consultation completes."""
        def executor(name, config, preds=None):
            return TaskStatus.SUCCEEDED, _output(name, "Here is my answer")

        wf = _make_workflow({
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                consult_agent="expert",
                consult_question="What is the cost?",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        events = event_log.query(
            workflow_id="test-wf", event_type=EventType.MESSAGE_RECEIVED
        )
        assert len(events) == 1
        assert events[0].payload["task_id"] == "clarify"
        assert events[0].payload["has_response"] is True

    def test_message_events_ordered(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """MESSAGE_SENT comes before MESSAGE_RECEIVED in sequence."""
        def executor(name, config, preds=None):
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "q": TaskConfig(
                name="q",
                type="consultation",
                consult_agent="agent",
                consult_question="Question?",
            ),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        sent = event_log.query(workflow_id="test-wf", event_type=EventType.MESSAGE_SENT)
        recv = event_log.query(workflow_id="test-wf", event_type=EventType.MESSAGE_RECEIVED)
        assert len(sent) == 1
        assert len(recv) == 1
        assert sent[0].seq < recv[0].seq


class TestConsultationFailure:
    def test_consultation_failure_propagates(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """If consultation task fails, dependents are skipped."""
        def executor(name, config, preds=None):
            if name == "clarify":
                return TaskStatus.FAILED, _output(name, "Could not answer")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                consult_agent="expert",
                consult_question="Complex question",
            ),
            "next": TaskConfig(name="next", depends_on=["clarify"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        result = ex.run("test-wf")

        assert result.status == "failed"
        assert "next" in result.skipped_tasks


class TestConsultationOutputFlows:
    def test_consultation_output_available_to_dependents(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Output from consultation task flows to dependent tasks."""
        received_preds: list[list[TaskOutput]] = []

        def executor(name, config, preds=None):
            if name == "analysis":
                received_preds.append(preds or [])
            if name == "clarify":
                return TaskStatus.SUCCEEDED, _output(name, "Data from 3 sources")
            return TaskStatus.SUCCEEDED, _output(name)

        wf = _make_workflow({
            "clarify": TaskConfig(
                name="clarify",
                type="consultation",
                consult_agent="expert",
                consult_question="What sources?",
            ),
            "analysis": TaskConfig(name="analysis", depends_on=["clarify"]),
        })
        ex = _make_executor(wf, event_log, seq, executor)
        ex.run("test-wf")

        assert len(received_preds) == 1
        assert any("3 sources" in p.summary for p in received_preds[0])


class TestConsultationVerification:
    def test_consultation_without_agent_fails_verification(self) -> None:
        from agentos.validation.workflow_verifier import WorkflowVerifier

        wf = WorkflowDefinition(
            name="test",
            tasks={
                "q": TaskConfig(
                    name="q",
                    type="consultation",
                    consult_question="Question?",
                ),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert not report.valid
        assert any(e.code == "consultation_no_agent" for e in report.errors)

    def test_consultation_without_question_fails_verification(self) -> None:
        from agentos.schemas.agent import AgentConfig
        from agentos.validation.workflow_verifier import WorkflowVerifier

        wf = WorkflowDefinition(
            name="test",
            agents={"expert": AgentConfig(adapter="tier1", model="test")},
            tasks={
                "q": TaskConfig(
                    name="q",
                    type="consultation",
                    consult_agent="expert",
                ),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert not report.valid
        assert any(e.code == "consultation_no_question" for e in report.errors)

    def test_consultation_with_undefined_agent_fails(self) -> None:
        from agentos.validation.workflow_verifier import WorkflowVerifier

        wf = WorkflowDefinition(
            name="test",
            tasks={
                "q": TaskConfig(
                    name="q",
                    type="consultation",
                    consult_agent="nonexistent",
                    consult_question="Question?",
                ),
            },
        )
        report = WorkflowVerifier().verify(wf)
        assert not report.valid
        assert any(e.code == "consultation_undefined_agent" for e in report.errors)
