"""E2E tests for REEXECUTE replay mode (re-runs PURE tools)."""

from __future__ import annotations

from typing import Any

import pytest

from agentos.core.identifiers import generate_run_id
from agentos.observability.replay import ReplayEngine, ReplayMode
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import (
    BaseEvent,
    EventType,
    RunFinished,
    RunStarted,
    ToolCallFinished,
    ToolCallStarted,
)

pytestmark = [pytest.mark.e2e, pytest.mark.replay]


def _build_run_with_pure_tool(log: SQLiteEventLog, run_id: str) -> None:
    """Build a synthetic run with PURE tool calls that have input data for replay."""
    log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test"}))
    log.append(ToolCallStarted(
        run_id=run_id, seq=1,
        payload={
            "tool_name": "adder",
            "side_effect": "PURE",
            "input": {"a": 2, "b": 3},
        },
    ))
    log.append(ToolCallFinished(
        run_id=run_id, seq=2,
        payload={
            "tool_name": "adder",
            "success": True,
            "output": {"result": 5},
            "output_hash": "abc123",
        },
    ))
    log.append(ToolCallStarted(
        run_id=run_id, seq=3,
        payload={
            "tool_name": "writer",
            "side_effect": "WRITE",
            "input": {"path": "/tmp/test.txt"},
        },
    ))
    log.append(ToolCallFinished(
        run_id=run_id, seq=4,
        payload={
            "tool_name": "writer",
            "success": True,
            "output": {"written": True},
            "output_hash": "def456",
        },
    ))
    log.append(RunFinished(run_id=run_id, seq=5, payload={"outcome": "SUCCEEDED"}))


def _tool_executor(tool_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """Mock tool executor that re-computes PURE tools."""
    if tool_name == "adder":
        return {"result": input_data["a"] + input_data["b"]}
    raise ValueError(f"Unknown tool: {tool_name}")


class TestReexecutePure:
    """Verify REEXECUTE mode re-runs PURE tools and gets the same results."""

    def test_reexecute_reruns_pure_tool(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        _build_run_with_pure_tool(log, rid)

        engine = ReplayEngine(log)
        result = engine.replay(
            rid,
            mode=ReplayMode.REEXECUTE,
            tool_executor=_tool_executor,
        )

        # Find the reexecuted PURE tool output
        reexecuted = {
            seq: out for seq, out in result.tool_outputs.items()
            if out.get("reexecuted")
        }
        assert len(reexecuted) >= 1
        # The adder tool should have been reexecuted with same result
        for seq, out in reexecuted.items():
            assert out["output"]["result"] == 5
        log.close()

    def test_write_tools_not_reexecuted(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        _build_run_with_pure_tool(log, rid)

        engine = ReplayEngine(log)
        result = engine.replay(
            rid,
            mode=ReplayMode.REEXECUTE,
            tool_executor=_tool_executor,
        )

        # WRITE tool ("writer") should NOT be reexecuted
        for seq, out in result.tool_outputs.items():
            if out.get("tool_name") == "writer":
                assert not out.get("reexecuted", False), (
                    "WRITE tool was unexpectedly reexecuted"
                )
        log.close()

    def test_replay_result_succeeds(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        _build_run_with_pure_tool(log, rid)

        engine = ReplayEngine(log)
        result = engine.replay(
            rid,
            mode=ReplayMode.REEXECUTE,
            tool_executor=_tool_executor,
        )

        assert result.success is True
        log.close()
