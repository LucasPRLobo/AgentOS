"""Tests for the SafetyScoreCalculator."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import Event, EventType
from agentos.schemas.sandbox import SandboxLevel
from agentos.schemas.task import TaskConfig
from agentos.schemas.workflow import WorkflowDefinition
from agentos.security.safety_score import SafetyScoreCalculator


@pytest.fixture
def calculator(event_log) -> SafetyScoreCalculator:
    return SafetyScoreCalculator(event_log)


def _make_workflow(**kwargs) -> WorkflowDefinition:
    defaults = {"name": "test_wf", "tasks": {}}
    defaults.update(kwargs)
    return WorkflowDefinition(**defaults)


class TestScoreAllDimensions:
    def test_all_six_dimensions_present(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf)
        assert len(report.dimensions) == 6
        names = {d.name for d in report.dimensions}
        assert names == {
            "permissions_scope",
            "isolation_level",
            "budget_constraints",
            "human_oversight",
            "adversarial_coverage",
            "historical_reliability",
        }

    def test_overall_is_weighted_average(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf)
        total_weight = sum(d.weight for d in report.dimensions)
        expected = sum(d.score * d.weight for d in report.dimensions) / total_weight
        assert abs(report.overall_score - round(expected, 3)) < 0.001


class TestPermissionsScope:
    def test_deny_by_default_scores_higher(self, calculator):
        wf = _make_workflow()
        policies = {
            "a1": CapabilityPolicy(agent_id="a1", deny_by_default=True),
            "a2": CapabilityPolicy(agent_id="a2", deny_by_default=True),
        }
        report = calculator.calculate(wf, policies)
        perm = next(d for d in report.dimensions if d.name == "permissions_scope")
        assert perm.score > 0.5

    def test_no_policies_low_score(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf, {})
        perm = next(d for d in report.dimensions if d.name == "permissions_scope")
        assert perm.score == 0.2

    def test_many_grants_reduce_score(self, calculator):
        wf = _make_workflow()
        grants = [CapabilityGrant(type=f"tool:tool_{i}") for i in range(20)]
        policies = {
            "a1": CapabilityPolicy(agent_id="a1", grants=grants, deny_by_default=True),
        }
        report = calculator.calculate(wf, policies)
        perm = next(d for d in report.dimensions if d.name == "permissions_scope")
        assert perm.score < 1.0


class TestIsolationLevel:
    def test_container_scores_highest(self, calculator):
        wf = _make_workflow()
        policies = {"a1": CapabilityPolicy(agent_id="a1", sandbox=SandboxLevel.CONTAINER)}
        report = calculator.calculate(wf, policies)
        iso = next(d for d in report.dimensions if d.name == "isolation_level")
        assert iso.score == 1.0

    def test_namespace_scores_medium(self, calculator):
        wf = _make_workflow()
        policies = {"a1": CapabilityPolicy(agent_id="a1", sandbox=SandboxLevel.NAMESPACE)}
        report = calculator.calculate(wf, policies)
        iso = next(d for d in report.dimensions if d.name == "isolation_level")
        assert iso.score == 0.6

    def test_none_scores_lowest(self, calculator):
        wf = _make_workflow()
        policies = {"a1": CapabilityPolicy(agent_id="a1", sandbox=SandboxLevel.NONE)}
        report = calculator.calculate(wf, policies)
        iso = next(d for d in report.dimensions if d.name == "isolation_level")
        assert iso.score == 0.2


class TestBudgetConstraints:
    def test_all_three_dimensions(self, calculator):
        wf = _make_workflow(budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0, max_time_seconds=60.0))
        report = calculator.calculate(wf)
        budget = next(d for d in report.dimensions if d.name == "budget_constraints")
        assert budget.score == 1.0

    def test_no_budget_limits(self, calculator):
        wf = _make_workflow(budget=BudgetSpec())
        report = calculator.calculate(wf)
        budget = next(d for d in report.dimensions if d.name == "budget_constraints")
        assert budget.score == 0.0

    def test_partial_budget(self, calculator):
        wf = _make_workflow(budget=BudgetSpec(max_tokens=1000))
        report = calculator.calculate(wf)
        budget = next(d for d in report.dimensions if d.name == "budget_constraints")
        assert 0.0 < budget.score < 1.0


class TestOversightDensity:
    def test_more_gates_higher_score(self, calculator):
        wf = _make_workflow(tasks={
            "t1": TaskConfig(name="t1", type="agent_task"),
            "g1": TaskConfig(name="g1", type="approval_gate"),
            "g2": TaskConfig(name="g2", type="input_gate"),
        })
        report = calculator.calculate(wf)
        oversight = next(d for d in report.dimensions if d.name == "human_oversight")
        assert oversight.score > 0.5

    def test_no_gates_zero_score(self, calculator):
        wf = _make_workflow(tasks={
            "t1": TaskConfig(name="t1", type="agent_task"),
        })
        report = calculator.calculate(wf)
        oversight = next(d for d in report.dimensions if d.name == "human_oversight")
        assert oversight.score == 0.0

    def test_no_tasks_zero_score(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf)
        oversight = next(d for d in report.dimensions if d.name == "human_oversight")
        assert oversight.score == 0.0


class TestAdversarialCoverage:
    def test_validated_tasks_score(self, calculator):
        wf = _make_workflow(tasks={
            "research": TaskConfig(name="research", type="agent_task", description="Do research"),
            "validate": TaskConfig(
                name="validate", type="agent_task",
                description="Validate research findings",
                depends_on=["research"],
            ),
        })
        report = calculator.calculate(wf)
        adv = next(d for d in report.dimensions if d.name == "adversarial_coverage")
        assert adv.score > 0.0

    def test_no_validation_zero_score(self, calculator):
        wf = _make_workflow(tasks={
            "research": TaskConfig(name="research", type="agent_task", description="Do research"),
            "implement": TaskConfig(
                name="implement", type="agent_task",
                description="Write code",
                depends_on=["research"],
            ),
        })
        report = calculator.calculate(wf)
        adv = next(d for d in report.dimensions if d.name == "adversarial_coverage")
        assert adv.score == 0.0


class TestHistoricalReliability:
    def test_no_history_neutral(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf)
        hist = next(d for d in report.dimensions if d.name == "historical_reliability")
        assert hist.score == 0.5

    def test_all_succeeded(self, calculator, event_log, seq):
        for i in range(5):
            event_log.append(Event(
                event_type=EventType.WORKFLOW_COMPLETED,
                workflow_id=f"wf-{i}",
                seq=seq.next(),
                payload={"status": "succeeded", "workflow_name": "test_wf"},
            ))
        wf = _make_workflow()
        report = calculator.calculate(wf)
        hist = next(d for d in report.dimensions if d.name == "historical_reliability")
        assert hist.score == 1.0

    def test_mixed_results(self, calculator, event_log, seq):
        for i, status in enumerate(["succeeded", "failed", "succeeded", "succeeded"]):
            event_log.append(Event(
                event_type=EventType.WORKFLOW_COMPLETED,
                workflow_id=f"wf-{i}",
                seq=seq.next(),
                payload={"status": status, "workflow_name": "test_wf"},
            ))
        wf = _make_workflow()
        report = calculator.calculate(wf)
        hist = next(d for d in report.dimensions if d.name == "historical_reliability")
        assert hist.score == 0.75


class TestGradeMapping:
    def test_grade_a(self, calculator):
        assert SafetyScoreCalculator._to_grade(0.95) == "A"

    def test_grade_b(self, calculator):
        assert SafetyScoreCalculator._to_grade(0.85) == "B"

    def test_grade_c(self, calculator):
        assert SafetyScoreCalculator._to_grade(0.65) == "C"

    def test_grade_d(self, calculator):
        assert SafetyScoreCalculator._to_grade(0.45) == "D"

    def test_grade_f(self, calculator):
        assert SafetyScoreCalculator._to_grade(0.2) == "F"


class TestMinimumThreshold:
    def test_meets_minimum(self, calculator):
        wf = _make_workflow(budget=BudgetSpec(max_tokens=1000, max_cost_usd=1.0, max_time_seconds=60.0))
        policies = {"a1": CapabilityPolicy(agent_id="a1", sandbox=SandboxLevel.CONTAINER)}
        report = calculator.calculate(wf, policies, minimum=0.3)
        assert report.meets_minimum is True

    def test_below_minimum(self, calculator):
        wf = _make_workflow()
        report = calculator.calculate(wf, {}, minimum=0.9)
        assert report.meets_minimum is False
        assert report.minimum_threshold == 0.9
