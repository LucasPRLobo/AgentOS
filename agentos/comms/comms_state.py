"""Comms state file I/O — shared state for concurrent workspace access.

Two modes:

**Legacy (sequential):** orchestrator writes ``comms_state.json`` before
launching an agent, MCP server reads it. Works for one-at-a-time execution.

**Concurrent (supervisor):** each agent has its own directory under
``.agentos/agents/{id}/`` with inbox.json, outbox/, status.json.
The human has ``.agentos/human/`` with inbox.json and commands.json.
The board lives at ``.agentos/board.json`` (written by supervisor every tick).
All participants read live files, not stale snapshots.
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


# ======================================================================
# Concurrent file I/O (per-agent directories)
# ======================================================================

def _agentos_dir(workspace: Path) -> Path:
    d = workspace / ".agentos"
    d.mkdir(exist_ok=True)
    return d


def ensure_agent_dir(workspace: Path, agent_id: str) -> Path:
    """Create and return .agentos/agents/{agent_id}/."""
    d = _agentos_dir(workspace) / "agents" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "outbox").mkdir(exist_ok=True)
    return d


def ensure_human_dir(workspace: Path) -> Path:
    """Create and return .agentos/human/."""
    d = _agentos_dir(workspace) / "human"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Agent I/O ────────────────────────────────────────────────────────

def write_agent_inbox(workspace: Path, agent_id: str, messages: list[dict]) -> None:
    """Write pending messages to an agent's inbox.json."""
    agent_dir = ensure_agent_dir(workspace, agent_id)
    inbox_path = agent_dir / "inbox.json"
    # Merge with existing (don't overwrite unread messages)
    existing = []
    if inbox_path.exists():
        try:
            existing = json.loads(inbox_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing.extend(messages)
    inbox_path.write_text(json.dumps(existing, indent=2))


def read_agent_inbox(workspace: Path, agent_id: str) -> list[dict]:
    """Read and clear an agent's inbox.json."""
    agent_dir = _agentos_dir(workspace) / "agents" / agent_id
    inbox_path = agent_dir / "inbox.json"
    if not inbox_path.exists():
        return []
    try:
        messages = json.loads(inbox_path.read_text())
        inbox_path.write_text("[]")
        return messages
    except (json.JSONDecodeError, OSError):
        return []


def read_agent_outbox(workspace: Path, agent_id: str) -> list[dict]:
    """Read and clear all messages from an agent's outbox/."""
    agent_dir = _agentos_dir(workspace) / "agents" / agent_id
    outbox_dir = agent_dir / "outbox"
    if not outbox_dir.exists():
        return []
    messages = []
    for f in sorted(outbox_dir.glob("*.json")):
        try:
            messages.append(json.loads(f.read_text()))
            f.unlink()
        except (json.JSONDecodeError, OSError):
            pass
    return messages


def write_agent_status(workspace: Path, agent_id: str, status: dict) -> None:
    """Write agent's self-reported status (heartbeat + activity)."""
    agent_dir = ensure_agent_dir(workspace, agent_id)
    (agent_dir / "status.json").write_text(json.dumps(status, indent=2))


def read_agent_status(workspace: Path, agent_id: str) -> dict | None:
    """Read agent's last reported status."""
    status_path = _agentos_dir(workspace) / "agents" / agent_id / "status.json"
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_all_agent_outboxes(workspace: Path) -> dict[str, list[dict]]:
    """Read and clear outboxes for ALL agents. Returns {agent_id: [messages]}."""
    agents_dir = _agentos_dir(workspace) / "agents"
    if not agents_dir.exists():
        return {}
    result = {}
    for agent_dir in agents_dir.iterdir():
        if agent_dir.is_dir():
            msgs = read_agent_outbox(workspace, agent_dir.name)
            if msgs:
                result[agent_dir.name] = msgs
    return result


# ── Human I/O ────────────────────────────────────────────────────────

def write_human_inbox(workspace: Path, messages: list[dict]) -> None:
    """Write messages for the human to .agentos/human/inbox.json."""
    human_dir = ensure_human_dir(workspace)
    inbox_path = human_dir / "inbox.json"
    existing = []
    if inbox_path.exists():
        try:
            existing = json.loads(inbox_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing.extend(messages)
    inbox_path.write_text(json.dumps(existing, indent=2))


def read_human_inbox(workspace: Path) -> list[dict]:
    """Read and clear .agentos/human/inbox.json."""
    inbox_path = _agentos_dir(workspace) / "human" / "inbox.json"
    if not inbox_path.exists():
        return []
    try:
        messages = json.loads(inbox_path.read_text())
        inbox_path.write_text("[]")
        return messages
    except (json.JSONDecodeError, OSError):
        return []


def write_human_command(workspace: Path, command: dict) -> None:
    """Human writes a command (from CLI or dashboard)."""
    human_dir = ensure_human_dir(workspace)
    cmd_path = human_dir / "commands.json"
    existing = []
    if cmd_path.exists():
        try:
            existing = json.loads(cmd_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    existing.append(command)
    cmd_path.write_text(json.dumps(existing, indent=2))


def read_human_commands(workspace: Path) -> list[dict]:
    """Read and clear .agentos/human/commands.json."""
    cmd_path = _agentos_dir(workspace) / "human" / "commands.json"
    if not cmd_path.exists():
        return []
    try:
        commands = json.loads(cmd_path.read_text())
        cmd_path.write_text("[]")
        return commands
    except (json.JSONDecodeError, OSError):
        return []


# ── Board file ───────────────────────────────────────────────────────

def write_board_file(workspace: Path, board_data: dict) -> None:
    """Write live board state to .agentos/board.json."""
    board_path = _agentos_dir(workspace) / "board.json"
    board_path.write_text(json.dumps(board_data, indent=2))


def read_board_file(workspace: Path) -> dict | None:
    """Read live board state from .agentos/board.json."""
    board_path = _agentos_dir(workspace) / "board.json"
    if not board_path.exists():
        return None
    try:
        return json.loads(board_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# ── Events stream ────────────────────────────────────────────────────

def append_event(workspace: Path, event: dict) -> None:
    """Append an event to .agentos/events/events.jsonl."""
    events_dir = _agentos_dir(workspace) / "events"
    events_dir.mkdir(exist_ok=True)
    with open(events_dir / "events.jsonl", "a") as f:
        f.write(json.dumps(event) + "\n")
