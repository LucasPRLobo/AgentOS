"""API request/response schemas for the AgentOS Platform server."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.runtime.domain_registry import ToolManifestEntry, WorkflowManifestEntry
from agentos.runtime.role_template import RoleTemplate
from agentos.schemas.session import AgentSlotConfig


# ── Requests ────────────────────────────────────────────────────────


class CreateSessionRequest(BaseModel):
    """Request body for POST /api/sessions."""

    domain_pack: str
    workflow: str
    agents: list[AgentSlotConfig]
    workspace_root: str
    task_description: str = ""
    max_parallel: int = 1


# ── Responses ───────────────────────────────────────────────────────


class SessionSummaryResponse(BaseModel):
    """Summary for session listings."""

    session_id: str
    state: str
    domain_pack: str
    workflow: str
    created_at: str
    agent_count: int


class SessionDetailResponse(BaseModel):
    """Detailed session info."""

    session_id: str
    state: str
    domain_pack: str
    workflow: str
    created_at: str
    agents: list[dict]
    event_count: int
    error: str | None = None


class DomainPackSummaryResponse(BaseModel):
    """Summary for pack listings."""

    name: str
    display_name: str
    description: str
    version: str
    tool_count: int
    role_count: int
    workflow_count: int


class DomainPackDetailResponse(BaseModel):
    """Full domain pack details."""

    name: str
    display_name: str
    description: str
    version: str
    tools: list[ToolManifestEntry]
    role_templates: list[RoleTemplate]
    workflows: list[WorkflowManifestEntry]


class EventResponse(BaseModel):
    """A single event from the event log."""

    run_id: str
    seq: int
    timestamp: str
    event_type: str
    payload: dict


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# ── Settings ───────────────────────────────────────────────────────


class UpdateSettingsRequest(BaseModel):
    """Request body for PUT /api/settings. All fields optional."""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str | None = None
    managed_proxy_url: str | None = None
    managed_proxy_key: str | None = None
    default_model: str | None = None
    workspace_dir: str | None = None
    workflows_dir: str | None = None
    google_oauth_token: str | None = None
    slack_bot_token: str | None = None


class SettingsResponse(BaseModel):
    """Platform settings (API keys masked)."""

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = ""
    managed_proxy_url: str | None = None
    managed_proxy_key: str | None = None
    default_model: str = ""
    workspace_dir: str = ""
    workflows_dir: str = ""
    google_oauth_token: str | None = None
    slack_bot_token: str | None = None


# ── Models ─────────────────────────────────────────────────────────


class ModelListEntry(BaseModel):
    """A single model in the available models list."""

    name: str
    provider: str
    display_name: str
    available: bool = True


class ModelCapabilitiesResponse(BaseModel):
    """Capabilities for a specific model."""

    context_window: int = 0
    max_output_tokens: int = 0
    supports_structured_output: bool = False
    supports_tool_use: bool = False
    supports_vision: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    provider: str = ""
    display_name: str = ""


# ── Workflows ──────────────────────────────────────────────────────


class WorkflowSummaryResponse(BaseModel):
    """Summary for workflow listings."""

    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    node_count: int = 0
    edge_count: int = 0
    domain_pack: str = ""
    created_at: str = ""
    updated_at: str = ""
    template_source: str | None = None


class RunWorkflowRequest(BaseModel):
    """Request body for POST /api/workflows/:id/run."""

    task_description: str = ""
    max_parallel: int = 1


class RunWorkflowResponse(BaseModel):
    """Response for POST /api/workflows/:id/run."""

    session_id: str
    state: str


class WorkflowValidationResponse(BaseModel):
    """Response for POST /api/workflows/:id/validate."""

    valid: bool
    issues: list[dict] = Field(default_factory=list)


# ── Integrations ──────────────────────────────────────────────────


class IntegrationStatusResponse(BaseModel):
    """Status of a single integration."""

    name: str
    connected: bool
    display_name: str = ""


class ConnectSlackRequest(BaseModel):
    """Request body for POST /api/integrations/slack/connect."""

    bot_token: str
