"""E2E tests for RLM budget enforcement, stop conditions, and REPL safety."""

from __future__ import annotations

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.lm.recursive_executor import RLMConfig, RecursiveExecutor
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType

from labos.domain.schemas import ExperimentConfig
from labos.workflows.ml_replication import run_rlm_pipeline

from tests.conftest import MockLMProvider, assert_has_event

pytestmark = pytest.mark.e2e


class TestBudgetHaltsRunawayRLM:
    """Verify tiny budget halts an RLM that never sets FINAL."""

    def test_budget_exceeded_outcome(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        spec = BudgetSpec(
            max_tokens=50,
            max_tool_calls=100,
            max_time_seconds=30.0,
            max_recursion_depth=2,
        )
        bm = BudgetManager(spec, log, rid)

        # Provider that never produces code setting FINAL
        provider = MockLMProvider(responses=["x = 1\nprint(x)"])

        executor = RecursiveExecutor(log, provider, budget_manager=bm)
        run_id, result = executor.run(
            "never finish",
            run_id=rid,
            config=RLMConfig(max_iterations=100),
        )

        events = log.query_by_run(rid)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "BUDGET_EXCEEDED"
        assert result is None
        log.close()


class TestConsecutiveFailuresStop:
    """Verify consecutive REPL failures trigger stop condition."""

    def test_consecutive_failures_trigger_stop(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()

        stop_checker = StopConditionChecker(
            log, rid, max_consecutive_failures=3
        )

        # Provider that always generates invalid code
        provider = MockLMProvider(responses=["raise ValueError('boom')"])

        executor = RecursiveExecutor(
            log, provider, stop_checker=stop_checker,
        )
        run_id, result = executor.run(
            "fail repeatedly",
            run_id=rid,
            config=RLMConfig(max_iterations=20),
        )

        events = log.query_by_run(rid)
        # Should have stop condition event
        assert_has_event(events, EventType.STOP_CONDITION)

        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "STOPPED"
        log.close()


class TestMaxIterationsOutcome:
    """Verify max_iterations=3 leads to MAX_ITERATIONS outcome."""

    def test_max_iterations_outcome(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()

        # Provider that never sets FINAL
        provider = MockLMProvider(responses=["x = 1"])

        executor = RecursiveExecutor(log, provider)
        run_id, result = executor.run(
            "run 3 times",
            run_id=rid,
            config=RLMConfig(max_iterations=3),
        )

        events = log.query_by_run(rid)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished
        assert run_finished[-1].payload["outcome"] == "MAX_ITERATIONS"
        assert result is None
        log.close()


class TestREPLBlocksImport:
    """Verify REPL blocks `import os` without crashing the RLM."""

    def test_import_blocked_continues(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()

        # First response tries import, second sets FINAL
        provider = MockLMProvider(responses=[
            "import os\nprint(os.getcwd())",
            'FINAL = "recovered"',
        ])

        executor = RecursiveExecutor(log, provider)
        run_id, result = executor.run(
            "try import",
            run_id=rid,
            config=RLMConfig(max_iterations=10),
        )

        # Should recover and succeed
        assert result == "recovered"

        events = log.query_by_run(rid)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert run_finished[-1].payload["outcome"] == "SUCCEEDED"
        log.close()


class TestREPLBlocksOpen:
    """Verify REPL blocks `open('/etc/passwd')` safely."""

    def test_open_blocked_safely(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()

        provider = MockLMProvider(responses=[
            "f = open('/etc/passwd')\ndata = f.read()",
            'FINAL = "safe"',
        ])

        executor = RecursiveExecutor(log, provider)
        run_id, result = executor.run(
            "try file access",
            run_id=rid,
            config=RLMConfig(max_iterations=10),
        )

        assert result == "safe"

        events = log.query_by_run(rid)
        # REPL should have blocked the open() call
        repl_finished = [e for e in events if e.event_type == EventType.REPL_EXEC_FINISHED]
        # First iteration should have failed
        assert repl_finished[0].payload["success"] is False
        log.close()
