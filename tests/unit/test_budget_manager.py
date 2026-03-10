"""Tests for BudgetManager."""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType


class TestApply:
    def test_apply_accumulates_usage(self, budget_manager: BudgetManager) -> None:
        budget_manager.apply("agent-1", BudgetDelta(tokens=500, api_calls=2))
        budget_manager.apply("agent-1", BudgetDelta(tokens=300, api_calls=1))

        usage = budget_manager.usage_for("agent-1")
        assert usage.tokens_used == 800
        assert usage.api_calls_made == 3

    def test_apply_emits_budget_consumed_event(
        self,
        event_log: SQLiteEventLog,
        budget_manager: BudgetManager,
    ) -> None:
        budget_manager.apply("agent-1", BudgetDelta(tokens=100))

        events = event_log.query(event_type=EventType.BUDGET_CONSUMED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "agent-1"
        assert events[0].payload["delta"]["tokens"] == 100


class TestWorkflowLevelEnforcement:
    def test_budget_workflow_level(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Workflow-level limit enforced across all agents."""
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=1000),
            event_log=event_log,
            seq=seq,
            workflow_id="test-wf",
        )
        mgr.apply("agent-1", BudgetDelta(tokens=600))
        mgr.apply("agent-2", BudgetDelta(tokens=300))

        with pytest.raises(BudgetExceededError, match="tokens"):
            mgr.apply("agent-2", BudgetDelta(tokens=200))

    def test_budget_hard_enforcement(self, budget_manager: BudgetManager) -> None:
        """Exceeding token limit raises BudgetExceededError."""
        # budget_spec has max_tokens=10000
        budget_manager.apply("agent-1", BudgetDelta(tokens=9000))

        with pytest.raises(BudgetExceededError, match="tokens"):
            budget_manager.apply("agent-1", BudgetDelta(tokens=2000))


class TestPerAgentEnforcement:
    def test_budget_per_agent(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Agent A's usage doesn't count against Agent B's limit."""
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(),  # no workflow limit
            event_log=event_log,
            seq=seq,
            workflow_id="test-wf",
            agent_specs={
                "agent-a": BudgetSpec(max_tokens=1000),
                "agent-b": BudgetSpec(max_tokens=1000),
            },
        )
        mgr.apply("agent-a", BudgetDelta(tokens=900))
        # agent-b should still have full budget
        mgr.apply("agent-b", BudgetDelta(tokens=900))

        assert mgr.usage_for("agent-a").tokens_used == 900
        assert mgr.usage_for("agent-b").tokens_used == 900


class TestMultipleDimensions:
    def test_budget_multiple_dimensions(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """Enforce tokens AND cost simultaneously."""
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=10000, max_cost_usd=0.50),
            event_log=event_log,
            seq=seq,
            workflow_id="test-wf",
        )
        # Under token limit but will exceed cost
        mgr.apply("agent-1", BudgetDelta(tokens=1000, cost_usd=0.40))

        with pytest.raises(BudgetExceededError, match="cost_usd"):
            mgr.apply("agent-1", BudgetDelta(tokens=1000, cost_usd=0.20))


class TestBudgetExceededEvent:
    def test_exceeded_event_emitted(
        self,
        event_log: SQLiteEventLog,
        budget_manager: BudgetManager,
    ) -> None:
        budget_manager.apply("agent-1", BudgetDelta(tokens=9000))

        with pytest.raises(BudgetExceededError):
            budget_manager.apply("agent-1", BudgetDelta(tokens=2000))

        events = event_log.query(event_type=EventType.BUDGET_EXCEEDED)
        assert len(events) == 1
        assert events[0].payload["resource"] == "tokens"
        assert events[0].payload["limit"] == 10000


class TestUnlimitedDimension:
    def test_unlimited_dimension(
        self, event_log: SQLiteEventLog, seq: SeqCounter
    ) -> None:
        """None limit means no enforcement for that dimension."""
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(),  # all None
            event_log=event_log,
            seq=seq,
            workflow_id="test-wf",
        )
        # Should not raise no matter how much we consume
        mgr.apply("agent-1", BudgetDelta(tokens=999999, cost_usd=9999.0))
        assert mgr.usage_for("agent-1").tokens_used == 999999


class TestTotalUsage:
    def test_total_usage(self, budget_manager: BudgetManager) -> None:
        budget_manager.apply("agent-1", BudgetDelta(tokens=500, cost_usd=0.10))
        budget_manager.apply("agent-2", BudgetDelta(tokens=300, cost_usd=0.05))

        total = budget_manager.total_usage
        assert total.tokens_used == 800
        assert total.cost_usd == pytest.approx(0.15)


