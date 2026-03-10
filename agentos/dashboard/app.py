"""Dashboard FastAPI application factory.

Usage:
    app = create_app("/path/to/events.db")
    uvicorn.run(app, host="127.0.0.1", port=8420)
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from agentos.dashboard.serializers import (
    budget_snapshot_to_dict,
    event_to_dict,
    gate_snapshot_to_dict,
    snapshot_to_dict,
    snapshot_to_summary,
)
from agentos.dashboard.websocket import event_stream
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.replayer import WorkflowReplayer
from agentos.schemas.events import EventType

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Optional authentication middleware for the dashboard.

    When an AuthManager is provided, mutating requests (POST, PUT, DELETE)
    require a valid ``Authorization: Bearer <token>`` header.  Read-only
    methods (GET, HEAD, OPTIONS) and WebSocket upgrades pass through
    unauthenticated.

    When *auth_manager* is ``None`` (the default), every request is allowed —
    preserving backwards-compatible behaviour for local testers.
    """

    def __init__(self, app, auth_manager=None):
        super().__init__(app)
        self._auth = auth_manager

    async def dispatch(self, request: Request, call_next):
        # If auth is not configured, pass through
        if self._auth is None:
            return await call_next(request)

        # Allow read-only methods without auth
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Allow WebSocket upgrades
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check Authorization header for mutating requests
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization required. Provide 'Authorization: Bearer <token>' header."},
            )

        token = auth_header[7:]  # Strip "Bearer "
        # Try API key first, then JWT
        user = self._auth.verify_api_key(token)
        if user is None:
            user = self._auth.verify_jwt(token)
        if user is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token."},
            )

        # Attach user to request state for downstream use
        request.state.user = user
        return await call_next(request)


