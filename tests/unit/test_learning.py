"""Tests for workflow-level learning."""

from __future__ import annotations

import pytest

from agentos.intelligence.learning import (
    ConfigRecommender,
    Pattern,
    PatternDetector,
    WorkflowRecord,
)


def _make_record(
    team: list[str] | None = None,
    cost: float = 0.1,
    duration: float = 30.0,
    quality: float = 0.8,
    success: bool = True,
    wf_id: str = "",
) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=wf_id or f"wf-{id(team)}",
        workflow_name="test",
        team_composition=team or ["agent-1"],
        total_cost_usd=cost,
        total_duration_seconds=duration,
        quality_score=quality,
        success=success,
    )


class TestPatternDetection:
    def test_no_patterns_with_few_records(self):
        detector = PatternDetector()
        detector.add_record(_make_record())
        assert detector.detect_patterns() == []

    def test_team_size_pattern(self):
        detector = PatternDetector()
        # Small teams with lower quality
        for i in range(5):
            detector.add_record(_make_record(team=["a"], quality=0.5, wf_id=f"small-{i}"))
        # Large teams with higher quality
        for i in range(5):
            detector.add_record(_make_record(team=["a", "b", "c"], quality=0.9, wf_id=f"large-{i}"))
        patterns = detector.detect_patterns()
        team_patterns = [p for p in patterns if "team" in p.description.lower()]
        assert len(team_patterns) >= 1

    def test_cost_quality_correlation(self):
        detector = PatternDetector()
        for i in range(10):
            detector.add_record(_make_record(
                cost=0.01 * (i + 1),
                quality=0.1 * (i + 1) / 10,
                wf_id=f"corr-{i}",
            ))
        patterns = detector.detect_patterns()
        corr_patterns = [p for p in patterns if "correlated" in p.description.lower()]
        assert len(corr_patterns) >= 1

    def test_low_success_rate_pattern(self):
        detector = PatternDetector()
        for i in range(5):
            detector.add_record(_make_record(
                team=["failing-agent"],
                success=False,
                wf_id=f"fail-{i}",
            ))
        patterns = detector.detect_patterns()
        success_patterns = [p for p in patterns if "success rate" in p.description.lower()]
        assert len(success_patterns) >= 1

    def test_pattern_has_confidence(self):
        detector = PatternDetector()
        for i in range(10):
            detector.add_record(_make_record(
                team=["a", "b", "c"] if i % 2 == 0 else ["a"],
                quality=0.9 if i % 2 == 0 else 0.3,
                wf_id=f"conf-{i}",
            ))
        patterns = detector.detect_patterns()
        for p in patterns:
            assert 0.0 <= p.confidence <= 1.0
            assert p.sample_size > 0


class TestConfigRecommender:
    def test_budget_recommendations(self):
        records = [_make_record(cost=0.10, duration=30.0, wf_id=f"r-{i}") for i in range(5)]
        recommender = ConfigRecommender()
        recs = recommender.recommend([], records)
        budget_recs = [r for r in recs if r.category == "budget"]
        assert len(budget_recs) >= 1

    def test_team_recommendation_from_pattern(self):
        patterns = [Pattern(
            description="Larger teams produce higher quality",
            confidence=0.8,
            sample_size=10,
            recommendation="Use larger teams",
        )]
        records = [_make_record(wf_id="r-1")]
        recommender = ConfigRecommender()
        recs = recommender.recommend(patterns, records)
        team_recs = [r for r in recs if r.category == "team"]
        assert len(team_recs) >= 1
        assert team_recs[0].description == "Use larger teams"

    def test_no_recommendations_without_records(self):
        recommender = ConfigRecommender()
        assert recommender.recommend([], []) == []

    def test_low_confidence_patterns_skipped(self):
        patterns = [Pattern(
            description="Weak pattern",
            confidence=0.2,
            sample_size=2,
            recommendation="Don't use this",
        )]
        records = [_make_record(wf_id="r-1")]
        recommender = ConfigRecommender()
        recs = recommender.recommend(patterns, records)
        team_recs = [r for r in recs if r.category == "team"]
        assert len(team_recs) == 0


class TestPearsonCorrelation:
    def test_perfect_positive(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        r = PatternDetector._pearson(x, y)
        assert abs(r - 1.0) < 0.01

    def test_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 8.0, 6.0, 4.0, 2.0]
        r = PatternDetector._pearson(x, y)
        assert abs(r - (-1.0)) < 0.01

    def test_no_correlation(self):
        x = [1.0, 1.0, 1.0]
        y = [1.0, 2.0, 3.0]
        r = PatternDetector._pearson(x, y)
        assert abs(r) < 0.01
