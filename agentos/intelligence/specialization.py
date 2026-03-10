"""Cross-workflow specialization — track agent performance per role."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean


@dataclass
class PerformanceRecord:
    """Performance of an agent in a specific role."""

    agent_id: str
    role: str
    workflow_id: str
    quality_score: float
    cost_usd: float
    duration_seconds: float
    success: bool


@dataclass
class SpecializationScore:
    """Specialization score for an agent-role pair."""

    agent_id: str
    role: str
    avg_quality: float
    avg_cost: float
    success_rate: float
    sample_size: int
    score: float  # Composite 0-1


@dataclass
class PromptRefinement:
    """A refined system prompt based on accumulated feedback."""

    agent_id: str
    role: str
    original_prompt: str
    refined_prompt: str
    feedback_count: int


class SpecializationTracker:
    """Tracks agent performance per role across workflows.

    Computes specialization scores and generates prompt refinements
    from accumulated gate feedback.
    """

    def __init__(self) -> None:
        self._records: list[PerformanceRecord] = []
        self._feedback: dict[tuple[str, str], list[str]] = {}  # (agent_id, role) -> feedback list

    def record_performance(self, record: PerformanceRecord) -> None:
        """Record a performance observation."""
        self._records.append(record)

    def add_feedback(self, agent_id: str, role: str, feedback: str) -> None:
        """Add gate feedback for an agent-role pair."""
        key = (agent_id, role)
        self._feedback.setdefault(key, []).append(feedback)

    def get_specialization_scores(self, agent_id: str | None = None) -> list[SpecializationScore]:
        """Compute specialization scores for each agent-role pair."""
        groups: dict[tuple[str, str], list[PerformanceRecord]] = {}
        for r in self._records:
            if agent_id and r.agent_id != agent_id:
                continue
            key = (r.agent_id, r.role)
            groups.setdefault(key, []).append(r)

        scores: list[SpecializationScore] = []
        for (aid, role), records in groups.items():
            avg_quality = mean(r.quality_score for r in records)
            avg_cost = mean(r.cost_usd for r in records)
            success_rate = sum(1 for r in records if r.success) / len(records)

            # Composite score: quality-weighted success rate
            score = avg_quality * 0.6 + success_rate * 0.3 + (1 - min(avg_cost, 1.0)) * 0.1

            scores.append(SpecializationScore(
                agent_id=aid,
                role=role,
                avg_quality=round(avg_quality, 3),
                avg_cost=round(avg_cost, 4),
                success_rate=round(success_rate, 3),
                sample_size=len(records),
                score=round(min(1.0, max(0.0, score)), 3),
            ))

        return sorted(scores, key=lambda s: -s.score)

    def get_best_agent_for_role(self, role: str) -> str | None:
        """Find the best agent for a given role based on specialization scores."""
        scores = self.get_specialization_scores()
        role_scores = [s for s in scores if s.role == role]
        if not role_scores:
            return None
        return role_scores[0].agent_id

    def refine_prompt(self, agent_id: str, role: str, original_prompt: str) -> PromptRefinement:
        """Generate a refined prompt based on accumulated feedback."""
        key = (agent_id, role)
        feedback_list = self._feedback.get(key, [])

        if not feedback_list:
            return PromptRefinement(
                agent_id=agent_id,
                role=role,
                original_prompt=original_prompt,
                refined_prompt=original_prompt,
                feedback_count=0,
            )

        # Build refinement from feedback
        feedback_section = "\n".join(f"- {f}" for f in feedback_list[-10:])  # Last 10
        refined = f"{original_prompt}\n\nBased on previous feedback, please also:\n{feedback_section}"

        return PromptRefinement(
            agent_id=agent_id,
            role=role,
            original_prompt=original_prompt,
            refined_prompt=refined,
            feedback_count=len(feedback_list),
        )

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def tracked_agents(self) -> set[str]:
        return {r.agent_id for r in self._records}

    @property
    def tracked_roles(self) -> set[str]:
        return {r.role for r in self._records}
