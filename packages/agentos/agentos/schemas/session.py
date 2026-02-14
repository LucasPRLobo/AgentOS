"""Session configuration schemas for multi-agent sessions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.core.identifiers import generate_run_id
from agentos.schemas.budget import BudgetSpec


class AgentSlotConfig(BaseModel):
    """Configuration for one agent slot in a session.

    An agent slot represents one or more instances of a role in the team.
    """

    role: str = Field(description="Role template name from the domain pack")
    model: str = Field(description="LLM model identifier (e.g. 'llama3.1:latest')")
    count: int = Field(default=1, gt=0, description="Number of instances of this role")
    budget_override: BudgetSpec | None = Field(
        default=None,
        description="Override the role's default budget profile",
    )
    system_prompt_override: str | None = Field(
        default=None,
        description="Override the role's default system prompt",
    )


class SessionConfig(BaseModel):
    """Full configuration for a multi-agent session."""

    session_id: str = Field(
        default_factory=generate_run_id,
        description="Unique session identifier",
    )
    domain_pack: str = Field(description="Domain pack name (e.g. 'labos', 'codeos')")
    workflow: str = Field(description="Workflow name from the domain pack")
    agents: list[AgentSlotConfig] = Field(
        description="Agent team configuration — one entry per role slot",
    )
    workspace_root: str = Field(description="Shared workspace directory for all agents")
    max_parallel: int = Field(
        default=1,
        gt=0,
        description="Maximum parallel DAG tasks",
    )
    task_description: str = Field(
        default="",
        description="Top-level task description / objective for the session",
    )
