"""Tests for the AgentRunner executor."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.permissions import PermissionsEngine
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.lm.acceptance import AcceptanceChecker, AcceptanceCriterion, AcceptanceResult
from agentos.lm.agent_config import AgentConfig
from agentos.lm.agent_runner import AgentOutcome, AgentRunner
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.tools.base import BaseTool, SideEffect
from agentos.tools.registry import ToolRegistry
from tests.conftest import MockLMProvider, assert_event_sequence, assert_has_event


# ── Test helpers ──────────────────────────────────────────────────


class _EchoInput(BaseModel):
    message: str


class _EchoOutput(BaseModel):
    echoed: str


class _EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _EchoInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _EchoOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, _EchoInput)
        return _EchoOutput(echoed=input_data.message)


class _FailTool(BaseTool):
    @property
    def name(self) -> str:
        return "fail_tool"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _EchoInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _EchoOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        raise RuntimeError("tool failed")


def _tool_call(tool: str, inp: dict[str, Any], reasoning: str = "") -> str:
    return json.dumps({"action": "tool_call", "tool": tool, "input": inp, "reasoning": reasoning})


def _finish(result: str = "Done.", reasoning: str = "") -> str:
    return json.dumps({"action": "finish", "result": result, "reasoning": reasoning})


def _make_registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _make_runner(
    responses: list[str],
    tools: list[BaseTool] | None = None,
    budget_spec: BudgetSpec | None = None,
    stop_checker: StopConditionChecker | None = None,
    permissions_engine: PermissionsEngine | None = None,
    acceptance_checker: AcceptanceChecker | None = None,
) -> tuple[AgentRunner, SQLiteEventLog, RunId, MockLMProvider]:
    event_log = SQLiteEventLog(":memory:")
    rid = generate_run_id()
    lm = MockLMProvider(responses)
    registry = _make_registry(*(tools or [_EchoTool()]))

    bm = None
    if budget_spec is not None:
        bm = BudgetManager(budget_spec, event_log, rid)

    runner = AgentRunner(
        event_log,
        lm,
        registry,
        budget_manager=bm,
        stop_checker=stop_checker,
        permissions_engine=permissions_engine,
        acceptance_checker=acceptance_checker,
    )
    return runner, event_log, rid, lm


# ── Tests ─────────────────────────────────────────────────────────


class TestAgentRunnerSingleStep:
    def test_finish_immediately(self) -> None:
        runner, event_log, rid, lm = _make_runner([_finish("all done")])
        result_rid, result = runner.run("Do nothing", run_id=rid)
        assert result_rid == rid
        assert result == "all done"
        events = event_log.query_by_run(rid)
        assert events[0].event_type == EventType.RUN_STARTED
        assert events[-1].event_type == EventType.RUN_FINISHED
        assert events[-1].payload["outcome"] == "SUCCEEDED"

    def test_tool_call_then_finish(self) -> None:
        responses = [
            _tool_call("echo", {"message": "hi"}),
            _finish("echoed hi"),
        ]
        runner, event_log, rid, lm = _make_runner(responses)
        _, result = runner.run("Echo hi", run_id=rid)
        assert result == "echoed hi"
        events = event_log.query_by_run(rid)
        # Verify key event types present
        assert_has_event(events, EventType.TOOL_CALL_STARTED, tool_name="echo")
        assert_has_event(events, EventType.TOOL_CALL_FINISHED, tool_name="echo", success=True)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="SUCCEEDED")


class TestAgentRunnerMultiStep:
    def test_multi_step_tool_calling(self) -> None:
        responses = [
            _tool_call("echo", {"message": "step1"}),
            _tool_call("echo", {"message": "step2"}),
            _finish("done after 2 calls"),
        ]
        runner, event_log, rid, _ = _make_runner(responses)
        _, result = runner.run("Multi step", run_id=rid)
        assert result == "done after 2 calls"
        tool_started = event_log.query_by_type(rid, EventType.TOOL_CALL_STARTED)
        assert len(tool_started) == 2


class TestAgentRunnerMaxSteps:
    def test_max_steps_outcome(self) -> None:
        # LM never finishes — always calls tool
        responses = [_tool_call("echo", {"message": "loop"})] * 10
        runner, event_log, rid, _ = _make_runner(responses)
        config = AgentConfig(max_steps=3)
        _, result = runner.run("Infinite loop", run_id=rid, config=config)
        assert result is None
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="MAX_STEPS")


class TestAgentRunnerParseErrors:
    def test_parse_error_recovery(self) -> None:
        responses = [
            "not json",
            _finish("recovered"),
        ]
        runner, event_log, rid, _ = _make_runner(responses)
        _, result = runner.run("Bad then good", run_id=rid)
        assert result == "recovered"

    def test_too_many_parse_errors(self) -> None:
        responses = ["bad1", "bad2", "bad3"]
        runner, event_log, rid, _ = _make_runner(responses)
        config = AgentConfig(max_consecutive_errors=3)
        _, result = runner.run("All bad", run_id=rid, config=config)
        assert result is None
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="TOO_MANY_ERRORS")


class TestAgentRunnerPermissions:
    def test_permission_denied_feedback(self) -> None:
        from agentos.governance.permissions import (
            PermissionPolicy,
            PermissionRule,
            PolicyAction,
        )

        event_log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        policy = PermissionPolicy(
            rules=[
                PermissionRule(
                    side_effect=SideEffect.WRITE,
                    action=PolicyAction.DENY,
                    reason="write denied",
                ),
            ],
            default_action=PolicyAction.DENY,
        )
        pe = PermissionsEngine(policy, event_log, rid)

        responses = [
            _tool_call("fail_tool", {"message": "test"}),
            _finish("gave up"),
        ]
        lm = MockLMProvider(responses)
        registry = _make_registry(_FailTool())
        runner = AgentRunner(
            event_log, lm, registry, permissions_engine=pe
        )
        _, result = runner.run("Try write", run_id=rid)
        assert result == "gave up"


class TestAgentRunnerBudget:
    def test_budget_exceeded_halts_run(self) -> None:
        # Budget allows only 1 tool call
        spec = BudgetSpec(
            max_tool_calls=1,
            max_tokens=100_000,
            max_time_seconds=60.0,
            max_recursion_depth=5,
        )
        responses = [
            _tool_call("echo", {"message": "a"}),
            _tool_call("echo", {"message": "b"}),
            _finish("done"),
        ]
        runner, event_log, rid, _ = _make_runner(responses, budget_spec=spec)
        _, result = runner.run("Budget test", run_id=rid)
        assert result is None
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="BUDGET_EXCEEDED")


class TestAgentRunnerStopConditions:
    def test_stop_condition_triggers(self) -> None:
        event_log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        sc = StopConditionChecker(event_log, rid, max_consecutive_failures=2)
        # Simulate consecutive failures by using a tool that fails
        responses = [
            _tool_call("fail_tool", {"message": "a"}),
            _tool_call("fail_tool", {"message": "b"}),
            _finish("should not reach"),
        ]
        lm = MockLMProvider(responses)
        registry = _make_registry(_FailTool())
        runner = AgentRunner(event_log, lm, registry, stop_checker=sc)
        _, result = runner.run("Stop test", run_id=rid)
        assert result is None
        events = event_log.query_by_run(rid)
        assert_has_event(events, EventType.RUN_FINISHED, outcome="STOPPED")


class TestAgentRunnerAcceptance:
    def test_acceptance_criteria_pass(self) -> None:
        class _PassCriterion(AcceptanceCriterion):
            @property
            def name(self) -> str:
                return "pass"

            def check(self, context: dict[str, Any]) -> AcceptanceResult:
                return AcceptanceResult(name="pass", passed=True, message="ok")

        checker = AcceptanceChecker([_PassCriterion()])
        runner, event_log, rid, _ = _make_runner(
            [_finish("done")], acceptance_checker=checker
        )
        _, result = runner.run("Test", run_id=rid)
        assert result == "done"

    def test_acceptance_criteria_fail_retries(self) -> None:
        call_count = [0]

        class _FailThenPass(AcceptanceCriterion):
            @property
            def name(self) -> str:
                return "conditional"

            def check(self, context: dict[str, Any]) -> AcceptanceResult:
                call_count[0] += 1
                passed = call_count[0] > 1
                return AcceptanceResult(
                    name="conditional",
                    passed=passed,
                    message="ok" if passed else "not yet",
                )

        checker = AcceptanceChecker([_FailThenPass()])
        responses = [
            _finish("first try"),
            _finish("second try"),
        ]
        runner, event_log, rid, _ = _make_runner(responses, acceptance_checker=checker)
        _, result = runner.run("Test", run_id=rid)
        assert result == "second try"


class TestAgentRunnerEventSequence:
    def test_full_event_sequence(self) -> None:
        responses = [
            _tool_call("echo", {"message": "hi"}),
            _finish("done"),
        ]
        runner, event_log, rid, _ = _make_runner(responses)
        runner.run("Event test", run_id=rid)
        events = event_log.query_by_run(rid)
        types = [e.event_type for e in events]

        # Verify ordering: RunStarted ... AgentStepStarted ... ToolCallStarted ...
        assert types[0] == EventType.RUN_STARTED
        assert types[-1] == EventType.RUN_FINISHED
        assert EventType.AGENT_STEP_STARTED in types
        assert EventType.AGENT_STEP_FINISHED in types
        assert EventType.LM_CALL_STARTED in types
        assert EventType.LM_CALL_FINISHED in types
        assert EventType.TOOL_CALL_STARTED in types
        assert EventType.TOOL_CALL_FINISHED in types

    def test_unknown_tool_gives_feedback(self) -> None:
        responses = [
            _tool_call("nonexistent", {"x": 1}),
            _finish("gave up"),
        ]
        runner, event_log, rid, _ = _make_runner(responses)
        _, result = runner.run("Unknown tool", run_id=rid)
        assert result == "gave up"
