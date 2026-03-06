"""Agent configuration schemas."""

from __future__ import annotations

from enum import IntEnum

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.sandbox import SandboxConfig, SandboxLevel


class AdapterTier(IntEnum):
    TIER1 = 1  # Fully controlled
    TIER2 = 2  # Semi-controlled
    TIER3 = 3  # Best-effort


class AgentConfig(BaseModel):
    """Configuration for a single agent."""

    adapter: str = Field(default="tier1", description="tier1 | tier2_claude_code | tier2_aider | manager")
    model: str = Field(default="claude-sonnet-4-6")
    role: str = Field(default="", description="System prompt / role description")
    tools: list[str] = Field(default_factory=list, description="Tool allowlist")
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    capabilities: list[CapabilityGrant] = Field(
        default_factory=list,
        description="Fine-grained capability grants for this agent",
    )
    sandbox: SandboxConfig | None = Field(
        default=None,
        description="Sandbox isolation configuration for this agent",
    )
    team: str | None = Field(
        default=None,
        description="Team name this agent belongs to (auto-populated by team expander)",
    )

    def to_capability_policy(self, agent_id: str) -> CapabilityPolicy:
        """Convert agent capabilities to a CapabilityPolicy."""
        sandbox_level = SandboxLevel.NONE
        if self.sandbox is not None:
            sandbox_level = self.sandbox.level
        return CapabilityPolicy(
            agent_id=agent_id,
            grants=list(self.capabilities),
            deny_by_default=len(self.capabilities) > 0,
            sandbox=sandbox_level,
        )
