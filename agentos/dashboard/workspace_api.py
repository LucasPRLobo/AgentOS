"""Workspace REST API routes for the dashboard.

Provides endpoints for board, backlog, messaging, team, cost, and
workspace lifecycle — connecting the frontend to the workspace runtime.

These routes operate on in-memory WorkspaceRuntime instances stored
in a registry. Each workspace gets its own runtime.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.schemas import (
    BacklogTask,
    WorkspaceConfig,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)

# In-memory workspace registry: workspace_id → runtime
_runtimes: dict[str, Any] = {}
_lock = threading.Lock()


def _get_runtime(workspace_id: str):
    """Get a workspace runtime by ID, or None."""
    with _lock:
        return _runtimes.get(workspace_id)


def register_runtime(workspace_id: str, runtime) -> None:
    """Register a workspace runtime (called externally when a workspace starts)."""
    with _lock:
        _runtimes[workspace_id] = runtime


def create_workspace_router(event_log: EventLog) -> APIRouter:
    """Create the workspace API router."""

    router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
    seq = SeqCounter()

    # ------------------------------------------------------------------
    # Workspace CRUD
    # ------------------------------------------------------------------

    @router.get("")
    def list_workspaces() -> list[dict]:
        """List all registered workspaces."""
        results = []
        with _lock:
            for wid, rt in _runtimes.items():
                config = rt.config
                backlog = rt.backlog.get_all_tasks()
                done = sum(1 for t in backlog if t.status == "done")
                results.append({
                    "workspace_id": wid,
                    "name": config.name,
                    "goal": config.goal,
                    "status": rt.state.status,
                    "team_mode": str(config.team_mode),
                    "team_size": len(config.team),
                    "tasks_total": len(backlog),
                    "tasks_done": done,
                    "budget_used_pct": 0.0,
                    "last_active": rt.state.last_active,
                    "created_at": rt.state.created_at,
                })
        return results

    @router.get("/{workspace_id}")
    def get_workspace(workspace_id: str) -> dict:
        """Get full workspace state."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        board = rt.board.get_state()
        backlog = rt.backlog.get_all_tasks()
        messages = rt.bus.get_all_messages()

        return {
            "workspace_id": workspace_id,
            "config": rt.config.model_dump(mode="json"),
            "status": rt.state.status,
            "board": board.model_dump(mode="json"),
            "backlog": [t.model_dump(mode="json") for t in backlog],
            "team": [s.model_dump(mode="json") for s in board.team_status],
            "messages": [m.model_dump(mode="json") for m in messages],
            "cost": {
                "total_usd": 0.0,
                "total_tokens": 0,
                "budget_usd": rt.config.budget.max_cost_usd,
                "budget_tokens": rt.config.budget.max_tokens,
                "consumed_pct": 0.0,
                "per_agent": {},
                "per_task": {},
            },
            "created_at": rt.state.created_at,
            "last_active": rt.state.last_active,
        }

    @router.post("/{workspace_id}/control")
    def control_workspace(workspace_id: str, body: dict[str, Any]) -> dict:
        """Control workspace: pause, resume, complete."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        action = body.get("action", "")
        if action == "pause":
            rt.pause()
        elif action == "resume":
            rt.resume()
        elif action == "complete":
            rt.complete()
        else:
            return JSONResponse(status_code=400, content={"detail": f"Unknown action: {action}"})

        return {"status": rt.state.status}

    # ------------------------------------------------------------------
    # Board
    # ------------------------------------------------------------------

    @router.get("/{workspace_id}/board")
    def get_board(workspace_id: str) -> dict:
        """Get current board state."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})
        return rt.board.get_state().model_dump(mode="json")

    @router.post("/{workspace_id}/board")
    def post_to_board(workspace_id: str, body: dict[str, Any]) -> dict:
        """Post to the board as the human lead."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        from agentos.comms.schemas import BoardPost, BoardSection, SpeechAct

        content = body.get("content", "")
        section = body.get("section", "post")
        speech_act = body.get("speech_act", "inform")

        if not content:
            return JSONResponse(status_code=400, content={"detail": "content required"})

        post = BoardPost(
            section=BoardSection(section),
            author_type="human",
            author_id="human",
            content=content,
            speech_act=SpeechAct(speech_act),
            pinned=section == "announcement",
        )
        post_id = rt.board.post(post)
        return post.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Backlog
    # ------------------------------------------------------------------

    @router.get("/{workspace_id}/backlog")
    def get_backlog(workspace_id: str) -> list[dict]:
        """Get all backlog tasks."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})
        return [t.model_dump(mode="json") for t in rt.backlog.get_all_tasks()]

    @router.post("/{workspace_id}/backlog")
    def create_task(workspace_id: str, body: dict[str, Any]) -> dict:
        """Create a new backlog task."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        title = body.get("title", "")
        if not title:
            return JSONResponse(status_code=400, content={"detail": "title required"})

        task = BacklogTask(
            title=title,
            description=body.get("description", ""),
            created_by="human",
            suggested_for=body.get("suggested_for"),
            priority=body.get("priority", "normal"),
        )
        rt.add_task(task)
        return task.model_dump(mode="json")

    @router.put("/{workspace_id}/backlog/{task_id}")
    def update_task(workspace_id: str, task_id: str, body: dict[str, Any]) -> dict:
        """Update a backlog task (claim, complete, etc.)."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        action = body.get("action", "")
        try:
            if action == "claim":
                participant = body.get("participant", "human")
                rt.claim_task(task_id, participant)
            elif action == "complete":
                summary = body.get("summary", "")
                rt.complete_task(task_id, {"summary": summary} if summary else None)
            elif action == "start":
                rt.backlog.start_task(task_id)
            elif action == "cancel":
                rt.backlog.cancel_task(task_id, body.get("reason", "cancelled by user"))
            else:
                return JSONResponse(status_code=400, content={"detail": f"Unknown action: {action}"})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"detail": str(e)})

        task = rt.backlog.get_task(task_id)
        return task.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    @router.get("/{workspace_id}/messages")
    def get_messages(workspace_id: str, participant: str | None = None) -> list[dict]:
        """Get messages, optionally filtered by participant."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        if participant:
            msgs = rt.bus.get_messages_for_participant(participant)
        else:
            msgs = rt.bus.get_all_messages()
        return [m.model_dump(mode="json") for m in msgs]

    @router.post("/{workspace_id}/messages")
    def send_message(workspace_id: str, body: dict[str, Any]) -> dict:
        """Send a direct message."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})

        to = body.get("to", "")
        content = body.get("content", "")
        if not to or not content:
            return JSONResponse(status_code=400, content={"detail": "to and content required"})

        from agentos.comms.schemas import DirectMessage, MessagePriority, SpeechAct

        msg = DirectMessage(
            sender_type="human",
            sender_id="human",
            recipient_type="human" if to == "human" else "agent",
            recipient_id=to,
            content=content,
            speech_act=SpeechAct(body.get("speech_act", "inform")),
            priority=MessagePriority(body.get("priority", "normal")),
            workflow_id=workspace_id,
        )
        rt.bus.send(msg)
        return msg.model_dump(mode="json")

    @router.get("/{workspace_id}/messages/{thread_id}")
    def get_thread(workspace_id: str, thread_id: str) -> list[dict]:
        """Get messages in a thread."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})
        msgs = rt.bus.get_thread(thread_id)
        return [m.model_dump(mode="json") for m in msgs]

    # ------------------------------------------------------------------
    # Team & Cost
    # ------------------------------------------------------------------

    @router.get("/{workspace_id}/team")
    def get_team(workspace_id: str) -> list[dict]:
        """Get team roster with live states."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})
        board = rt.board.get_state()
        return [s.model_dump(mode="json") for s in board.team_status]

    @router.get("/{workspace_id}/cost")
    def get_cost(workspace_id: str) -> dict:
        """Get cost breakdown."""
        rt = _get_runtime(workspace_id)
        if rt is None:
            return JSONResponse(status_code=404, content={"detail": "Workspace not found"})
        return {
            "total_usd": 0.0,
            "total_tokens": 0,
            "budget_usd": rt.config.budget.max_cost_usd,
            "budget_tokens": rt.config.budget.max_tokens,
            "consumed_pct": 0.0,
            "per_agent": {},
            "per_task": {},
        }

    return router


