"""Integration tests — adversarial validation + lifecycle in workflows."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.lifecycle import (
    AgentLifecycleManager,
    AgentState,
    LifecycleError,
    LifecyclePolicy,
    RestartReason,
    TerminationReason,
)
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.events import EventType
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.adversarial import (
    AdversarialValidator,
    AdversarialValidatorConfig,
    FailureAction,
    ValidationResult,
)


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
# Tests: Adversarial validation in DAG workflow
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestAdversarialInWorkflow:

    def test_validation_pass_continues_workflow(self, event_log, seq):
        """Task output passes validation → workflow succeeds."""
        wf = WorkflowDefinition(
            name="val-pass",
            tasks={
                "produce": TaskConfig(name="produce", agent="ag1"),
                "consume": TaskConfig(
                    name="consume", agent="ag1", depends_on=["produce"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="v1",
        )
        config = AdversarialValidatorConfig(
            validator_agent="validator-1",
            target_task="produce",
        )
        validator = AdversarialValidator(config)

        def executor(name, task_config, predecessors=None):
            if name == "produce":
                output = TaskOutput(
                    task_id=name, agent_id="ag1",
                    status=TaskStatus.SUCCEEDED,
                    summary="Analysis complete.",
                    key_findings=[Finding(
                        finding="Revenue up 15%",
                        confidence=Confidence.HIGH,
                    )],
                )
                # Validate in-line
                report = validator.validate(output)
                if report.result == ValidationResult.FAILED:
                    return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("v1")
        assert result.status == "succeeded"

    def test_validation_fail_stops_workflow(self, event_log, seq):
        """Task output fails validation → task fails → workflow fails."""
        wf = WorkflowDefinition(
            name="val-fail",
            tasks={
                "produce": TaskConfig(name="produce", agent="ag1"),
                "consume": TaskConfig(
                    name="consume", agent="ag1", depends_on=["produce"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="v2",
        )
        config = AdversarialValidatorConfig(
            validator_agent="validator-1",
            target_task="produce",
            min_confidence=0.99,
        )
        validator = AdversarialValidator(config)

        def executor(name, task_config, predecessors=None):
            if name == "produce":
                # Bad output: empty summary
                output = TaskOutput(
                    task_id=name, agent_id="ag1",
                    status=TaskStatus.SUCCEEDED,
                    summary="",
                    key_findings=[],
                )
                report = validator.validate(output)
                if report.result == ValidationResult.FAILED:
                    return TaskStatus.FAILED
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("v2")
        assert result.status == "failed"

    def test_validation_with_retry(self, event_log, seq):
        """Custom validator retries once then passes."""
        call_count = {"n": 0}

        def retry_validator(output, config):
            from agentos.validation.adversarial import ValidationReport
            call_count["n"] += 1
            if call_count["n"] == 1:
                return ValidationReport(
                    task_id=output.task_id,
                    validator_id=config.validator_agent,
                    result=ValidationResult.FAILED,
                    confidence=0.3,
                    summary="First attempt: insufficient detail",
                )
            return ValidationReport(
                task_id=output.task_id,
                validator_id=config.validator_agent,
                result=ValidationResult.PASSED,
                confidence=0.95,
                summary="Retry passed",
            )

        config = AdversarialValidatorConfig(
            validator_agent="v1",
            target_task="produce",
            on_failure=FailureAction.RETRY,
            max_retries=2,
        )
        validator = AdversarialValidator(config, validate_fn=retry_validator)

        output = TaskOutput(
            task_id="produce", agent_id="ag1",
            status=TaskStatus.SUCCEEDED,
            summary="Analysis", key_findings=[],
        )

        # First validation fails
        report1 = validator.validate(output)
        assert report1.result == ValidationResult.FAILED

        # Retry succeeds
        report2 = validator.validate(output)
        assert report2.result == ValidationResult.PASSED
        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Tests: Lifecycle in DAG workflow
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLifecycleInWorkflow:

    def test_spawn_and_stop_during_dag(self, event_log, seq):
        """Lifecycle events emitted alongside DAG execution events."""
        wf = WorkflowDefinition(
            name="lc-dag",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="lc1",
        )
        lm = AgentLifecycleManager(event_log, seq, "lc1")

        def executor(name, task_config, predecessors=None):
            lm.spawn("ag1", agent_name="researcher", adapter_tier=1)
            lm.record_turn("ag1", tokens=200)
            lm.stop("ag1", reason=TerminationReason.COMPLETED)
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("lc1")
        assert result.status == "succeeded"

        spawned = event_log.query(workflow_id="lc1", event_type=EventType.AGENT_SPAWNED)
        terminated = event_log.query(workflow_id="lc1", event_type=EventType.AGENT_TERMINATED)
        assert len(spawned) == 1
        assert len(terminated) == 1

    def test_restart_during_dag(self, event_log, seq):
        """Agent restarts mid-task, continues with fresh context."""
        wf = WorkflowDefinition(
            name="lc-restart",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="lc2",
        )
        policy = LifecyclePolicy(max_tokens=500, max_restarts=2)
        lm = AgentLifecycleManager(event_log, seq, "lc2")

        def executor(name, task_config, predecessors=None):
            lm.spawn("ag1", agent_name="worker", policy=policy)
            lm.record_turn("ag1", tokens=300, summary="Phase 1")

            # Simulate token-triggered restart
            trigger = lm.record_turn("ag1", tokens=250)
            assert trigger == RestartReason.TOKEN_THRESHOLD

            new_record, briefing = lm.restart(
                "ag1", RestartReason.TOKEN_THRESHOLD,
                instructions="Continue from phase 2",
            )
            assert new_record.restart_count == 1
            assert briefing.prior_summary == "Phase 1"

            lm.record_turn("ag1", tokens=100, summary="Phase 2 done")
            lm.stop("ag1")
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("lc2")
        assert result.status == "succeeded"

        spawned = event_log.query(workflow_id="lc2", event_type=EventType.AGENT_SPAWNED)
        terminated = event_log.query(workflow_id="lc2", event_type=EventType.AGENT_TERMINATED)
        # 1 initial + 1 restart = 2 spawned
        assert len(spawned) == 2
        # 1 policy stop + 1 final stop = 2 terminated
        assert len(terminated) == 2

    def test_max_restarts_fails_task(self, event_log, seq):
        """Exceeding max_restarts causes LifecycleError → task fails."""
        wf = WorkflowDefinition(
            name="lc-maxr",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="lc3",
        )
        policy = LifecyclePolicy(max_restarts=0)
        lm = AgentLifecycleManager(event_log, seq, "lc3")

        def executor(name, task_config, predecessors=None):
            lm.spawn("ag1", policy=policy)
            lm.restart("ag1")  # Should raise
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("lc3")
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# Tests: Lifecycle + Budget combined
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLifecycleBudgetCombined:

    def test_budget_and_lifecycle_coexist(self, event_log, seq):
        """Both budget tracking and lifecycle management emit events."""
        wf = WorkflowDefinition(
            name="lc-budget",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="lb1",
        )
        lm = AgentLifecycleManager(event_log, seq, "lb1")

        def executor(name, task_config, predecessors=None):
            lm.spawn("ag1")
            budget_mgr.apply("ag1", BudgetDelta(tokens=100, api_calls=1))
            lm.record_turn("ag1", tokens=100)
            lm.stop("ag1")
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("lb1")
        assert result.status == "succeeded"

        all_events = event_log.replay("lb1")
        event_types = {e.event_type for e in all_events}
        assert EventType.AGENT_SPAWNED in event_types
        assert EventType.AGENT_TERMINATED in event_types
        assert EventType.BUDGET_CONSUMED in event_types
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.WORKFLOW_COMPLETED in event_types


# ---------------------------------------------------------------------------
# Tests: Model separation in multi-agent workflow
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestModelSeparationInWorkflow:

    def test_same_model_warning(self):
        """Workflow with same model for producer and validator gets warning."""
        warning = AdversarialValidator.check_model_separation(
            "claude-sonnet-4-6", "claude-sonnet-4-6",
        )
        assert warning is not None

    def test_different_model_no_warning(self):
        warning = AdversarialValidator.check_model_separation(
            "claude-sonnet-4-6", "gpt-4o-mini",
        )
        assert warning is None
