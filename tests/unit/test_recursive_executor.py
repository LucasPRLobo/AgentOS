"""Tests for RecursiveExecutor — RLM algorithm implementation."""

import pytest

from agentos.core.errors import BudgetExceededError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.lm.recursive_executor import RecursiveExecutor, RLMConfig
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType


class MockLMProvider(BaseLMProvider):
    """Deterministic mock LM provider with scripted responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.call_log: list[list[LMMessage]] = []

    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        self.call_log.append(list(messages))
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        return LMResponse(
            content=content,
            tokens_used=len(content),
            prompt_tokens=sum(len(m.content) for m in messages),
            completion_tokens=len(content),
        )


class TrackingLMProvider(BaseLMProvider):
    """LM provider that tracks all calls including sub-queries."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.all_calls: list[str] = []

    @property
    def name(self) -> str:
        return "tracking"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        last_content = messages[-1].content if messages else ""
        self.all_calls.append(last_content)
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        return LMResponse(content=content, tokens_used=len(content))


class TestRecursiveExecutorSingleIteration:
    def test_immediate_final(self) -> None:
        """LM immediately sets FINAL in one iteration."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'hello world'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, result = executor.run("test prompt")

        assert result == "hello world"
        events = event_log.query_by_run(run_id)
        # Should have: RunStarted, RLMIterationStarted, LMCallStarted,
        # LMCallFinished, REPLExecStarted, REPLExecFinished,
        # RLMIterationFinished, RunFinished
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[-1].event_type == EventType.RUN_FINISHED
        assert events[-1].payload["outcome"] == "SUCCEEDED"

    def test_final_value_returned(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 42"])
        executor = RecursiveExecutor(event_log, provider)

        _, result = executor.run("compute something")
        assert result == "42"


class TestRecursiveExecutorMultiIteration:
    def test_three_step_computation(self) -> None:
        """LM takes 3 steps: compute, transform, set FINAL."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider([
            "x = len(P)",
            "y = x * 2",
            "FINAL = str(y)",
        ])
        executor = RecursiveExecutor(event_log, provider)

        run_id, result = executor.run("hello")

        assert result == "10"  # len("hello")=5, 5*2=10
        events = event_log.query_by_run(run_id)
        assert events[-1].payload["outcome"] == "SUCCEEDED"

    def test_multi_iteration_event_count(self) -> None:
        """Verify correct number of iteration events."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["x = 1", "y = 2", "FINAL = x + y"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        iter_started = event_log.query_by_type(run_id, EventType.RLM_ITERATION_STARTED)
        iter_finished = event_log.query_by_type(run_id, EventType.RLM_ITERATION_FINISHED)
        assert len(iter_started) == 3
        assert len(iter_finished) == 3


class TestRecursiveExecutorRunId:
    def test_custom_run_id(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)
        custom_id = RunId("custom-run-123")

        run_id, _ = executor.run("test", run_id=custom_id)

        assert run_id == custom_id
        events = event_log.query_by_run(custom_id)
        assert len(events) > 0

    def test_generated_run_id(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        assert run_id is not None
        assert len(run_id) > 0


class TestRecursiveExecutorMaxIterations:
    def test_max_iterations_exhausted(self) -> None:
        """When FINAL is never set, outcome is MAX_ITERATIONS."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["x = 1"])  # Never sets FINAL
        config = RLMConfig(max_iterations=3)
        executor = RecursiveExecutor(event_log, provider)

        run_id, result = executor.run("test", config=config)

        assert result is None
        events = event_log.query_by_run(run_id)
        assert events[-1].payload["outcome"] == "MAX_ITERATIONS"

    def test_max_iterations_respected(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["x = 1"])
        config = RLMConfig(max_iterations=5)
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test", config=config)

        iter_events = event_log.query_by_type(run_id, EventType.RLM_ITERATION_STARTED)
        assert len(iter_events) == 5


