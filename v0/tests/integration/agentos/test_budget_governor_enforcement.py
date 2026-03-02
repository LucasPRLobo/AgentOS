"""Integration tests for budget manager enforcement with event emission."""

from __future__ import annotations

import pytest

from agentos.core.errors import BudgetExceededError
from agentos.core.identifiers import generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.lm.provider import LMMessage
from agentos.lm.recursive_executor import RLMConfig, RecursiveExecutor
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType

from tests.conftest import MockLMProvider, assert_has_event

pytestmark = pytest.mark.integration


class TestTokenLimitHaltsRLM:
    """Verify that exceeding token limit halts RLM and emits BudgetExceeded."""

    def test_token_limit_produces_budget_exceeded_event(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=50,
            max_tool_calls=100,
            max_time_seconds=60.0,
            max_recursion_depth=2,
        )
        bm = BudgetManager(spec, log, rid)

        # Mock that generates long responses to blow through the budget
        provider = MockLMProvider(responses=["x" * 60])

        executor = RecursiveExecutor(log, provider, budget_manager=bm)
        run_id, result = executor.run("test prompt", run_id=rid, config=RLMConfig(max_iterations=10))

        events = log.query_by_run(rid)
        budget_exceeded = assert_has_event(events, EventType.BUDGET_EXCEEDED)
        assert budget_exceeded.payload["limit"] == "max_tokens"

        # RunFinished should indicate BUDGET_EXCEEDED
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "BUDGET_EXCEEDED"
        log.close()


class TestToolCallsLimit:
    """Verify that exceeding tool_calls limit halts workflow."""

    def test_tool_calls_limit_triggers(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=100_000,
            max_tool_calls=2,
            max_time_seconds=60.0,
            max_recursion_depth=2,
        )
        bm = BudgetManager(spec, log, rid)

        # Manually apply tool calls to exceed budget
        bm.set_seq(0)
        bm.record_tool_call()  # 1
        bm.record_tool_call()  # 2 — now at limit

        with pytest.raises(BudgetExceededError):
            bm.check()

        events = log.query_by_run(rid)
        assert_has_event(events, EventType.BUDGET_EXCEEDED, limit="max_tool_calls")
        log.close()


class TestBudgetEventsEmittedInOrder:
    """Verify BudgetUpdated events appear between tool calls."""

    def test_budget_events_ordered(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=10_000,
            max_tool_calls=50,
            max_time_seconds=60.0,
            max_recursion_depth=2,
        )
        bm = BudgetManager(spec, log, rid)

        bm.set_seq(0)
        bm.record_tool_call()
        bm.record_tokens(100)
        bm.record_tool_call()

        events = log.query_by_run(rid)
        types = [e.event_type for e in events]
        # Each apply emits a BudgetUpdated
        assert types.count(EventType.BUDGET_UPDATED) == 3
        # Sequence numbers should be monotonically increasing
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)
        log.close()


class TestRecursionDepthEnforced:
    """Verify recursion depth is enforced in lm_query."""

    def test_recursion_depth_in_rlm(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=100_000,
            max_tool_calls=100,
            max_time_seconds=60.0,
            max_recursion_depth=1,
        )
        bm = BudgetManager(spec, log, rid)

        # Use RLM with code that calls lm_query which should work at depth 0→1
        # but fail if it tries to go deeper
        provider = MockLMProvider(responses=[
            'result = lm_query("sub-query")\nFINAL = result',
            "sub-answer",
        ])

        executor = RecursiveExecutor(log, provider, budget_manager=bm)
        run_id, result = executor.run(
            "test",
            run_id=rid,
            config=RLMConfig(max_iterations=5, max_recursion_depth=1),
        )

        events = log.query_by_run(rid)
        # Should have LMCallStarted events for both main and sub-query
        lm_calls = [e for e in events if e.event_type == EventType.LM_CALL_STARTED]
        assert len(lm_calls) >= 2
        log.close()


class TestBudgetExceededIdentifiesLimit:
    """Verify BudgetExceeded payload tells which limit was hit."""

    def test_payload_identifies_token_limit(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=10,
            max_tool_calls=100,
            max_time_seconds=60.0,
            max_recursion_depth=2,
        )
        bm = BudgetManager(spec, log, rid)
        bm.set_seq(0)
        bm.record_tokens(10)

        with pytest.raises(BudgetExceededError):
            bm.check()

        events = log.query_by_run(rid)
        exceeded_event = assert_has_event(events, EventType.BUDGET_EXCEEDED)
        assert exceeded_event.payload["limit"] == "max_tokens"
        assert exceeded_event.payload["usage"]["tokens_used"] >= 10
        assert exceeded_event.payload["spec"]["max_tokens"] == 10
        log.close()
