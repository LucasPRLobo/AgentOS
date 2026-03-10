"""Workflow-level learning — pattern detection and config recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, stdev


@dataclass
class WorkflowRecord:
    """Historical record of a workflow execution."""

    workflow_id: str
    workflow_name: str
    team_composition: list[str]  # agent IDs/roles
    total_cost_usd: float
    total_duration_seconds: float
    quality_score: float  # 0-1
    success: bool
    gate_approval_rate: float = 1.0
    token_usage: int = 0


@dataclass
class Pattern:
    """A detected correlation pattern."""

    description: str
    confidence: float
    sample_size: int
    recommendation: str = ""


@dataclass
class ConfigRecommendation:
    """A recommended configuration change."""

    category: str  # team, budget, model, tools
    description: str
    expected_improvement: str
    confidence: float


class PatternDetector:
    """Detects correlations between team composition and outcome quality."""

    def __init__(self) -> None:
        self._records: list[WorkflowRecord] = []

    def add_record(self, record: WorkflowRecord) -> None:
        self._records.append(record)

    def detect_patterns(self) -> list[Pattern]:
        """Analyze records for patterns."""
        patterns: list[Pattern] = []

        if len(self._records) < 3:
            return patterns

        # Pattern 1: Team size vs quality
        small_teams = [r for r in self._records if len(r.team_composition) <= 2]
        large_teams = [r for r in self._records if len(r.team_composition) > 2]
        if small_teams and large_teams:
            small_avg = mean(r.quality_score for r in small_teams)
            large_avg = mean(r.quality_score for r in large_teams)
            if abs(large_avg - small_avg) > 0.1:
                better = "larger" if large_avg > small_avg else "smaller"
                patterns.append(Pattern(
                    description=f"{better.title()} teams produce higher quality ({max(small_avg, large_avg):.2f} vs {min(small_avg, large_avg):.2f})",
                    confidence=min(0.9, len(self._records) / 20),
                    sample_size=len(self._records),
                    recommendation=f"Consider using {better} teams for this workflow type",
                ))

        # Pattern 2: Cost vs quality correlation
        if len(self._records) >= 5:
            costs = [r.total_cost_usd for r in self._records]
            qualities = [r.quality_score for r in self._records]
            correlation = self._pearson(costs, qualities)
            if abs(correlation) > 0.5:
                direction = "positively" if correlation > 0 else "negatively"
                patterns.append(Pattern(
                    description=f"Cost and quality are {direction} correlated (r={correlation:.2f})",
                    confidence=min(0.85, abs(correlation)),
                    sample_size=len(self._records),
                ))

        # Pattern 3: Success rate by team composition
        comp_groups: dict[str, list[WorkflowRecord]] = {}
        for r in self._records:
            key = ",".join(sorted(r.team_composition))
            comp_groups.setdefault(key, []).append(r)

        for comp, records in comp_groups.items():
            if len(records) >= 2:
                success_rate = sum(1 for r in records if r.success) / len(records)
                if success_rate < 0.5:
                    patterns.append(Pattern(
                        description=f"Team [{comp}] has low success rate ({success_rate:.0%})",
                        confidence=min(0.8, len(records) / 10),
                        sample_size=len(records),
                        recommendation=f"Consider changing team composition for [{comp}]",
                    ))

        return patterns

    @staticmethod
    def _pearson(x: list[float], y: list[float]) -> float:
        """Simple Pearson correlation coefficient."""
        n = len(x)
        if n < 2:
            return 0.0
        mx, my = mean(x), mean(y)
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = (sum((xi - mx) ** 2 for xi in x)) ** 0.5
        dy = (sum((yi - my) ** 2 for yi in y)) ** 0.5
        if dx == 0 or dy == 0:
            return 0.0
        return num / (dx * dy)


class ConfigRecommender:
    """Generates configuration recommendations from detected patterns."""

    def recommend(self, patterns: list[Pattern], records: list[WorkflowRecord]) -> list[ConfigRecommendation]:
        """Generate recommendations from patterns and historical data."""
        recommendations: list[ConfigRecommendation] = []

        if not records:
            return recommendations

        # Budget recommendation based on successful runs
        successful = [r for r in records if r.success]
        if successful:
            avg_cost = mean(r.total_cost_usd for r in successful)
            avg_duration = mean(r.total_duration_seconds for r in successful)
            recommendations.append(ConfigRecommendation(
                category="budget",
                description=f"Set budget to ~${avg_cost * 1.5:.2f} (1.5x avg successful cost of ${avg_cost:.2f})",
                expected_improvement="Avoid over-spending while leaving headroom",
                confidence=min(0.9, len(successful) / 10),
            ))

            recommendations.append(ConfigRecommendation(
                category="budget",
                description=f"Set timeout to ~{avg_duration * 1.5:.0f}s (1.5x avg of {avg_duration:.0f}s)",
                expected_improvement="Prevent runaway execution",
                confidence=min(0.9, len(successful) / 10),
            ))

        # Team recommendation from patterns
        for pattern in patterns:
            if pattern.recommendation and pattern.confidence > 0.5:
                recommendations.append(ConfigRecommendation(
                    category="team",
                    description=pattern.recommendation,
                    expected_improvement=pattern.description,
                    confidence=pattern.confidence,
                ))

        return recommendations
