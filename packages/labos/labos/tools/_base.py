"""Bridge between LabOS tools and the AgentOS event log."""

from __future__ import annotations

from pydantic import BaseModel

from agentos.core.identifiers import RunId
from agentos.integrity.hashing import hash_dict
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import ToolCallFinished, ToolCallStarted
from agentos.tools.base import BaseTool


class _SeqCounter:
    """Mutable sequence counter for event ordering."""

    __slots__ = ("value",)

    def __init__(self, start: int = 0) -> None:
        self.value = start

    def next(self) -> int:
        v = self.value
        self.value += 1
        return v


def execute_with_events(
    tool: BaseTool,
    input_data: BaseModel,
    event_log: EventLog,
    run_id: RunId,
    seq_counter: _SeqCounter,
) -> BaseModel:
    """Execute a tool and emit ToolCallStarted/Finished events around it."""
    input_hash = hash_dict(input_data.model_dump())

    event_log.append(
        ToolCallStarted(
            run_id=run_id,
            seq=seq_counter.next(),
            payload={
                "tool_name": tool.name,
                "tool_version": tool.version,
                "input_hash": input_hash,
                "side_effect": tool.side_effect.value,
            },
        )
    )

    try:
        output = tool.execute(input_data)
        output_hash = hash_dict(output.model_dump())

        event_log.append(
            ToolCallFinished(
                run_id=run_id,
                seq=seq_counter.next(),
                payload={
                    "tool_name": tool.name,
                    "success": True,
                    "output_hash": output_hash,
                },
            )
        )
        return output
    except Exception as exc:
        event_log.append(
            ToolCallFinished(
                run_id=run_id,
                seq=seq_counter.next(),
                payload={
                    "tool_name": tool.name,
                    "success": False,
                    "error": str(exc),
                },
            )
        )
        raise
