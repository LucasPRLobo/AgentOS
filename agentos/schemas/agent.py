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


class ClaudeCodeConfig(BaseModel):
    """Claude Code Tier 2 specific configuration."""

    permission_mode: str | None = Field(
        default=None,
        description="Claude Code permission mode: default, plan, auto, bypassPermissions",
    )
    append_system_prompt: str | None = Field(
        default=None,
        description="Additional system prompt appended to the agent's role",
    )
    mcp_config: list[str] = Field(
        default_factory=list,
        description="MCP server configuration JSON strings or file paths",
    )
    disabled_commands: list[str] = Field(
        default_factory=list,
        description="Slash commands to disable (e.g., 'commit', 'push')",
    )
    model: str | None = Field(
        default=None,
        description="Override model for this agent (e.g., claude-sonnet-4-6)",
    )
    max_turns: int | None = Field(
        default=None,
        description="Maximum conversation turns",
    )
    add_dirs: list[str] = Field(
        default_factory=list,
        description="Additional directories the agent can access beyond workspace",
    )


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
    claude_code: ClaudeCodeConfig = Field(
        default_factory=ClaudeCodeConfig,
        description="Claude Code specific configuration (Tier 2 only)",
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
