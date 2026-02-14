"""FastAPI server for the AgentOS Platform."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from agentos.lm.provider import BaseLMProvider
from agentos.runtime.domain_registry import DomainRegistry
from agentos.schemas.session import AgentSlotConfig, SessionConfig

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.api_schemas import (
    CreateSessionRequest,
    DomainPackDetailResponse,
    DomainPackSummaryResponse,
    EventResponse,
    SessionDetailResponse,
    SessionSummaryResponse,
)
from agentplatform.event_stream import EventStreamer
from agentplatform.orchestrator import SessionOrchestrator


def create_app(
    *,
    lm_provider: BaseLMProvider | None = None,
    domain_registry: DomainRegistry | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lm_provider: Default LM provider for sessions.
        domain_registry: Pre-configured registry (builtins registered if None).
    """
    app = FastAPI(title="AgentOS Platform", version="0.1.0")

    # Initialize registry and orchestrator
    registry = domain_registry or DomainRegistry()
    if domain_registry is None:
        register_builtin_packs(registry)
    orchestrator = SessionOrchestrator(registry)
    streamer = EventStreamer()

    # Store provider for session starts
    app.state.lm_provider = lm_provider
    app.state.orchestrator = orchestrator
    app.state.registry = registry
    app.state.streamer = streamer

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