class TestCheckFresh:
    def test_check_before_any_usage(self, budget_manager: BudgetManager) -> None:
        """Check on fresh manager should pass without error."""
        budget_manager.check("agent-1")


# ---------------------------------------------------------------------------
# Sprint 7: Budget enforcement edge cases
# ---------------------------------------------------------------------------

class TestExactLimitBoundary:
    """Verify behavior when usage exactly matches the limit."""

    def test_exact_tokens_passes(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=1000),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        mgr.apply("agent-1", BudgetDelta(tokens=1000))
        # Exactly at limit — should NOT raise (current > limit, not >=)
        assert mgr.usage_for("agent-1").tokens_used == 1000

    def test_one_over_limit_fails(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=1000),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        with pytest.raises(BudgetExceededError, match="tokens"):
            mgr.apply("agent-1", BudgetDelta(tokens=1001))

    def test_exact_cost_passes(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_cost_usd=1.00),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        mgr.apply("agent-1", BudgetDelta(cost_usd=1.00))
        assert mgr.usage_for("agent-1").cost_usd == pytest.approx(1.00)


class TestGradualApproach:
    """Many small allocations gradually approaching the limit."""

    def test_many_small_allocations(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=1000),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        for _ in range(100):
            mgr.apply("agent-1", BudgetDelta(tokens=10))

        assert mgr.usage_for("agent-1").tokens_used == 1000

        with pytest.raises(BudgetExceededError):
            mgr.apply("agent-1", BudgetDelta(tokens=1))

    def test_gradual_cost_approach(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_cost_usd=1.00),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        # Use 0.25 increments to avoid floating-point accumulation errors
        for _ in range(4):
            mgr.apply("agent-1", BudgetDelta(cost_usd=0.25))

        assert mgr.usage_for("agent-1").cost_usd == pytest.approx(1.00)

        with pytest.raises(BudgetExceededError, match="cost_usd"):
            mgr.apply("agent-1", BudgetDelta(cost_usd=0.01))


class TestApiCallsEnforcement:
    """Verify api_calls limit is enforced."""

    def test_api_calls_exceeded(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_api_calls=5),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        for _ in range(5):
            mgr.apply("agent-1", BudgetDelta(api_calls=1))

        with pytest.raises(BudgetExceededError, match="api_calls"):
            mgr.apply("agent-1", BudgetDelta(api_calls=1))

    def test_api_calls_exact_limit_passes(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_api_calls=3),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        mgr.apply("agent-1", BudgetDelta(api_calls=3))
        assert mgr.usage_for("agent-1").api_calls_made == 3


class TestTimeSecondsEnforcement:
    """Verify time_seconds limit is enforced."""

    def test_time_exceeded(self, event_log: SQLiteEventLog, seq: SeqCounter) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_time_seconds=60.0),
            event_log=event_log, seq=seq, workflow_id="test-wf",
        )
        mgr.apply("agent-1", BudgetDelta(time_seconds=50.0))

        with pytest.raises(BudgetExceededError, match="time_seconds"):
            mgr.apply("agent-1", BudgetDelta(time_seconds=20.0))


class TestWorkflowLimitOverridesAgent:
    """Workflow-level limit takes precedence when agent limit is higher."""

    def test_workflow_limit_enforced_over_agent(
        self, event_log: SQLiteEventLog, seq: SeqCounter,
    ) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=500),
            event_log=event_log, seq=seq, workflow_id="test-wf",
            agent_specs={"agent-1": BudgetSpec(max_tokens=10000)},
        )
        mgr.apply("agent-1", BudgetDelta(tokens=400))

        # Agent limit is 10000, but workflow limit is 500
        with pytest.raises(BudgetExceededError, match="tokens"):
            mgr.apply("agent-1", BudgetDelta(tokens=200))

    def test_agent_limit_enforced_under_workflow(
        self, event_log: SQLiteEventLog, seq: SeqCounter,
    ) -> None:
        mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=10000),
            event_log=event_log, seq=seq, workflow_id="test-wf",
            agent_specs={"agent-1": BudgetSpec(max_tokens=500)},
        )
        mgr.apply("agent-1", BudgetDelta(tokens=400))

        with pytest.raises(BudgetExceededError, match="tokens"):
            mgr.apply("agent-1", BudgetDelta(tokens=200))
