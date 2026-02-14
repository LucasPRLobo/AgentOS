"""Role template — reusable agent role definitions for multi-agent sessions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec


class RoleTemplate(BaseModel):
    """A reusable agent role definition.

    Role templates bundle a system prompt, tool set, budget profile,
    and suggested LLM model into a named configuration. Sessions
    reference roles by name and can override individual fields.
    """

    name: str = Field(description="Unique role identifier (e.g. 'planner', 'reviewer')")
    display_name: str = Field(description="Human-readable name (e.g. 'Planning Agent')")
    description: str = Field(description="What this role does")
    system_prompt: str = Field(description="Role-specific system prompt for the LLM")
    tool_names: list[str] = Field(
        default_factory=list,
        description="Names of tools this role needs from the domain pack",
    )
    suggested_model: str = Field(
        default="llama3.1:latest",
        description="Recommended LLM model identifier",
    )
    budget_profile: BudgetSpec = Field(
        default_factory=lambda: BudgetSpec(
            max_tokens=50_000,
            max_tool_calls=20,
            max_time_seconds=300.0,
            max_recursion_depth=1,
        ),
        description="Recommended budget limits for this role",
    )
    max_steps: int = Field(default=50, gt=0, description="Maximum agent steps")
    max_instances: int = Field(
        default=1,
        gt=0,
        description="Default number of parallel instances for this role",
    )
