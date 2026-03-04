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

    # Collaborative workflows (V1.5)
    BRANCH_EVALUATED = "branch.evaluated"
    TASK_RETRIED = "task.retried"
    REVISION_FEEDBACK = "revision.feedback"
    MESSAGE_SENT = "message.sent"
    MESSAGE_RECEIVED = "message.received"

    # Channels (V2)
    CHANNEL_CREATED = "channel.created"
    CHANNEL_CLOSED = "channel.closed"

    # Sandbox (V2)
    SANDBOX_CREATED = "sandbox.created"
    SANDBOX_DESTROYED = "sandbox.destroyed"
    SANDBOX_VIOLATION = "sandbox.violation"

    # Safety (V2)
    SAFETY_SCORE_CALCULATED = "safety.score_calculated"

    # Policy (V2)
    POLICY_VIOLATION_DETECTED = "policy.violation_detected"
    POLICY_RELOADED = "policy.reloaded"

    # Auth (V2)
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"

    # Memory (V2)
    MEMORY_EXTRACTED = "memory.extracted"
    MEMORY_INJECTED = "memory.injected"

    # Benchmark (V2+)
    BENCHMARK_STARTED = "benchmark.started"
    BENCHMARK_COMPLETED = "benchmark.completed"

    # Dynamic DAG (V3)
    TASK_ADDED = "task.added"
    TASK_WIRED = "task.wired"
    AGENT_SPAWN_REQUESTED = "agent.spawn_requested"
    AGENT_SPAWN_APPROVED = "agent.spawn_approved"

    # Knowledge (V3)
    KNOWLEDGE_ENTITY_ADDED = "knowledge.entity_added"
    KNOWLEDGE_RELATIONSHIP_ADDED = "knowledge.relationship_added"

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
