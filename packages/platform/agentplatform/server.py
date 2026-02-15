"""FastAPI server for the AgentOS Platform."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import asdict
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agentos.lm import model_registry
from agentos.lm.provider import BaseLMProvider, ModelCapabilities
from agentos.runtime.domain_registry import DomainRegistry
from agentos.schemas.session import AgentSlotConfig, SessionConfig
from agentos.schemas.workflow import WorkflowDefinition

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.api_schemas import (
    ConnectSlackRequest,
    CreateSessionRequest,
    DomainPackDetailResponse,
    DomainPackSummaryResponse,
    EventResponse,
    IntegrationStatusResponse,
    ModelCapabilitiesResponse,
    ModelListEntry,
    RunWorkflowRequest,
    RunWorkflowResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
    SettingsResponse,
    UpdateSettingsRequest,
    WorkflowSummaryResponse,
    WorkflowValidationResponse,
)
from agentplatform.event_stream import EventStreamer
from agentplatform.orchestrator import SessionOrchestrator
from agentplatform.settings import PlatformSettings, SettingsManager
from agentplatform.workflow_store import WorkflowStore

logger = logging.getLogger(__name__)


def _make_provider_factory(
    settings: PlatformSettings,
) -> Callable[[str], BaseLMProvider]:
    """Create a provider factory that routes model names to the correct backend.

    Routing logic:
    - ``gpt-*``, ``o1*``, ``o3*`` → OpenAI (requires API key)
    - ``claude-*`` → Anthropic (requires API key)
    - Managed proxy URL configured → ManagedProxyProvider (fallback)
    - Everything else → Ollama (local)
    """

    def factory(model_name: str) -> BaseLMProvider:
        # OpenAI models
        if model_name.startswith(("gpt-", "o1", "o3")):
            if not settings.has_openai():
                raise RuntimeError(
                    f"OpenAI API key required for model '{model_name}'. "
                    "Configure it via PUT /api/settings."
                )
            from agentos.lm.providers.openai import OpenAIProvider

            return OpenAIProvider(model=model_name, api_key=settings.openai_api_key)

        # Anthropic models
        if model_name.startswith("claude-"):
            if not settings.has_anthropic():
                raise RuntimeError(
                    f"Anthropic API key required for model '{model_name}'. "
                    "Configure it via PUT /api/settings."
                )
            from agentos.lm.providers.anthropic import AnthropicProvider

            return AnthropicProvider(model=model_name, api_key=settings.anthropic_api_key)

        # Managed proxy (if configured and model not matched above)
        if settings.has_managed():
            from agentos.lm.providers.managed import ManagedProxyProvider

            return ManagedProxyProvider(
                model=model_name,
                proxy_url=settings.managed_proxy_url,  # type: ignore[arg-type]
                proxy_key=settings.managed_proxy_key,
            )

        # Default: Ollama (local models)
        try:
            from labos.providers.ollama import OllamaProvider

            return OllamaProvider(model=model_name, base_url=settings.ollama_base_url)
        except ImportError:
            raise RuntimeError(
                f"No provider available for model '{model_name}'. "
                "Install labos for Ollama support, or configure an API key."
            )

    return factory


def _fetch_ollama_models(base_url: str) -> list[dict[str, str]]:
    """Fetch available models from a local Ollama instance."""
    try:
        url = f"{base_url.rstrip('/')}/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        return [
            {"name": m["name"], "size": str(m.get("size", ""))}
            for m in data.get("models", [])
        ]
    except Exception:
        return []


def create_app(
    *,
    lm_provider: BaseLMProvider | None = None,
    lm_provider_factory: Callable[[str], BaseLMProvider] | None = None,
    domain_registry: DomainRegistry | None = None,
    settings_manager: SettingsManager | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lm_provider: Default LM provider for all sessions (single model).
        lm_provider_factory: Factory model_name → provider (multi-model).
            If neither is given, builds a settings-based routing factory.
        domain_registry: Pre-configured registry (builtins registered if None).
        settings_manager: Settings manager instance (uses default if None).
    """
    app = FastAPI(title="AgentOS Platform", version="0.1.0")

    # Allow CORS for local development (Vite dev server on :5173)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize settings
    sm = settings_manager or SettingsManager()
    settings = sm.load()

    # Initialize workflow store
    wf_store = WorkflowStore(settings.workflows_dir)

    # Initialize registry and orchestrator
    registry = domain_registry or DomainRegistry()
    if domain_registry is None:
        register_builtin_packs(registry)

    # Build provider factory from settings if none supplied
    if lm_provider is None and lm_provider_factory is None:
        lm_provider_factory = _make_provider_factory(settings)

    orchestrator = SessionOrchestrator(registry, lm_provider_factory=lm_provider_factory)
    streamer = EventStreamer()

    # Store on app state for endpoint access
    app.state.lm_provider = lm_provider
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    app.state.streamer = streamer
    app.state.settings_manager = sm
    app.state.settings = settings

    # ── Settings Endpoints ────────────────────────────────────────────

    @app.get("/api/settings", response_model=SettingsResponse)
    def get_settings() -> dict[str, Any]:
        """Return current platform settings (API keys masked)."""
        return app.state.settings.mask_keys()

    @app.put("/api/settings", response_model=SettingsResponse)
    def update_settings(request: UpdateSettingsRequest) -> dict[str, Any]:
        """Update platform settings. Only provided fields are changed."""
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=422, detail="No fields to update")

        updated = app.state.settings_manager.update(updates)
        app.state.settings = updated

        # Rebuild the provider factory with new settings
        nonlocal lm_provider_factory
        lm_provider_factory = _make_provider_factory(updated)
        orchestrator._lm_provider_factory = lm_provider_factory

        return updated.mask_keys()

    # ── Models Endpoints ──────────────────────────────────────────────

    @app.get("/api/models", response_model=list[ModelListEntry])
    def list_models() -> list[dict[str, Any]]:
        """List available models from all configured providers."""
        models: list[dict[str, Any]] = []
        current_settings: PlatformSettings = app.state.settings

        # Cloud models from registry (available if API key configured)
        if current_settings.has_openai():
            for name in model_registry.list_models_by_provider("openai"):
                caps = model_registry.get_capabilities(name)
                models.append({
                    "name": name,
                    "provider": "openai",
                    "display_name": caps.display_name,
                    "available": True,
                })

        if current_settings.has_anthropic():
            for name in model_registry.list_models_by_provider("anthropic"):
                caps = model_registry.get_capabilities(name)
                models.append({
                    "name": name,
                    "provider": "anthropic",
                    "display_name": caps.display_name,
                    "available": True,
                })

        # Ollama models (live-fetched)
        ollama_models = _fetch_ollama_models(current_settings.ollama_base_url)
        for m in ollama_models:
            caps = model_registry.get_capabilities_or_none(m["name"])
            models.append({
                "name": m["name"],
                "provider": "ollama",
                "display_name": caps.display_name if caps else m["name"],
                "available": True,
            })

        # If managed proxy is configured, note it
        if current_settings.has_managed():
            models.append({
                "name": current_settings.default_model,
                "provider": "managed",
                "display_name": f"Managed ({current_settings.default_model})",
                "available": True,
            })

        return models

    @app.get("/api/models/{model_name}/capabilities", response_model=ModelCapabilitiesResponse)
    def get_model_capabilities(model_name: str) -> dict[str, Any]:
        """Return capabilities for a specific model."""
        caps = model_registry.get_capabilities_or_none(model_name)
        if caps is None:
            raise HTTPException(
                status_code=404,
                detail=f"No capability data for model '{model_name}'",
            )
        return asdict(caps)

    # ── Workflow Endpoints ─────────────────────────────────────────────

    @app.post("/api/workflows", response_model=WorkflowSummaryResponse, status_code=201)
    def save_workflow(workflow: WorkflowDefinition) -> dict[str, Any]:
        """Save a workflow definition."""
        from agentos.schemas.workflow import WorkflowDefinition as _WD

        wf_store.save(workflow)
        return {
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "version": workflow.version,
            "node_count": len(workflow.nodes),
            "edge_count": len(workflow.edges),
            "domain_pack": workflow.domain_pack,
            "created_at": workflow.created_at,
            "updated_at": workflow.updated_at,
            "template_source": workflow.template_source,
        }

    @app.get("/api/workflows", response_model=list[WorkflowSummaryResponse])
    def list_workflows() -> list[dict[str, Any]]:
        """List all saved workflows."""
        return [s.model_dump() for s in wf_store.list()]

    @app.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> Any:
        """Get a workflow definition by ID."""
        try:
            return wf_store.load(workflow_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )

    @app.put("/api/workflows/{workflow_id}", response_model=WorkflowSummaryResponse)
    def update_workflow(workflow_id: str, workflow: WorkflowDefinition) -> dict[str, Any]:
        """Update an existing workflow."""
        from agentos.schemas.workflow import WorkflowDefinition as _WD

        if not wf_store.exists(workflow_id):
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )
        # Ensure the ID matches the URL
        updated = workflow.model_copy(update={"id": workflow_id})
        wf_store.save(updated)
        return {
            "id": updated.id,
            "name": updated.name,
            "description": updated.description,
            "version": updated.version,
            "node_count": len(updated.nodes),
            "edge_count": len(updated.edges),
            "domain_pack": updated.domain_pack,
            "created_at": updated.created_at,
            "updated_at": updated.updated_at,
            "template_source": updated.template_source,
        }

    @app.delete("/api/workflows/{workflow_id}", status_code=204)
    def delete_workflow(workflow_id: str) -> None:
        """Delete a workflow."""
        try:
            wf_store.delete(workflow_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )

    @app.post("/api/workflows/{workflow_id}/clone", response_model=WorkflowSummaryResponse)
    def clone_workflow(workflow_id: str) -> dict[str, Any]:
        """Clone a workflow with a new ID."""
        try:
            cloned = wf_store.clone(workflow_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )
        return {
            "id": cloned.id,
            "name": cloned.name,
            "description": cloned.description,
            "version": cloned.version,
            "node_count": len(cloned.nodes),
            "edge_count": len(cloned.edges),
            "domain_pack": cloned.domain_pack,
            "created_at": cloned.created_at,
            "updated_at": cloned.updated_at,
            "template_source": cloned.template_source,
        }

    @app.post("/api/workflows/{workflow_id}/validate", response_model=WorkflowValidationResponse)
    def validate_workflow_endpoint(workflow_id: str) -> dict[str, Any]:
        """Validate a workflow definition."""
        from agentos.runtime.workflow_validator import validate_workflow

        try:
            workflow = wf_store.load(workflow_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )

        # Gather available tools and models
        available_tools: set[str] = set()
        if workflow.domain_pack and registry.has_pack(workflow.domain_pack):
            pack = registry.get_pack(workflow.domain_pack)
            available_tools = {t.name for t in pack.tools}

        issues = validate_workflow(
            workflow,
            available_tools=available_tools,
        )
        return {
            "valid": all(i.severity != "error" for i in issues),
            "issues": [i.model_dump() for i in issues],
        }

    @app.post("/api/workflows/{workflow_id}/run", response_model=RunWorkflowResponse)
    def run_workflow(workflow_id: str, request: RunWorkflowRequest) -> dict[str, Any]:
        """Compile a workflow into a session and start execution."""
        try:
            workflow = wf_store.load(workflow_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' not found"
            )

        try:
            sid = orchestrator.create_session_from_workflow(
                workflow, task_description=request.task_description
            )
            orchestrator.start_workflow_session(sid)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))

        return {"session_id": sid, "state": "RUNNING"}

    # ── Domain Pack Endpoints ────────────────────────────────────────

    @app.get("/api/packs", response_model=list[DomainPackSummaryResponse])
    def list_packs() -> list[dict[str, Any]]:
        packs = registry.list_packs()
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "version": p.version,
                "tool_count": len(p.tools),
                "role_count": len(p.role_templates),
                "workflow_count": len(p.workflows),
            }
            for p in packs
        ]

    @app.get("/api/packs/{name}", response_model=DomainPackDetailResponse)
    def get_pack(name: str) -> Any:
        try:
            pack = registry.get_pack(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Domain pack '{name}' not found")
        return pack

    @app.get("/api/packs/{name}/roles")
    def get_pack_roles(name: str) -> Any:
        try:
            pack = registry.get_pack(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Domain pack '{name}' not found")
        return pack.role_templates

    # ── Session Endpoints ────────────────────────────────────────────

    @app.post("/api/sessions", response_model=SessionSummaryResponse, status_code=201)
    def create_session(request: CreateSessionRequest) -> dict[str, Any]:
        config = SessionConfig(
            domain_pack=request.domain_pack,
            workflow=request.workflow,
            agents=request.agents,
            workspace_root=request.workspace_root,
            task_description=request.task_description,
            max_parallel=request.max_parallel,
        )
        try:
            sid = orchestrator.create_session(config)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        info = orchestrator.get_session_info(sid)
        return {
            "session_id": sid,
            "state": info["state"],
            "domain_pack": info["domain_pack"],
            "workflow": info["workflow"],
            "created_at": info["created_at"],
            "agent_count": sum(a.count for a in config.agents),
        }

    @app.get("/api/sessions", response_model=list[SessionSummaryResponse])
    def list_sessions() -> list[dict[str, Any]]:
        return orchestrator.list_sessions()

    @app.get("/api/sessions/{session_id}", response_model=SessionDetailResponse)
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            return orchestrator.get_session_info(session_id)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )

    @app.post("/api/sessions/{session_id}/start")
    def start_session(session_id: str) -> dict[str, str]:
        try:
            orchestrator.start_session(
                session_id, lm_provider=app.state.lm_provider
            )
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"status": "started"}

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict[str, str]:
        try:
            orchestrator.stop_session(session_id)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )
        return {"status": "stopped"}

    @app.get("/api/sessions/{session_id}/events", response_model=list[EventResponse])
    def get_session_events(session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        try:
            events = orchestrator.get_session_events(
                session_id, after_seq=after_seq
            )
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )
        return [
            {
                "run_id": e.run_id,
                "seq": e.seq,
                "timestamp": e.timestamp.isoformat(),
                "event_type": e.event_type.value,
                "payload": e.payload,
            }
            for e in events
        ]

    # ── Integration Endpoints ─────────────────────────────────────────

    @app.get("/api/integrations", response_model=list[IntegrationStatusResponse])
    def list_integrations() -> list[dict[str, Any]]:
        """List connected integrations and their status."""
        current: PlatformSettings = app.state.settings
        return [
            {
                "name": "google",
                "connected": bool(current.google_oauth_token),
                "display_name": "Google Workspace",
            },
            {
                "name": "slack",
                "connected": bool(current.slack_bot_token),
                "display_name": "Slack",
            },
        ]

    @app.post("/api/integrations/slack/connect", response_model=IntegrationStatusResponse)
    def connect_slack(request: ConnectSlackRequest) -> dict[str, Any]:
        """Save Slack bot token to settings."""
        updated = app.state.settings_manager.update({"slack_bot_token": request.bot_token})
        app.state.settings = updated
        return {
            "name": "slack",
            "connected": True,
            "display_name": "Slack",
        }

    @app.delete("/api/integrations/{integration_name}/disconnect")
    def disconnect_integration(integration_name: str) -> dict[str, str]:
        """Remove an integration's stored credentials."""
        field_map = {
            "google": "google_oauth_token",
            "slack": "slack_bot_token",
        }
        field = field_map.get(integration_name)
        if field is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown integration '{integration_name}'",
            )
        # Setting to empty string to clear
        current: PlatformSettings = app.state.settings
        updated = current.model_copy(update={field: None})
        app.state.settings_manager.save(updated)
        app.state.settings = updated
        return {"status": "disconnected", "integration": integration_name}

    # ── WebSocket ────────────────────────────────────────────────────

    @app.websocket("/ws/sessions/{session_id}/events")
    async def ws_session_events(websocket: WebSocket, session_id: str) -> None:
        try:
            orchestrator.get_session_state(session_id)
        except KeyError:
            await websocket.close(code=4004, reason="Session not found")
            return

        await websocket.accept()
        try:
            await streamer.stream(websocket, orchestrator, session_id)
        except WebSocketDisconnect:
            pass

    return app
