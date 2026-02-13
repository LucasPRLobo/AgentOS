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
    BUDGET_EXCEEDED = "BudgetExceeded"
    POLICY_DECISION = "PolicyDecision"
    ARTIFACT_CREATED = "ArtifactCreated"
    STOP_CONDITION = "StopCondition"
    RLM_ITERATION_STARTED = "RLMIterationStarted"
    RLM_ITERATION_FINISHED = "RLMIterationFinished"
    LM_CALL_STARTED = "LMCallStarted"
    LM_CALL_FINISHED = "LMCallFinished"
    REPL_EXEC_STARTED = "REPLExecStarted"
    REPL_EXEC_FINISHED = "REPLExecFinished"
    AGENT_STEP_STARTED = "AgentStepStarted"
    AGENT_STEP_FINISHED = "AgentStepFinished"
    WORKSPACE_SNAPSHOT = "WorkspaceSnapshot"


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


class BudgetExceeded(BaseEvent):
    """Emitted when a budget limit is exceeded."""

    event_type: EventType = EventType.BUDGET_EXCEEDED


class ArtifactCreated(BaseEvent):
    """Emitted when a new artifact is produced."""

    event_type: EventType = EventType.ARTIFACT_CREATED


class StopCondition(BaseEvent):
    """Emitted when a stop condition is triggered."""

    event_type: EventType = EventType.STOP_CONDITION


class RLMIterationStarted(BaseEvent):
    """Emitted when an RLM iteration begins."""

    event_type: EventType = EventType.RLM_ITERATION_STARTED


class RLMIterationFinished(BaseEvent):
    """Emitted when an RLM iteration completes."""

    event_type: EventType = EventType.RLM_ITERATION_FINISHED


class LMCallStarted(BaseEvent):
    """Emitted when a language model call begins."""

    event_type: EventType = EventType.LM_CALL_STARTED


class LMCallFinished(BaseEvent):
    """Emitted when a language model call completes."""

    event_type: EventType = EventType.LM_CALL_FINISHED


class REPLExecStarted(BaseEvent):
    """Emitted when REPL code execution begins."""

    event_type: EventType = EventType.REPL_EXEC_STARTED


class REPLExecFinished(BaseEvent):
    """Emitted when REPL code execution completes."""

    event_type: EventType = EventType.REPL_EXEC_FINISHED


class AgentStepStarted(BaseEvent):
    """Emitted when an agent step begins."""

    event_type: EventType = EventType.AGENT_STEP_STARTED


class AgentStepFinished(BaseEvent):
    """Emitted when an agent step completes."""

    event_type: EventType = EventType.AGENT_STEP_FINISHED


class WorkspaceSnapshot(BaseEvent):
    """Emitted to capture workspace state at run start/end."""

    event_type: EventType = EventType.WORKSPACE_SNAPSHOT
