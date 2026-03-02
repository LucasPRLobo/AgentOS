"""Event log schema v0.1 — event envelope, event types, and SQLite DDL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventType(StrEnum):
    """All V1 event types. Grouped by subsystem."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"

    # Task lifecycle
    TASK_STATE_CHANGED = "task.state_changed"
    TASK_OUTPUT_PRODUCED = "task.output_produced"

    # Agent lifecycle
    AGENT_SPAWNED = "agent.spawned"
    AGENT_TERMINATED = "agent.terminated"

    # Gates
    GATE_WAITING = "gate.waiting"
    GATE_RESOLVED = "gate.resolved"

    # Budget
    BUDGET_CONSUMED = "budget.consumed"
    BUDGET_EXCEEDED = "budget.exceeded"

    # Workspace / files
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"

    # Security
    CAPABILITY_GRANTED = "capability.granted"
    CAPABILITY_DENIED = "capability.denied"

    # Errors
    ERROR_OCCURRED = "error.occurred"


class Event(BaseModel):
    """Immutable event in the append-only log.

    Every event has a common envelope. Type-specific data lives in `payload`.
    The `metadata` field provides extensibility without schema changes.
    """

    event_id: str = Field(default_factory=_uuid, description="Unique event ID (UUID)")
    event_type: EventType
    workflow_id: str = Field(description="Workflow this event belongs to")
    seq: int = Field(ge=0, description="Monotonic sequence within the workflow")
    timestamp: datetime = Field(default_factory=_utc_now)
    schema_version: str = Field(default="0.1")
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible key-value pairs for future features",
    )


EVENT_TABLE_DDL = """\
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    workflow_id  TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    timestamp    TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '0.1',
    payload      TEXT NOT NULL DEFAULT '{}',
    metadata     TEXT NOT NULL DEFAULT '{}',
    UNIQUE(workflow_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_events_workflow ON events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""
