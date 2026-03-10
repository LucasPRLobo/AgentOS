"""Agent safety scoring — 6-dimension risk assessment for workflows."""

from __future__ import annotations

from dataclasses import dataclass

from agentos.kernel.event_log import EventLog
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.schemas.sandbox import SandboxLevel
from agentos.schemas.workflow import WorkflowDefinition


@dataclass
class SafetyDimension:
    """A single scored dimension with weight."""

    name: str
    score: float  # 0.0 (unsafe) to 1.0 (safe)
    weight: float
    rationale: str


@dataclass
class SafetyReport:
    """Complete safety score for a workflow."""

    overall_score: float  # Weighted average, 0.0–1.0
    grade: str  # A/B/C/D/F
    dimensions: list[SafetyDimension]
    meets_minimum: bool
    minimum_threshold: float


class SafetyScoreCalculator:
    """Calculates 6-dimension safety score for a workflow.

    Dimensions:
    1. permissions_scope — How restricted are agent capabilities?
    2. isolation_level — What sandbox level is configured?
    3. budget_constraints — How tight are budget limits?
    4. human_oversight — How many gates per critical path?
    5. adversarial_coverage — What % of outputs have validation nodes?
    6. historical_reliability — Past success rate for this config
    """

    DEFAULT_MINIMUM = 0.5

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def calculate(
        self,
        workflow: WorkflowDefinition,
        policies: dict[str, CapabilityPolicy] | None = None,
        minimum: float = DEFAULT_MINIMUM,
    ) -> SafetyReport:
        """Calculate safety score for a workflow configuration."""
        policies = policies or {}
        dimensions = [
            self._score_permissions(workflow, policies),
            self._score_isolation(policies),
            self._score_budget(workflow),
            self._score_oversight(workflow),
            self._score_adversarial(workflow),
            self._score_reliability(workflow),
        ]
        total_weight = sum(d.weight for d in dimensions)
        overall = (
            sum(d.score * d.weight for d in dimensions) / total_weight
            if total_weight
            else 0.0
        )

        return SafetyReport(
            overall_score=round(overall, 3),
            grade=self._to_grade(overall),
            dimensions=dimensions,
            meets_minimum=overall >= minimum,
            minimum_threshold=minimum,
        )

    def _score_permissions(
        self,
        workflow: WorkflowDefinition,
        policies: dict[str, CapabilityPolicy],
    ) -> SafetyDimension:
        """Score based on how restricted agent permissions are."""
        if not policies:
            return SafetyDimension("permissions_scope", 0.2, 1.0, "No policies defined")

        deny_default_count = sum(1 for p in policies.values() if p.deny_by_default)
        ratio = deny_default_count / len(policies)
        avg_grants = sum(len(p.grants) for p in policies.values()) / len(policies)
        grant_penalty = min(avg_grants / 20.0, 0.5)
        score = max(0.0, ratio - grant_penalty)
        return SafetyDimension(
            "permissions_scope",
            round(score, 3),
            1.0,
            f"{deny_default_count}/{len(policies)} agents deny-by-default",
        )

    def _score_isolation(
        self, policies: dict[str, CapabilityPolicy],
    ) -> SafetyDimension:
        """Score based on sandbox isolation levels."""
        level_scores = {
            SandboxLevel.NONE: 0.2,
            SandboxLevel.NAMESPACE: 0.6,
            SandboxLevel.CONTAINER: 1.0,
        }
        if not policies:
            return SafetyDimension("isolation_level", 0.2, 1.0, "No policies — no isolation")
        avg = sum(level_scores.get(p.sandbox, 0.2) for p in policies.values()) / len(
            policies
        )
        return SafetyDimension(
            "isolation_level", round(avg, 3), 1.0, "Averaged across agents"
        )

    def _score_budget(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on budget constraint tightness."""
        budget = workflow.budget
        has_limits = 0
        if budget.max_tokens is not None and budget.max_tokens > 0:
            has_limits += 1
        if budget.max_cost_usd is not None and budget.max_cost_usd > 0:
            has_limits += 1
        if budget.max_time_seconds is not None and budget.max_time_seconds > 0:
            has_limits += 1
        score = min(has_limits / 3.0, 1.0)
        return SafetyDimension(
            "budget_constraints",
            round(score, 3),
            0.8,
            f"{has_limits}/3 budget dimensions configured",
        )

    def _score_oversight(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on human oversight density."""
        total_tasks = len(workflow.tasks)
        gate_tasks = sum(
            1
            for t in workflow.tasks.values()
            if t.type in ("approval_gate", "input_gate")
        )
        if total_tasks == 0:
            return SafetyDimension("human_oversight", 0.0, 0.8, "No tasks")
        ratio = gate_tasks / total_tasks
        score = min(ratio * 3.0, 1.0)
        return SafetyDimension(
            "human_oversight",
            round(score, 3),
            0.8,
            f"{gate_tasks}/{total_tasks} tasks are gates",
        )

    def _score_adversarial(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on adversarial validation coverage."""
        agent_tasks = [
            t for t in workflow.tasks.values() if t.type == "agent_task"
        ]
        validated = 0
        for task in agent_tasks:
            for other in workflow.tasks.values():
                if other.type == "agent_task" and task.name in other.depends_on:
                    if "validat" in other.description.lower():
                        validated += 1
                        break
        total = len(agent_tasks)
        score = validated / total if total else 0.0
        return SafetyDimension(
            "adversarial_coverage",
            round(score, 3),
            0.6,
            f"{validated}/{total} agent tasks have validation",
        )

    def _score_reliability(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on historical success rate for this workflow."""
        events = self._event_log.query(event_type=EventType.WORKFLOW_COMPLETED)
        matching = [
            e for e in events if e.payload.get("workflow_name") == workflow.name
        ]
        if not matching:
            return SafetyDimension(
                "historical_reliability",
                0.5,
                0.5,
                "No historical data — neutral score",
            )
        successes = sum(
            1 for e in matching if e.payload.get("status") == "succeeded"
        )
        score = successes / len(matching)
        return SafetyDimension(
            "historical_reliability",
            round(score, 3),
            0.5,
            f"{successes}/{len(matching)} past runs succeeded",
        )

    @staticmethod
    def _to_grade(score: float) -> str:
        if score >= 0.9:
            return "A"
        elif score >= 0.8:
            return "B"
        elif score >= 0.6:
            return "C"
        elif score >= 0.4:
            return "D"
        else:
            return "F"