class TestRecursiveExecutorEventSequence:
    def test_correct_event_order(self) -> None:
        """Verify the event sequence for a single iteration."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        events = event_log.query_by_run(run_id)
        types = [e.event_type for e in events]

        assert types[0] == EventType.RUN_STARTED
        assert EventType.RLM_ITERATION_STARTED in types
        assert EventType.LM_CALL_STARTED in types
        assert EventType.LM_CALL_FINISHED in types
        assert EventType.REPL_EXEC_STARTED in types
        assert EventType.REPL_EXEC_FINISHED in types
        assert EventType.RLM_ITERATION_FINISHED in types
        assert types[-1] == EventType.RUN_FINISHED

    def test_strict_event_ordering_single_iteration(self) -> None:
        """Events within one iteration follow strict order."""
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        events = event_log.query_by_run(run_id)
        types = [e.event_type for e in events]

        # Find the indices
        idx_run_start = types.index(EventType.RUN_STARTED)
        idx_iter_start = types.index(EventType.RLM_ITERATION_STARTED)
        idx_lm_start = types.index(EventType.LM_CALL_STARTED)
        idx_lm_end = types.index(EventType.LM_CALL_FINISHED)
        idx_repl_start = types.index(EventType.REPL_EXEC_STARTED)
        idx_repl_end = types.index(EventType.REPL_EXEC_FINISHED)
        idx_iter_end = types.index(EventType.RLM_ITERATION_FINISHED)
        idx_run_end = types.index(EventType.RUN_FINISHED)

        assert idx_run_start < idx_iter_start < idx_lm_start < idx_lm_end
        assert idx_lm_end < idx_repl_start < idx_repl_end < idx_iter_end
        assert idx_iter_end < idx_run_end


class TestRecursiveExecutorLMCallMetadata:
    def test_lm_call_events_have_metadata(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        lm_started = event_log.query_by_type(run_id, EventType.LM_CALL_STARTED)
        lm_finished = event_log.query_by_type(run_id, EventType.LM_CALL_FINISHED)

        assert len(lm_started) >= 1
        assert lm_started[0].payload["call_type"] == "code_generation"

        assert len(lm_finished) >= 1
        assert "tokens_used" in lm_finished[0].payload
        assert "code_length" in lm_finished[0].payload
        assert "code_hash" in lm_finished[0].payload

    def test_repl_exec_events_have_metadata(self) -> None:
        event_log = SQLiteEventLog()
        provider = MockLMProvider(["FINAL = 'done'"])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        repl_finished = event_log.query_by_type(run_id, EventType.REPL_EXEC_FINISHED)
        assert len(repl_finished) >= 1
        payload = repl_finished[0].payload
        assert "success" in payload
        assert "has_final" in payload
        assert "variables" in payload


class TestRecursiveExecutorBudget:
    def test_budget_exceeded_stops_execution(self) -> None:
        """When budget is exceeded, outcome is BUDGET_EXCEEDED."""
        event_log = SQLiteEventLog()
        run_id = generate_run_id()

        budget_spec = BudgetSpec(
            max_tokens=10,
            max_tool_calls=100,
            max_time_seconds=60.0,
            max_recursion_depth=5,
        )
        budget_mgr = BudgetManager(budget_spec, event_log, run_id)

        # Provider returns code that won't set FINAL, burning tokens
        provider = MockLMProvider(["x = 1"])
        executor = RecursiveExecutor(
            event_log, provider, budget_manager=budget_mgr
        )

        result_id, result = executor.run("test", run_id=run_id)

        assert result is None
        events = event_log.query_by_run(run_id)
        run_finished = [e for e in events if e.event_type == EventType.RUN_FINISHED]
        assert len(run_finished) == 1
        assert run_finished[0].payload["outcome"] == "BUDGET_EXCEEDED"


class TestRecursiveExecutorSubLMQuery:
    def test_lm_query_in_repl(self) -> None:
        """Test that lm_query() works inside REPL code."""
        event_log = SQLiteEventLog()
        # First call: code generation that calls lm_query
        # Second call: the sub-query response
        # Third call: code that sets FINAL with the result
        provider = TrackingLMProvider([
            "result = lm_query('what is 2+2?')",  # code gen iteration 1
            "4",  # sub-query response
            "FINAL = result",  # code gen iteration 2
        ])
        executor = RecursiveExecutor(event_log, provider)

        run_id, result = executor.run("test sub-query")

        assert result == "4"

    def test_sub_lm_query_emits_events(self) -> None:
        """Sub LM queries should emit LMCallStarted/Finished events."""
        event_log = SQLiteEventLog()
        provider = TrackingLMProvider([
            "result = lm_query('query')",
            "answer",
            "FINAL = result",
        ])
        executor = RecursiveExecutor(event_log, provider)

        run_id, _ = executor.run("test")

        lm_calls = event_log.query_by_type(run_id, EventType.LM_CALL_STARTED)
        # Should have at least: code gen call 1 + sub_lm_query + code gen call 2
        code_gen_calls = [c for c in lm_calls if c.payload.get("call_type") == "code_generation"]
        sub_calls = [c for c in lm_calls if c.payload.get("call_type") == "sub_lm_query"]
        assert len(code_gen_calls) >= 2
        assert len(sub_calls) >= 1

    def test_recursion_depth_limit(self) -> None:
        """lm_query should respect max_recursion_depth."""
        event_log = SQLiteEventLog()
        config = RLMConfig(max_recursion_depth=0)
        # Code tries to call lm_query but depth=0 means no sub-calls allowed
        provider = MockLMProvider([
            "result = lm_query('test')",
            "FINAL = 'fallback'",
        ])
        executor = RecursiveExecutor(event_log, provider)

        run_id, result = executor.run("test", config=config)

        # First iteration should fail (lm_query raises RuntimeError at depth 0)
        # Second iteration sets FINAL
        events = event_log.query_by_run(run_id)
        repl_finished = [
            e for e in events if e.event_type == EventType.REPL_EXEC_FINISHED
        ]
        # First REPL exec should have failed
        assert repl_finished[0].payload["success"] is False


class TestRLMConfig:
    def test_defaults(self) -> None:
        config = RLMConfig()
        assert config.max_iterations == 100
        assert config.max_stdout_in_history == 500
        assert config.max_recursion_depth == 1
        assert "REPL" in config.system_prompt

    def test_custom_values(self) -> None:
        config = RLMConfig(
            system_prompt="Custom prompt",
            max_iterations=10,
            max_stdout_in_history=200,
            max_recursion_depth=3,
        )
        assert config.system_prompt == "Custom prompt"
        assert config.max_iterations == 10
