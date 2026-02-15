"""Workflow definition schema — bridge between visual builder and DAG executor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.identifiers import generate_run_id
from agentos.schemas.budget import BudgetSpec


class AdvancedModelConfig(BaseModel):
    """Advanced LLM configuration for power users."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int | None = None
    few_shot_examples: list[dict[str, str]] = Field(default_factory=list)


class WorkflowNodeConfig(BaseModel):
    """Configuration for a single agent node in a workflow."""

    model: str
    system_prompt: str = ""
    persona_preset: str = Field(
        default="analytical",
        description="Personality preset: analytical, creative, formal, concise, friendly",
    )
    tools: list[str] = Field(default_factory=list)
    budget: BudgetSpec | None = None
    max_steps: int = Field(default=50, gt=0)
    advanced: AdvancedModelConfig | None = None


class WorkflowNode(BaseModel):
    """A node in the visual workflow graph."""

    id: str
    role: str = Field(description="Role template name or 'custom'")
    display_name: str
    position: dict[str, float] = Field(
        default_factory=lambda: {"x": 0, "y": 0},
        description="Canvas position {x, y}",
    )
    config: WorkflowNodeConfig


class DataContract(BaseModel):
    """Schema contract for data flowing between nodes."""

    output_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema that the source node's output must satisfy",
    )
    input_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema that the target node expects as input",
    )


class WorkflowEdge(BaseModel):
    """A directed connection between two nodes."""

    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    data_contract: DataContract | None = None


class WorkflowVariable(BaseModel):
    """A workflow-level input variable (user-supplied at run time)."""

    name: str
    type: str = "string"
    default: Any = None
    description: str = ""


class WorkflowDefinition(BaseModel):
    """Complete workflow definition — serializable to/from JSON.

    This is the canonical format used by:
    - The visual builder (frontend) for editing
    - The workflow store for persistence
    - The workflow compiler for conversion to an executable DAG
    """

    id: str = Field(default_factory=lambda: str(generate_run_id()))
    name: str
    description: str = ""
    version: str = "1.0.0"
    domain_pack: str = Field(
        default="",
        description="Domain pack to resolve tools from (empty = platform-only)",
    )
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge] = Field(default_factory=list)
    variables: list[WorkflowVariable] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    template_source: str | None = Field(
        default=None,
        description="Template ID this was cloned from",
    )
