"""Workflow definition schema — parsed from YAML."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.agent import AgentConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import TaskConfig


class WorkflowDefinition(BaseModel):
    """Complete workflow parsed from YAML."""

    name: str
    version: str = "1.0"
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
