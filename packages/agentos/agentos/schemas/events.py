"""Event schemas for the append-only event log."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.identifiers import RunId


class EventType(StrEnum):
    """All recognized event types."""

    RUN_STARTED = "RunStarted"
    RUN_FINISHED = "RunFinished"
    TASK_STARTED = "TaskStarted"
    TASK_FINISHED = "TaskFinished"
    TOOL_CALL_STARTED = "ToolCallStarted"
    TOOL_CALL_FINISHED = "ToolCallFinished"
    BUDGET_UPDATED = "BudgetUpdated"
    POLICY_DECISION = "PolicyDecision"
    ARTIFACT_CREATED = "ArtifactCreated"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BaseEvent(BaseModel):
    """Base schema for all events in the event log."""

    run_id: RunId
    seq: int = Field(ge=0, description="Sequence number within the run")
    timestamp: datetime = Field(default_factory=_utc_now)
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)


class RunStarted(BaseEvent):
    """Emitted when a run begins."""

    event_type: EventType = EventType.RUN_STARTED


class RunFinished(BaseEvent):
    """Emitted when a run completes (success or failure)."""

    event_type: EventType = EventType.RUN_FINISHED


class TaskStarted(BaseEvent):
    """Emitted when a task transitions to RUNNING."""

    event_type: EventType = EventType.TASK_STARTED


class TaskFinished(BaseEvent):
    """Emitted when a task transitions to SUCCEEDED or FAILED."""

    event_type: EventType = EventType.TASK_FINISHED


class ToolCallStarted(BaseEvent):
    """Emitted when a tool invocation begins."""

    event_type: EventType = EventType.TOOL_CALL_STARTED


class ToolCallFinished(BaseEvent):
    """Emitted when a tool invocation completes."""

    event_type: EventType = EventType.TOOL_CALL_FINISHED


class BudgetUpdated(BaseEvent):
    """Emitted when budget counters change."""

    event_type: EventType = EventType.BUDGET_UPDATED


class PolicyDecision(BaseEvent):
    """Emitted when a governance policy makes a decision."""

    event_type: EventType = EventType.POLICY_DECISION


class ArtifactCreated(BaseEvent):
    """Emitted when a new artifact is produced."""

    event_type: EventType = EventType.ARTIFACT_CREATED