def create_workspace_websocket_handler(event_log: EventLog):
    """Create WebSocket handler for workspace real-time updates."""

    async def workspace_ws(websocket: WebSocket, workspace_id: str) -> None:
        """WebSocket endpoint for workspace events."""
        await websocket.accept()

        rt = _get_runtime(workspace_id)
        if rt is None:
            await websocket.send_json({"type": "error", "data": {"detail": "Workspace not found"}})
            await websocket.close()
            return

        # Send initial snapshot
        board = rt.board.get_state()
        await websocket.send_json({
            "type": "snapshot",
            "data": {
                "board": board.model_dump(mode="json"),
                "backlog": [t.model_dump(mode="json") for t in rt.backlog.get_all_tasks()],
                "team": [s.model_dump(mode="json") for s in board.team_status],
            },
        })

        # Poll for changes
        import asyncio
        last_board_version = board.version
        last_backlog_count = len(rt.backlog.get_all_tasks())
        last_msg_count = len(rt.bus.get_all_messages())

        try:
            while True:
                await asyncio.sleep(0.5)

                # Check for board changes
                current_board = rt.board.get_state()
                if current_board.version > last_board_version:
                    # Send new posts
                    new_posts = [
                        p for p in current_board.recent_posts
                        if p.timestamp > board.last_updated
                    ]
                    for post in new_posts:
                        await websocket.send_json({
                            "type": "board_post",
                            "data": post.model_dump(mode="json"),
                        })
                    # Send team status updates
                    await websocket.send_json({
                        "type": "agent_status",
                        "data": [s.model_dump(mode="json") for s in current_board.team_status],
                    })
                    last_board_version = current_board.version
                    board = current_board

                # Check for backlog changes
                current_tasks = rt.backlog.get_all_tasks()
                if len(current_tasks) != last_backlog_count:
                    await websocket.send_json({
                        "type": "backlog_update",
                        "data": [t.model_dump(mode="json") for t in current_tasks],
                    })
                    last_backlog_count = len(current_tasks)

                # Check for new messages
                current_msgs = rt.bus.get_all_messages()
                if len(current_msgs) > last_msg_count:
                    for msg in current_msgs[last_msg_count:]:
                        await websocket.send_json({
                            "type": "message",
                            "data": msg.model_dump(mode="json"),
                        })
                    last_msg_count = len(current_msgs)

        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("Workspace WebSocket error: %s", exc)

    return workspace_ws
