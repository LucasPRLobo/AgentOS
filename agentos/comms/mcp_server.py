"""AgentOS Communication MCP Server.

Exposes workspace communication tools (board + direct messaging) to
Claude Code agents via the Model Context Protocol (stdio transport).

Claude Code spawns this server as a child process.  The server reads
comms state from ``.agentos/comms_state.json`` (written by the
orchestrator) and writes outgoing messages to ``.agentos/outbox/``.

Usage (registered by Tier 2 adapter automatically):
    claude mcp add --transport stdio agentos-comms -- \\
        python -m agentos.comms.mcp_server --workspace /path/to/workspace

Or via --mcp-config JSON:
    {"mcpServers": {"agentos-comms": {
        "command": "python",
        "args": ["-m", "agentos.comms.mcp_server", "--workspace", "/path"],
        "env": {}
    }}}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("agentos.comms.mcp")

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    logger.error(
        "MCP SDK not installed. Install with: pip install 'agentos[comms]'"
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "agentos-comms",
    instructions=(
        "AgentOS workspace communication tools. Use these to read the "
        "shared board, check for messages from teammates, send messages, "
        "and post findings to the board."
    ),
)

# Workspace path — set via CLI arg or env var
_workspace: Path | None = None


def _get_workspace() -> Path:
    global _workspace
    if _workspace is not None:
        return _workspace
    ws = os.environ.get("AGENTOS_WORKSPACE")
    if ws:
        _workspace = Path(ws)
        return _workspace
    # Fallback: current working directory
    _workspace = Path.cwd()
    return _workspace


def _read_state() -> dict:
    """Read comms state — prefers live board.json, falls back to legacy snapshot."""
    ws = _get_workspace()
    from agentos.comms.comms_state import read_board_file, read_comms_state

    # Try live board file first (concurrent mode)
    board_data = read_board_file(ws)
    if board_data is not None:
        # Read agent-specific inbox
        agent_id = os.environ.get("AGENTOS_AGENT_ID", "")
        inbox = []
        if agent_id:
            from agentos.comms.comms_state import read_agent_inbox
            inbox = read_agent_inbox(ws, agent_id)
        # Build compact board from full state
        compact = board_data.get("_compact", "[WORKSPACE BOARD]\n[END BOARD]")
        return {
            "agent_id": agent_id,
            "workflow_id": board_data.get("workflow_id", ""),
            "board_compact": compact,
            "board_full": board_data,
            "inbox": inbox,
        }

    # Fallback: legacy snapshot
    return read_comms_state(ws)


def _write_outbox(message: dict) -> str:
    """Write a message to the outbox."""
    from agentos.comms.comms_state import write_outbox_message
    path = write_outbox_message(_get_workspace(), message)
    return str(path.name)


# ---------------------------------------------------------------------------
# Board tools
# ---------------------------------------------------------------------------

@mcp.tool()
def read_board() -> str:
    """Read the workspace board — announcements, team status, recent posts, decisions, open questions, and alerts.

    Call this at the START of your work and periodically to stay aware of team
    activity and project context. The board is shared by all team members.
    """
    state = _read_state()
    return state.get("board_compact", "[WORKSPACE BOARD — v0]\n[END BOARD]")


@mcp.tool()
def post_to_board(
    content: str,
    section: str = "post",
    speech_act: str = "inform",
) -> str:
    """Post a message to the workspace board visible to ALL team members.

    Use this to share important findings, ask the team a question, or record
    a decision.

    Args:
        content: Your post content (natural language).
        section: Where to post — 'post' (general finding), 'question' (needs
                 team input), or 'decision' (records a choice made).
        speech_act: Intent — 'inform' (sharing a fact), 'request' (asking for
                    something), or 'propose' (suggesting a direction).
    """
    if section not in ("post", "question", "decision"):
        return f"Invalid section '{section}'. Use: post, question, decision."
    if speech_act not in ("inform", "request", "propose"):
        return f"Invalid speech_act '{speech_act}'. Use: inform, request, propose."

    state = _read_state()
    msg = {
        "to": "board",
        "content": content,
        "section": section,
        "speech_act": speech_act,
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    fname = _write_outbox(msg)
    return f"Posted to board [{section}] ({fname})"


# ---------------------------------------------------------------------------
# Direct messaging tools
# ---------------------------------------------------------------------------

@mcp.tool()
def check_messages() -> str:
    """Check for direct messages from team members and the human manager.

    Returns pending messages or 'No new messages.' Call this periodically
    and after completing major steps in your work.
    """
    state = _read_state()
    inbox = state.get("inbox", [])

    if not inbox:
        return "No new messages."

    parts = [f"You have {len(inbox)} message(s):\n"]
    for msg in inbox:
        sender = msg.get("sender_id", "unknown")
        sender_type = msg.get("sender_type", "agent")
        act = msg.get("speech_act", "inform")
        priority = msg.get("priority", "normal")
        content = msg.get("content", "")

        header = f"From: {sender} ({sender_type}) [{act}]"
        if priority in ("high", "critical"):
            header += f" [PRIORITY: {priority.upper()}]"
        parts.append(header)
        parts.append(content)
        if act == "request":
            parts.append("(Response expected — use send_message to reply.)")
        if act == "directive":
            parts.append("(This is a directive — you must follow it.)")
        parts.append("")

    return "\n".join(parts)


@mcp.tool()
def send_message(
    to: str,
    content: str,
    speech_act: str = "inform",
    priority: str = "normal",
) -> str:
    """Send a direct message to a team member or the human manager.

    Args:
        to: Recipient — use an agent name (e.g. 'research-agent') or 'human'.
        content: Your message content.
        speech_act: Intent — 'inform' (FYI, no response needed), 'request'
                    (need a response), or 'propose' (suggest a direction).
        priority: 'low', 'normal', or 'high'.
    """
    if speech_act not in ("inform", "request", "propose"):
        return f"Invalid speech_act '{speech_act}'. Use: inform, request, propose."
    if priority not in ("low", "normal", "high"):
        return f"Invalid priority '{priority}'. Use: low, normal, high."

    state = _read_state()
    msg = {
        "to": to,
        "content": content,
        "speech_act": speech_act,
        "priority": priority,
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    fname = _write_outbox(msg)
    return f"Message sent to {to} ({fname})"


# ---------------------------------------------------------------------------
# Protocol tools (P2.2 — structured exchanges)
# ---------------------------------------------------------------------------

@mcp.tool()
def request_consultation(expert: str, question: str) -> str:
    """Ask another agent for expert input.

    The system will track whether you receive a response. If no reply comes
    within the timeout, the question will be posted to the board automatically.

    Args:
        expert: The agent to consult (e.g. 'analysis-agent').
        question: Your question.
    """
    state = _read_state()
    msg = {
        "to": expert,
        "content": question,
        "speech_act": "request",
        "priority": "normal",
        "protocol": "consultation",
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    fname = _write_outbox(msg)
    return f"Consultation request sent to {expert} ({fname}). The system will track the response."


@mcp.tool()
def request_review(
    reviewer: str,
    artifact_path: str,
    criteria: str = "",
) -> str:
    """Submit your work for review by another agent or the human manager.

    Args:
        reviewer: Who should review — agent name or 'human'.
        artifact_path: Path to the file to review (relative to workspace).
        criteria: What to evaluate (e.g. 'factual accuracy, clarity').
    """
    state = _read_state()
    msg = {
        "to": reviewer,
        "content": f"Review requested for {artifact_path}. Criteria: {criteria or 'general quality'}",
        "speech_act": "request",
        "priority": "normal",
        "protocol": "review",
        "protocol_data": {
            "artifact_path": artifact_path,
            "criteria": criteria,
        },
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    fname = _write_outbox(msg)
    return f"Review request sent to {reviewer} for {artifact_path} ({fname})"


@mcp.tool()
def escalate(issue: str, context: str = "") -> str:
    """Escalate an issue you cannot resolve to the human manager.

    Use this when you are stuck, when agents disagree, or when a decision
    requires human judgment.

    Args:
        issue: What the problem is.
        context: Additional context (what you tried, why you're stuck).
    """
    state = _read_state()
    msg = {
        "to": "human",
        "content": f"ESCALATION: {issue}",
        "speech_act": "request",
        "priority": "high",
        "protocol": "escalation",
        "protocol_data": {
            "issue": issue,
            "context": context,
        },
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    fname = _write_outbox(msg)

    # Also post to board so team is aware
    board_msg = {
        "to": "board",
        "content": f"[ESCALATION from {state.get('agent_id', 'unknown')}] {issue}",
        "section": "alert",
        "speech_act": "alert",
        "sender_id": state.get("agent_id", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _write_outbox(board_msg)

    return f"Issue escalated to human manager ({fname}). Also posted to board."


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

@mcp.tool()
def report_progress(summary: str, activity: str = "") -> str:
    """Report what you're currently working on.

    Call this periodically to let the team and human know what you're doing.
    The supervisor and dashboard will display your progress.

    Args:
        summary: Brief description of current status (e.g., "Analyzing competitor dashboards")
        activity: Specific current activity (e.g., "Reading Linear's kanban implementation")
    """
    state = _read_state()
    agent_id = state.get("agent_id", "")
    if not agent_id:
        agent_id = os.environ.get("AGENTOS_AGENT_ID", "unknown")

    from agentos.comms.comms_state import write_agent_status
    write_agent_status(_get_workspace(), agent_id, {
        "agent_id": agent_id,
        "summary": summary,
        "activity": activity,
        "timestamp": datetime.now(UTC).isoformat(),
    })

    return f"Progress reported: {summary}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AgentOS Communication MCP Server")
    parser.add_argument(
        "--workspace", "-w",
        type=str,
        default=None,
        help="Workspace directory path (defaults to CWD or AGENTOS_WORKSPACE env)",
    )
    parser.add_argument(
        "--agent-id",
        type=str,
        default=None,
        help="Agent ID for this MCP server instance",
    )
    args = parser.parse_args()

    global _workspace
    if args.workspace:
        _workspace = Path(args.workspace)
    if args.agent_id:
        os.environ["AGENTOS_AGENT_ID"] = args.agent_id

    logger.info("AgentOS Comms MCP Server starting (workspace: %s, agent: %s)",
                _get_workspace(), args.agent_id or "unknown")
    mcp.run()


if __name__ == "__main__":
    main()
