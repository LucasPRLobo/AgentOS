"""Agent configuration schemas."""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec
from agentos.schemas.capability import CapabilityGrant


class AdapterTier(IntEnum):
    TIER1 = 1  # Fully controlled
    TIER2 = 2  # Semi-controlled
    TIER3 = 3  # Best-effort


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    adapter: str = Field(default="tier1", description="tier1 | tier2_claude_code")
    model: str = Field(default="claude-sonnet-4-6")
    role: str = Field(default="", description="System prompt / role description")
    tools: list[str] = Field(default_factory=list, description="Tool allowlist")
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    capabilities: list[CapabilityGrant] = Field(
        default_factory=list,
        description="Fine-grained capability grants for this agent",
    )
