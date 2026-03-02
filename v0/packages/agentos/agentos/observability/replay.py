"""Replay engine — reconstruct and re-execute runs from the event log."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import BaseEvent, EventType

# Callback: (tool_name, input_data) -> output_data
ToolExecutorCallback = Callable[[str, dict[str, Any]], dict[str, Any]]


class ReplayMode(StrEnum):
    """How tool calls are handled during replay."""

    STRICT = "STRICT"
    """Use recorded outputs from events — no re-execution."""

    REEXECUTE = "REEXECUTE"
    """Re-execute deterministic (PURE) tools, mock others from events."""


class ReplayResult:
    """Result of replaying a run."""

    def __init__(
        self,
        run_id: RunId,
        events: list[BaseEvent],
        tool_outputs: dict[int, dict[str, Any]],
        *,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.events = events
        self.tool_outputs = tool_outputs
        self.success = success
        self.error = error

    @property
    def task_events(self) -> list[BaseEvent]:
        return [
            e
            for e in self.events
            if e.event_type in (EventType.TASK_STARTED, EventType.TASK_FINISHED)
        ]

    @property
    def tool_call_events(self) -> list[BaseEvent]:
        return [
            e
            for e in self.events
            if e.event_type
            in (EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_FINISHED)
        ]


class RunComparison:
    """Result of comparing two runs."""

    def __init__(
        self,
        run_id_a: RunId,
        run_id_b: RunId,
        events_a_count: int,
        events_b_count: int,
        same_structure: bool,
        event_types_a: list[EventType],
        event_types_b: list[EventType],
    ) -> None:
        self.run_id_a = run_id_a
        self.run_id_b = run_id_b
        self.events_a_count = events_a_count
        self.events_b_count = events_b_count
        self.same_structure = same_structure
        self.event_types_a = event_types_a
        self.event_types_b = event_types_b


class ReplayEngine:
    """Replays a run from the event log.

    In STRICT mode, all tool outputs are taken from recorded ToolCallFinished
    events. In REEXECUTE mode, PURE tools can be re-executed using a provided
    tool executor callback.
    """

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def replay(
        self,
        run_id: RunId,
        *,
        mode: ReplayMode = ReplayMode.STRICT,
        tool_executor: ToolExecutorCallback | None = None,
    ) -> ReplayResult:
        """Replay a run from the event log.

        Args:
            run_id: The run to replay.
            mode: STRICT (mock all) or REEXECUTE (re-run PURE tools).
            tool_executor: Callback for re-executing tools in REEXECUTE mode.
                Signature: (tool_name, input_payload) -> output_payload.

        Returns:
            ReplayResult with the reconstructed event stream and tool outputs.
        """
        events = self._event_log.replay(run_id)
        if not events:
            return ReplayResult(
                run_id=run_id,
                events=[],
                tool_outputs={},
                success=False,
                error=f"No events found for run {run_id}",
            )

        tool_outputs: dict[int, dict[str, Any]] = {}

        # Extract tool call outputs from the event stream
        for event in events:
            if event.event_type == EventType.TOOL_CALL_FINISHED:
                # Don't overwrite if already populated by re-execution
                if event.seq not in tool_outputs:
                    tool_outputs[event.seq] = event.payload

            if (
                mode == ReplayMode.REEXECUTE
                and event.event_type == EventType.TOOL_CALL_STARTED
                and tool_executor is not None
            ):
                payload = event.payload
                side_effect = payload.get("side_effect", "")
                if side_effect == "PURE":
                    tool_name = payload.get("tool_name", "")
                    input_data = payload.get("input", {})
                    try:
                        output = tool_executor(tool_name, input_data)
                        # Find the corresponding ToolCallFinished and override
                        for future_event in events:
                            if (
                                future_event.event_type
                                == EventType.TOOL_CALL_FINISHED
                                and future_event.seq > event.seq
                                and future_event.payload.get("tool_name")
                                == tool_name
                            ):
                                tool_outputs[future_event.seq] = {
                                    **future_event.payload,
                                    "output": output,
                                    "reexecuted": True,
                                }
                                break
                    except Exception as exc:
                        return ReplayResult(
                            run_id=run_id,
                            events=events,
                            tool_outputs=tool_outputs,
                            success=False,
                            error=f"Re-execution of '{tool_name}' failed: {exc}",
                        )

        # Check if the run completed successfully
        run_finished = [
            e for e in events if e.event_type == EventType.RUN_FINISHED
        ]
        success = bool(
            run_finished and run_finished[-1].payload.get("outcome") == "SUCCEEDED"
        )

        return ReplayResult(
            run_id=run_id,
            events=events,
            tool_outputs=tool_outputs,
            success=success,
        )

    def compare_runs(
        self, run_id_a: RunId, run_id_b: RunId
    ) -> RunComparison:
        """Compare two runs by their event streams."""
        events_a = self._event_log.replay(run_id_a)
        events_b = self._event_log.replay(run_id_b)

        types_a = [e.event_type for e in events_a]
        types_b = [e.event_type for e in events_b]

        return RunComparison(
            run_id_a=run_id_a,
            run_id_b=run_id_b,
            events_a_count=len(events_a),
            events_b_count=len(events_b),
            same_structure=types_a == types_b,
            event_types_a=types_a,
            event_types_b=types_b,
        )
