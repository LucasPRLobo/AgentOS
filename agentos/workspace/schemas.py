"""Workspace runtime schemas — configuration, backlog tasks, context summaries.

See docs/WORKSPACE_RUNTIME_DESIGN.md for design rationale.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec


def _uuid() -> str:
    return str(uuid.uuid4())


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Team and workspace configuration
# ---------------------------------------------------------------------------

class TeamMode(StrEnum):
    LOCKED = "locked"
    SUGGEST = "suggest"
    AUTO_MINOR = "auto_minor"
    AUTO_FULL = "auto_full"


class ParticipantType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class ParticipantRole(StrEnum):
    LEAD = "lead"
    WORKER = "worker"
    REVIEWER = "reviewer"
    OBSERVER = "observer"


class WorkspaceParticipant(BaseModel):
    name: str
    type: ParticipantType = ParticipantType.AGENT
    roles: list[ParticipantRole] = Field(default_factory=lambda: [ParticipantRole.WORKER])
    specialization: str = ""
    adapter: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    budget: BudgetSpec | None = None


class CoordinatorConfig(BaseModel):
    enabled: bool = True
    type: ParticipantType = ParticipantType.AGENT
    model: str = "opus"
    authority: TeamMode = TeamMode.SUGGEST
    auto_decompose: bool = True
    replan_interval: int = 0


class WorkspaceConfig(BaseModel):
    name: str
    goal: str
    description: str = ""
    team_mode: TeamMode = TeamMode.SUGGEST
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    coordinator: CoordinatorConfig = Field(default_factory=CoordinatorConfig)
    team: list[WorkspaceParticipant] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    persist: bool = True


# ---------------------------------------------------------------------------
# Backlog task
# ---------------------------------------------------------------------------

class BacklogTaskStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    REVISION_NEEDED = "revision_needed"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class BacklogTask(BaseModel):
    task_id: str = Field(default_factory=_uuid)
    title: str
    description: str = ""
    created_by: str = ""

    # Assignment
    assigned_to: str | None = None
    suggested_for: str | None = None
    required_role: str | None = None

    # Status
    status: BacklogTaskStatus = Field(default=BacklogTaskStatus.OPEN)

    # Dependencies
    depends_on: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)

    # Acceptance
    acceptance_criteria: list[str] = Field(default_factory=list)

    # Output
    output: dict[str, Any] | None = None

    # Governance
    budget: BudgetSpec | None = None
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    computed_priority: float | None = None
    estimated_minutes: int | None = None
    model_tier: Literal["haiku", "sonnet", "opus"] | None = None

    # Chaining
    next_task: dict[str, Any] | None = None

    # Tracking
    created_at: str = Field(default_factory=_utc_now_iso)
    claimed_at: str | None = None
    completed_at: str | None = None
    review_count: int = 0
    stall_count: int = 0


# ---------------------------------------------------------------------------
# Context summaries
# ---------------------------------------------------------------------------

class AgentContextSummary(BaseModel):
    """Anchored iterative summary — Factory 4-field pattern."""

    agent_id: str
    intent: str = ""
    changes_made: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    confidence: list[str] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    entity_references: list[str] = Field(default_factory=list)
    error_log: list[str] = Field(default_factory=list)

    tasks_completed: list[str] = Field(default_factory=list)
    last_active: str = Field(default_factory=_utc_now_iso)
    summary_version: int = 0


class WorkspaceContextSummary(BaseModel):
    """Workspace-level summary maintained by the coordinator."""

    goal: str = ""
    current_status: str = ""
    intent: str = ""
    key_decisions: list[str] = Field(default_factory=list)
    key_artifacts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    tasks_completed: int = 0
    tasks_remaining: int = 0
    budget_consumed_pct: float = 0.0
    team_notes: str = ""

    facts: list[str] = Field(default_factory=list)
    educated_guesses: list[str] = Field(default_factory=list)
    current_plan: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspace state
# ---------------------------------------------------------------------------

class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class WorkspaceState(BaseModel):
    workspace_id: str = Field(default_factory=_uuid)
    config: WorkspaceConfig
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    created_at: str = Field(default_factory=_utc_now_iso)
    last_active: str = Field(default_factory=_utc_now_iso)


# ---------------------------------------------------------------------------
# Activation context (assembled by runtime for each agent activation)
# ---------------------------------------------------------------------------

class ActivationContext(BaseModel):
    agent_id: str
    role: str = ""
    specialization: str = ""
    task: BacklogTask
    predecessor_outputs: list[dict[str, Any]] = Field(default_factory=list)
    board_state_compact: str = ""
    pending_messages: list[dict[str, Any]] = Field(default_factory=list)
    agent_summary: AgentContextSummary | None = None
    workspace_summary: WorkspaceContextSummary | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    last_seen_board_version: int | None = None
    last_seen_summary_version: int | None = None


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

class CompletionResult(BaseModel):
    complete: bool = False
    reason: str = ""
    layer: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""
