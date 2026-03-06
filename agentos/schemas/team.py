"""Team configuration schema — groups agents under a manager."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec


class TeamConfig(BaseModel):
    """Configuration for a named team of agents under a manager."""

    manager: str = Field(description="Agent name that manages this team")
    members: list[str] = Field(default_factory=list, description="Agent names in the team")
    description: str = Field(default="", description="What this team does (injected into manager context)")
    channel: str | None = Field(default=None, description="Auto-created team channel (defaults to team_{name})")
    human_input: bool = Field(default=False, description="Whether manager accepts human directives via gates")
    budget: BudgetSpec = Field(default_factory=BudgetSpec, description="Aggregate budget for the entire team")
    workspace: str = Field(default="", description="Team workspace name (defaults to team_{name})")
