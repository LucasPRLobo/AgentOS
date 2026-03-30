"""Comms state file I/O — bridge between the orchestrator and the MCP server.

The orchestrator writes comms state to ``.agentos/comms_state.json`` before
launching an agent.  The MCP server (running as a child process of Claude Code)
reads this file to serve board state and pending messages.

When the agent sends messages or posts to the board via MCP tools, the MCP
server writes to ``.agentos/outbox/`` (same convention as Phase 1).  The
orchestrator reads the outbox after the agent completes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import DirectMessage

logger = logging.getLogger(__name__)


def write_comms_state(
    workspace: Path,
    board_manager: BoardManager,
    pending_messages: list[DirectMessage],
    agent_id: str,
    workflow_id: str,
) -> Path:
    """Write comms state to workspace for the MCP server to read.

    Returns the path to the state file.
    """
    comms_dir = workspace / ".agentos"
    comms_dir.mkdir(exist_ok=True)

    state = {
        "agent_id": agent_id,
        "workflow_id": workflow_id,
        "board_compact": board_manager.render_compact(max_tokens=400),
        "board_full": board_manager.render_full(),
        "inbox": [
            {
                "message_id": m.message_id,
                "thread_id": m.thread_id,
                "reply_to": m.reply_to,
                "sender_type": m.sender_type,
                "sender_id": m.sender_id,
                "content": m.content,
                "speech_act": str(m.speech_act),
                "priority": str(m.priority),
                "timestamp": m.timestamp,
            }
            for m in pending_messages
        ],
    }

    state_path = comms_dir / "comms_state.json"
    state_path.write_text(json.dumps(state, indent=2))
    return state_path


def read_comms_state(workspace: Path) -> dict[str, Any]:
    """Read comms state from workspace.  Used by the MCP server.

    Returns a dict with keys: agent_id, workflow_id, board_compact,
    board_full, inbox.  Returns empty defaults if file missing.
    """
    state_path = workspace / ".agentos" / "comms_state.json"
    if not state_path.exists():
        return {
            "agent_id": "unknown",
            "workflow_id": "unknown",
            "board_compact": "[WORKSPACE BOARD — v0]\n[END BOARD]",
            "board_full": {},
            "inbox": [],
        }
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read comms state: %s", exc)
        return {
            "agent_id": "unknown",
            "workflow_id": "unknown",
            "board_compact": "[WORKSPACE BOARD — v0]\n[END BOARD]",
            "board_full": {},
            "inbox": [],
        }


def write_outbox_message(workspace: Path, message: dict[str, Any]) -> Path:
    """Write a single message to the outbox.  Used by the MCP server.

    Returns the path to the created file.
    """
    outbox_dir = workspace / ".agentos" / "outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)

    # Use a counter-based name to preserve ordering
    existing = list(outbox_dir.glob("*.json"))
    index = len(existing)
    path = outbox_dir / f"mcp-{index:04d}.json"
    path.write_text(json.dumps(message, indent=2))
    return path


def refresh_comms_state(
    workspace: Path,
    board_compact: str | None = None,
    new_inbox_messages: list[dict] | None = None,
) -> None:
    """Partially update the comms state file.

    Used by the MCP server to reflect board posts and sent messages
    so subsequent tool calls within the same session see updated state.
    """
    state = read_comms_state(workspace)

    if board_compact is not None:
        state["board_compact"] = board_compact

    if new_inbox_messages:
        state.setdefault("inbox", []).extend(new_inbox_messages)

    state_path = workspace / ".agentos" / "comms_state.json"
    state_path.write_text(json.dumps(state, indent=2))
