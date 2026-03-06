"""Workflow definition schema — parsed from YAML."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.agent import AgentConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.channel import ChannelConfig
from agentos.schemas.memory import MemoryConfig
from agentos.schemas.spawn import AgentArchetype, SpawnPolicy
from agentos.schemas.task import TaskConfig
from agentos.schemas.team import TeamConfig


class WorkflowDefinition(BaseModel):
    """Complete workflow parsed from YAML."""

    name: str
    version: str = "1.0"
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
    teams: dict[str, TeamConfig] = Field(default_factory=dict)
    channels: dict[str, ChannelConfig] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    spawn_policy: SpawnPolicy | None = Field(
        default=None, description="Policy for dynamic agent spawning",
    )
    archetypes: dict[str, AgentArchetype] = Field(
        default_factory=dict, description="Agent archetypes for dynamic spawning",
    )