def create_app(db_path: str) -> FastAPI:
    """Create the dashboard FastAPI application.

    Args:
        db_path: Path to the SQLite event log database.

    Returns:
        Configured FastAPI app with REST + WebSocket endpoints.
    """
    app = FastAPI(
        title="AgentOS Dashboard",
        description="Read-only monitoring dashboard for AgentOS workflows.",
        version="1.5.0",
    )

    # Auth middleware (opt-in via AGENTOS_AUTH_ENABLED=1)
    auth_manager = None
    if os.environ.get("AGENTOS_AUTH_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        from agentos.dashboard.auth import AuthManager
        from agentos.schemas.auth import AuthConfig

        jwt_secret = os.environ.get("AGENTOS_JWT_SECRET", "")
        if not jwt_secret:
            jwt_secret = secrets.token_urlsafe(32)
            logger.warning(
                "AGENTOS_JWT_SECRET not set — generated ephemeral secret. "
                "JWTs will not survive server restarts."
            )

        auth_config = AuthConfig(
            enabled=True,
            jwt_secret=jwt_secret,
            token_expiry_hours=int(os.environ.get("AGENTOS_TOKEN_EXPIRY_HOURS", "24")),
        )
        auth_db = os.environ.get("AGENTOS_AUTH_DB", db_path)
        auth_manager = AuthManager(config=auth_config, db_path=auth_db)
        logger.info("Dashboard authentication enabled.")

    app.add_middleware(AuthMiddleware, auth_manager=auth_manager)

    # CORS — configurable origins, defaults to common local dev ports
    raw_origins = os.environ.get(
        "AGENTOS_CORS_ORIGINS", "http://localhost:5173,http://localhost:8420"
    )
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip() and o.strip() != "*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )

    # Shared event log — SQLite WAL mode supports concurrent reads
    event_log = SQLiteEventLog(db_path)
    replayer = WorkflowReplayer(event_log)

    # ------------------------------------------------------------------
    # REST Endpoints
    # ------------------------------------------------------------------

    @app.get("/api/workflows")
    def list_workflows() -> list[dict[str, Any]]:
        """List all workflows with summary info."""
        # Find all distinct workflow IDs from WORKFLOW_STARTED events
        started_events = event_log.query(event_type=EventType.WORKFLOW_STARTED)
        workflow_ids = list(dict.fromkeys(e.workflow_id for e in started_events))

        summaries = []
        for wf_id in workflow_ids:
            snapshot = replayer.replay(wf_id)
            summaries.append(snapshot_to_summary(snapshot))

        return summaries

    @app.get("/api/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        """Get full workflow detail (snapshot)."""
        snapshot = replayer.replay(workflow_id)
        if not snapshot.events:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Workflow {workflow_id!r} not found"},
            )
        return snapshot_to_dict(snapshot)

    @app.get("/api/workflows/{workflow_id}/events")
    def get_events(
        workflow_id: str,
        type: str | None = Query(None, description="Filter by event type"),
        since_seq: int | None = Query(None, description="Only events with seq >= this value"),
        limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    ) -> dict[str, Any]:
        """Get events for a workflow with optional filters."""
        event_type = None
        if type:
            try:
                event_type = EventType(type)
            except ValueError:
                event_type = type  # Pass through as string

        events = event_log.query(
            workflow_id=workflow_id,
            event_type=event_type,
            since_seq=since_seq,
        )

        # Apply limit
        events = events[:limit]

        last_seq = events[-1].seq if events else (since_seq or 0)

        return {
            "events": [event_to_dict(e) for e in events],
            "last_seq": last_seq,
        }

    @app.get("/api/workflows/{workflow_id}/budget")
    def get_budget(workflow_id: str) -> dict[str, Any]:
        """Get budget usage for a workflow."""
        snapshot = replayer.replay(workflow_id)
        return {
            "agents": {
                aid: budget_snapshot_to_dict(b)
                for aid, b in snapshot.budgets.items()
            },
            "total": {
                "tokens": snapshot.total_tokens,
                "cost": snapshot.total_cost,
            },
        }

    @app.get("/api/workflows/{workflow_id}/gates")
    def get_gates(workflow_id: str) -> list[dict[str, Any]]:
        """Get gate statuses for a workflow."""
        snapshot = replayer.replay(workflow_id)
        return [
            gate_snapshot_to_dict(g) for g in snapshot.gates.values()
        ]

    # ------------------------------------------------------------------
    # Workflow Builder / Template CRUD
    # ------------------------------------------------------------------

    builder = None

    def _get_builder():
        nonlocal builder
        if builder is None:
            from agentos.dashboard.builder import WorkflowBuilder
            builder = WorkflowBuilder(db_path)
        return builder

    @app.post("/api/templates")
    def create_template(body: dict[str, Any]) -> dict[str, Any]:
        """Create a new workflow template."""
        b = _get_builder()
        template = b.create_template(
            name=body.get("name", "Untitled"),
            workflow_yaml=body.get("workflow_yaml", ""),
            description=body.get("description", ""),
        )
        return template.to_dict()

    @app.get("/api/templates")
    def list_templates() -> list[dict[str, Any]]:
        """List all workflow templates."""
        b = _get_builder()
        return [t.to_dict() for t in b.list_templates()]

    @app.get("/api/templates/{template_id}")
    def get_template(template_id: str) -> dict[str, Any]:
        """Get a specific template."""
        b = _get_builder()
        template = b.get_template(template_id)
        if template is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Template {template_id!r} not found"},
            )
        return template.to_dict()

    @app.put("/api/templates/{template_id}")
    def update_template(template_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Update an existing template."""
        b = _get_builder()
        template = b.update_template(
            template_id=template_id,
            name=body.get("name"),
            workflow_yaml=body.get("workflow_yaml"),
            description=body.get("description"),
        )
        if template is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Template {template_id!r} not found"},
            )
        return template.to_dict()

    @app.delete("/api/templates/{template_id}")
    def delete_template(template_id: str) -> dict[str, Any]:
        """Delete a template."""
        b = _get_builder()
        deleted = b.delete_template(template_id)
        if not deleted:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Template {template_id!r} not found"},
            )
        return {"deleted": True}

    @app.post("/api/templates/validate")
    def validate_template(body: dict[str, Any]) -> dict[str, Any]:
        """Validate a workflow YAML string."""
        b = _get_builder()
        yaml_str = body.get("workflow_yaml", "")
        result = b.validate_workflow(yaml_str)
        return result.to_dict()

    # ------------------------------------------------------------------
    # Run Management
    # ------------------------------------------------------------------

    from agentos.dashboard.run_manager import RunManager
    run_manager = RunManager()

    @app.post("/api/run")
    def start_run(body: dict[str, Any]) -> dict[str, Any]:
        """Start a new workflow run."""
        yaml_str = body.get("workflow_yaml", "")
        if not yaml_str:
            return JSONResponse(status_code=400, content={"detail": "workflow_yaml required"})
        run_id = run_manager.start(
            yaml_str,
            live=body.get("live", False),
            interactive=body.get("interactive", False),
            db_path=db_path,
        )
        return {"run_id": run_id}

    @app.delete("/api/run/{run_id}")
    def cancel_run(run_id: str) -> dict[str, Any]:
        """Cancel a running workflow."""
        cancelled = run_manager.cancel(run_id)
        if not cancelled:
            return JSONResponse(status_code=404, content={"detail": f"Run {run_id!r} not found"})
        return {"cancelled": True}

    @app.get("/api/run")
    def list_runs() -> list[dict[str, Any]]:
        """List active workflow runs."""
        return run_manager.list_active()

    # ------------------------------------------------------------------
    # Gate Resolution
    # ------------------------------------------------------------------

    @app.post("/api/workflows/{workflow_id}/gates/{gate_id}/resolve")
    def resolve_gate(workflow_id: str, gate_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Resolve a pending gate from the UI."""
        from agentos.kernel.gate_manager import GateManager
        from agentos.kernel.seq import SeqCounter
        from agentos.schemas.gate import GateResolution as GR

        last_seq = 0
        events = event_log.query(workflow_id=workflow_id)
        if events:
            last_seq = events[-1].seq

        seq = SeqCounter(start=last_seq + 1)
        gate_mgr = GateManager(event_log=event_log, seq=seq, workflow_id=workflow_id)

        resolution_str = body.get("resolution", "approved")
        feedback = body.get("feedback", "")
        resolved_by = body.get("resolved_by", "dashboard_user")

        # Convert string to GateResolution enum
        try:
            resolution = GR(resolution_str)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Invalid resolution: {resolution_str!r}. Must be one of: approved, rejected, edited"},
            )

        try:
            gate_mgr.resolve_gate(
                gate_id=gate_id,
                resolution=resolution,
                reviewer=resolved_by,
                feedback=feedback,
            )
        except Exception:
            logger.exception("Failed to resolve gate %s in workflow %s", gate_id, workflow_id)
            return JSONResponse(status_code=400, content={"detail": "Failed to resolve gate. Check server logs for details."})

        return {"gate_id": gate_id, "resolution": resolution_str}

    # ------------------------------------------------------------------
    # NL Workflow Generation
    # ------------------------------------------------------------------

    @app.post("/api/builder/generate")
    def generate_workflow(body: dict[str, Any]) -> dict[str, Any]:
        """Generate workflow YAML from natural language description."""
        description = body.get("description", "")
        if not description:
            return JSONResponse(status_code=400, content={"detail": "description required"})
        try:
            from agentos.dashboard.nl_generator import generate_workflow_yaml
            yaml_str = generate_workflow_yaml(description)
            return {"workflow_yaml": yaml_str}
        except RuntimeError:
            logger.exception("Workflow generation failed for description: %.100s", description)
            return JSONResponse(status_code=500, content={"detail": "Workflow generation failed. Check server logs for details."})

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            await event_stream(websocket, event_log)
        except WebSocketDisconnect:
            pass

    # ------------------------------------------------------------------
    # Static files (frontend) — served last to not shadow API routes
    # ------------------------------------------------------------------

    frontend_dist = Path(__file__).parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


# Module-level app for `uvicorn agentos.dashboard.app:app`
# Uses DB path from AGENTOS_DB env var, or a file-based DB for dev.
# NOTE: :memory: does NOT work because RunManager spawns subprocesses
# that need to share the same database.
app = create_app(os.environ.get("AGENTOS_DB", "agentos_dashboard.db"))
