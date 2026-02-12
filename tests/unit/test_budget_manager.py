"""Tests for BudgetManager — enforcement, events, and delta application."""

import pytest

from agentos.core.errors import BudgetExceededError
from agentos.core.identifiers import generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType


def _make_spec(**overrides: int | float) -> BudgetSpec:
    defaults: dict[str, int | float] = {
        "max_tokens": 1000,
        "max_tool_calls": 50,
        "max_time_seconds": 300.0,
        "max_recursion_depth": 10,
    }
    defaults.update(overrides)
    return BudgetSpec(**defaults)  # type: ignore[arg-type]


class TestBudgetManagerCheck:
    def test_check_passes_under_limit(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)
        mgr.check()  # should not raise

    def test_check_fails_on_token_limit(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(max_tokens=5), log, run_id)
        mgr.apply(BudgetDelta(tokens=5))

        with pytest.raises(BudgetExceededError, match="max_tokens"):
            mgr.check()

    def test_check_fails_on_tool_call_limit(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(max_tool_calls=2), log, run_id)
        mgr.record_tool_call()
        mgr.record_tool_call()

        with pytest.raises(BudgetExceededError, match="max_tool_calls"):
            mgr.check()

    def test_check_emits_budget_exceeded_event(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(max_tokens=1), log, run_id)
        mgr.apply(BudgetDelta(tokens=1))

        with pytest.raises(BudgetExceededError):
            mgr.check()

        events = log.query_by_type(run_id, EventType.BUDGET_EXCEEDED)
        assert len(events) == 1
        assert events[0].payload["limit"] == "max_tokens"


class TestBudgetManagerApply:
    def test_apply_delta(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)

        mgr.apply(BudgetDelta(tokens=100, tool_calls=2, time_seconds=1.5))
        assert mgr.usage.tokens_used == 100
        assert mgr.usage.tool_calls_used == 2
        assert mgr.usage.time_elapsed_seconds == 1.5

    def test_apply_emits_budget_updated_event(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)

        mgr.apply(BudgetDelta(tokens=10))
        events = log.query_by_type(run_id, EventType.BUDGET_UPDATED)
        assert len(events) == 1

    def test_cumulative_deltas(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)

        mgr.apply(BudgetDelta(tokens=50))
        mgr.apply(BudgetDelta(tokens=30))
        assert mgr.usage.tokens_used == 80

    def test_record_tool_call(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)

        mgr.record_tool_call()
        mgr.record_tool_call()
        assert mgr.usage.tool_calls_used == 2

    def test_record_tokens(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(), log, run_id)

        mgr.record_tokens(200)
        assert mgr.usage.tokens_used == 200


class TestBudgetManagerRecursion:
    def test_recursion_depth_tracking(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(max_recursion_depth=3), log, run_id)

        mgr.apply(BudgetDelta(recursion_depth_change=1))
        mgr.apply(BudgetDelta(recursion_depth_change=1))
        assert mgr.usage.current_recursion_depth == 2
        mgr.check()  # still ok

        mgr.apply(BudgetDelta(recursion_depth_change=1))
        with pytest.raises(BudgetExceededError, match="max_recursion_depth"):
            mgr.check()

    def test_recursion_depth_decreases(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        mgr = BudgetManager(_make_spec(max_recursion_depth=2), log, run_id)

        mgr.apply(BudgetDelta(recursion_depth_change=1))
        mgr.apply(BudgetDelta(recursion_depth_change=-1))
        assert mgr.usage.current_recursion_depth == 0
        mgr.check()  # should pass
