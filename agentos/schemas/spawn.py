"""Dynamic team composition schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SpawnStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROVISIONED = "provisioned"


class SpawnRequest(BaseModel):
    """Request to spawn a new agent at runtime."""

    request_id: str
    requesting_agent: str
    archetype: str = Field(description="Template name for the new agent")
    reason: str = Field(description="Why this agent is needed")
    task_description: str = Field(default="", description="What the new agent should do")
    status: SpawnStatus = SpawnStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class SpawnPolicy(BaseModel):
    """Policy controlling dynamic agent spawning."""

    allow_spawn: bool = Field(default=False)
    require_approval: bool = Field(default=True)
    max_spawns_per_workflow: int = Field(default=5, ge=0)
    allowed_archetypes: list[str] = Field(default_factory=list)


class AgentArchetype(BaseModel):
    """Template for spawning agents."""

    name: str
    adapter: str = Field(default="tier1")
    model: str = Field(default="claude-sonnet-4-20250514")
    role: str = Field(default="")
    default_tools: list[str] = Field(default_factory=list)
