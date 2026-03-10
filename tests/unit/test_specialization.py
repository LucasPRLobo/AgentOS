"""Tests for cross-workflow specialization."""

from __future__ import annotations

import pytest

from agentos.intelligence.specialization import (
    PerformanceRecord,
    SpecializationTracker,
)


def _make_perf(
    agent: str = "agent-1",
    role: str = "researcher",
    quality: float = 0.8,
    cost: float = 0.05,
    success: bool = True,
    wf_id: str = "",
) -> PerformanceRecord:
    return PerformanceRecord(
        agent_id=agent,
        role=role,
        workflow_id=wf_id or f"wf-{id(agent)}",
        quality_score=quality,
        cost_usd=cost,
        duration_seconds=30.0,
        success=success,
    )


@pytest.fixture
def tracker() -> SpecializationTracker:
    return SpecializationTracker()


class TestPerformanceTracking:
    def test_record_performance(self, tracker):
        tracker.record_performance(_make_perf())
        assert tracker.record_count == 1

    def test_tracked_agents(self, tracker):
        tracker.record_performance(_make_perf(agent="a"))
        tracker.record_performance(_make_perf(agent="b"))
        assert tracker.tracked_agents == {"a", "b"}

    def test_tracked_roles(self, tracker):
        tracker.record_performance(_make_perf(role="researcher"))
        tracker.record_performance(_make_perf(role="coder"))
        assert tracker.tracked_roles == {"researcher", "coder"}


class TestSpecializationScores:
    def test_single_agent_score(self, tracker):
        for i in range(5):
            tracker.record_performance(_make_perf(quality=0.8, cost=0.05, wf_id=f"wf-{i}"))
        scores = tracker.get_specialization_scores()
        assert len(scores) == 1
        assert scores[0].sample_size == 5
        assert scores[0].avg_quality == 0.8

    def test_multiple_agents_ranked(self, tracker):
        for i in range(5):
            tracker.record_performance(_make_perf(agent="good", quality=0.9, wf_id=f"g-{i}"))
            tracker.record_performance(_make_perf(agent="bad", quality=0.3, success=False, wf_id=f"b-{i}"))
        scores = tracker.get_specialization_scores()
        assert scores[0].agent_id == "good"
        assert scores[0].score > scores[1].score

    def test_filter_by_agent(self, tracker):
        tracker.record_performance(_make_perf(agent="a", wf_id="w1"))
        tracker.record_performance(_make_perf(agent="b", wf_id="w2"))
        scores = tracker.get_specialization_scores(agent_id="a")
        assert len(scores) == 1
        assert scores[0].agent_id == "a"

    def test_separate_roles(self, tracker):
        tracker.record_performance(_make_perf(agent="a", role="researcher", wf_id="w1"))
        tracker.record_performance(_make_perf(agent="a", role="coder", wf_id="w2"))
        scores = tracker.get_specialization_scores()
        assert len(scores) == 2

    def test_score_bounds(self, tracker):
        tracker.record_performance(_make_perf(quality=1.0, cost=0.0, wf_id="w1"))
        tracker.record_performance(_make_perf(quality=0.0, cost=1.0, success=False, wf_id="w2"))
        scores = tracker.get_specialization_scores()
        for s in scores:
            assert 0.0 <= s.score <= 1.0


class TestBestAgent:
    def test_best_agent_for_role(self, tracker):
        for i in range(5):
            tracker.record_performance(_make_perf(agent="expert", role="researcher", quality=0.95, wf_id=f"e-{i}"))
            tracker.record_performance(_make_perf(agent="novice", role="researcher", quality=0.4, wf_id=f"n-{i}"))
        best = tracker.get_best_agent_for_role("researcher")
        assert best == "expert"

    def test_no_agent_for_role(self, tracker):
        assert tracker.get_best_agent_for_role("unknown") is None


class TestPromptRefinement:
    def test_refine_with_feedback(self, tracker):
        tracker.add_feedback("agent-1", "researcher", "Be more concise")
        tracker.add_feedback("agent-1", "researcher", "Include sources")
        refinement = tracker.refine_prompt("agent-1", "researcher", "You are a researcher.")
        assert "Be more concise" in refinement.refined_prompt
        assert "Include sources" in refinement.refined_prompt
        assert refinement.feedback_count == 2

    def test_refine_without_feedback(self, tracker):
        refinement = tracker.refine_prompt("agent-1", "coder", "You are a coder.")
        assert refinement.refined_prompt == "You are a coder."
        assert refinement.feedback_count == 0

    def test_refine_limits_feedback(self, tracker):
        for i in range(20):
            tracker.add_feedback("agent-1", "role", f"Feedback {i}")
        refinement = tracker.refine_prompt("agent-1", "role", "Base prompt")
        # Should only include last 10
        assert "Feedback 19" in refinement.refined_prompt
        assert "Feedback 0" not in refinement.refined_prompt
