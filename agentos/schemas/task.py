"""Task output protocol v0.1 — structured output for inter-agent handoffs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EdgeCondition(BaseModel):
    """Conditional outgoing edge — evaluated against predecessor output."""

    target: str = Field(description="Task name to conditionally activate")
    expression: str = Field(description="Python expression evaluated against task output")


class RetryPolicy(BaseModel):
    """Revision loop configuration for a task."""

    max_retries: int = Field(default=2, ge=1, le=10)
    on: str = Field(default="gate_rejected", description="gate_rejected | validation_failed")


class TaskConfig(BaseModel):
    """A single task (node) in the workflow DAG."""

    name: str
    agent: str | None = None
    type: str = "agent_task"  # agent_task | approval_gate | input_gate | consultation
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    workspace: str = "shared"
    prompt: str = ""  # Gate prompt for approval/input gates
    conditions: list[EdgeCondition] = Field(default_factory=list)
    retry_policy: RetryPolicy | None = None
    consult_agent: str | None = None
    consult_question: str | None = None
    publishes_to: list[str] = Field(default_factory=list, description="Channels this task publishes to")
    subscribes_to: list[str] = Field(default_factory=list, description="Channels this task subscribes to")


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING = "waiting"  # Blocked on gate or input
    SKIPPED = "skipped"  # Conditionally deactivated


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    """A single finding produced by an agent."""

    finding: str = Field(description="What was found or concluded")
    confidence: Confidence = Field(description="Agent's confidence in this finding")
    sources: list[str] = Field(
        default_factory=list, description="URLs, file paths, or references"
    )


class FileReference(BaseModel):
    """A file produced or modified by the task."""

    path: str = Field(description="Path relative to workspace root")
    description: str = Field(description="What this file contains or why it was created")
    role: str = Field(default="primary", description="primary | supporting | log")


class TaskMetrics(BaseModel):
    """Resource consumption metrics for a completed task."""

    tokens_consumed: int = 0
    api_calls_made: int = 0
    execution_time_seconds: float = 0.0
    estimated_cost_usd: float = 0.0


class TaskOutput(BaseModel):
    """Structured output manifest produced by every task.

    Tier 1: enforced via JSON mode / tool use.
    Tier 2: agent instructed to write this as manifest.json; validated post-hoc.
    """

    schema_version: str = Field(default="0.1", description="Output schema version")
    task_id: str
    agent_id: str
    status: TaskStatus
    summary: str = Field(description="1-3 sentence summary of what was accomplished")
    key_findings: list[Finding] = Field(default_factory=list)
    files_produced: list[FileReference] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="Unresolved questions for downstream agents or human review",
    )
    metrics: TaskMetrics | None = None
    iteration: int = Field(default=1, description="Retry iteration count")
    revision_feedback: str | None = Field(default=None, description="Feedback from reviewer on retry")
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
