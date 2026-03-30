#!/usr/bin/env python3
"""Live demo: two Claude Code agents communicating via the Board + Direct Messaging.

Usage:
    python examples/comms_demo.py

Requires:
    - ANTHROPIC_API_KEY set in environment
    - `claude` CLI available on PATH

What happens:
    1. A workspace is created with a board and a human directive
    2. Research Agent launches, reads the board + inbox, produces a finding,
       posts to the board, and sends a message to the Analysis Agent
    3. Analysis Agent launches, reads the updated board + Research's message,
       writes an analysis, and posts a conclusion to the board
    4. The final board state and full event log are printed
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.adapters.tier2_shared import (
    read_outbox,
    write_board_state,
    write_comms_prompt_addition,
    write_inbox,
)
from agentos.comms.board_manager import BoardManager
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter


def run_claude(prompt: str, workspace: Path, max_turns: int = 8,
               use_mcp: bool = True) -> str:
    """Launch Claude Code and return raw output.

    When *use_mcp* is True, injects the AgentOS comms MCP server so the
    agent has read_board, post_to_board, check_messages, send_message
    tools available during execution.
    """
    comms_addition = (
        "\n\n## Team Communication\n"
        "You have MCP tools for team communication:\n"
        "- **read_board**: See the shared workspace board\n"
        "- **post_to_board**: Share findings, ask questions, record decisions\n"
        "- **check_messages**: Check for direct messages from teammates\n"
        "- **send_message**: Send a direct message to a teammate or 'human'\n"
        "- **request_consultation**: Ask an expert for input\n"
        "- **request_review**: Submit work for review\n"
        "- **escalate**: Escalate an issue to the human manager\n\n"
        "Call read_board at the START. Call check_messages periodically.\n"
        "When you discover something important, post_to_board.\n"
    )
    full_prompt = prompt + comms_addition

    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Agent,TodoWrite,ToolSearch",
    ]

    # Inject MCP comms server
    if use_mcp:
        mcp_config = json.dumps({
            "mcpServers": {
                "agentos-comms": {
                    "command": sys.executable,
                    "args": ["-m", "agentos.comms.mcp_server", "--workspace", str(workspace)],
                    "env": {},
                }
            }
        })
        cmd.extend(["--mcp-config", mcp_config])

    cmd.extend(["-p", full_prompt])

    print(f"  Running: claude --print (max_turns={max_turns}, mcp={'yes' if use_mcp else 'no'})")
    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0 and result.stderr:
        print(f"  stderr: {result.stderr[:500]}")
    return result.stdout


def route_outbox(workspace: Path, board: BoardManager, bus: MessageBus,
                  sender_id: str, workflow_id: str) -> int:
    """Read outbox files and route them through the comms system."""
    outbox_msgs = read_outbox(workspace)
    for msg_data in outbox_msgs:
        target = msg_data.get("to", "")
        content = msg_data.get("content", "")
        if target == "board":
            board.post(BoardPost(
                section=BoardSection(msg_data.get("section", "post")),
                author_type="agent",
                author_id=sender_id,
                content=content,
                speech_act=SpeechAct.INFORM,
            ))
            print(f"  → Board post: {content[:80]}")
        else:
            bus.send(DirectMessage(
                sender_type="agent",
                sender_id=sender_id,
                recipient_type="agent",
                recipient_id=target,
                content=content,
                speech_act=SpeechAct(msg_data.get("speech_act", "inform")),
                workflow_id=workflow_id,
            ))
            print(f"  → Message to {target}: {content[:80]}")
    return len(outbox_msgs)


def main():
    # Check claude CLI is available and authenticated
    try:
        result = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print("ERROR: 'claude' CLI not working")
            sys.exit(1)
        print(f"Using: {result.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: 'claude' CLI not found on PATH")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="agentos_comms_demo_") as tmpdir:
        tmpdir = Path(tmpdir)

        # --- Infrastructure ---
        db_path = str(tmpdir / "demo.db")
        event_log = SQLiteEventLog(db_path)
        seq = SeqCounter()
        workflow_id = "wf-comms-demo"
        board = BoardManager(event_log, seq, workflow_id)
        bus = MessageBus(event_log, seq, workflow_id)
        workspace = tmpdir / "workspace"
        workspace.mkdir()

        print("=" * 60)
        print("AgentOS Communication System — Live Demo")
        print("=" * 60)

        # --- Setup board ---
        print("\n[Setup] Creating board with project context...")
        board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="human",
            author_id="human-manager",
            content=(
                "Project: Summarize how AI agent communication protocols work. "
                "Focus on Google A2A and Anthropic MCP — how they complement each other."
            ),
            speech_act=SpeechAct.DIRECTIVE,
            pinned=True,
        ))
        board.update_agent_status(AgentStatus(
            agent_id="research-agent", agent_name="Research Agent",
            role="Researcher", state="pending",
        ))
        board.update_agent_status(AgentStatus(
            agent_id="analysis-agent", agent_name="Analysis Agent",
            role="Analyst", state="pending",
        ))
        print("  Board created with project announcement and team roster.")

        # --- Human directive to research agent ---
        print("[Setup] Sending human directive to Research Agent...")
        bus.send(DirectMessage(
            sender_type="human",
            sender_id="human-manager",
            recipient_type="agent",
            recipient_id="research-agent",
            content=(
                "Keep your research finding concise — 2-3 sentences max. "
                "The key point is how A2A handles agent-to-agent while MCP handles agent-to-tool."
            ),
            speech_act=SpeechAct.DIRECTIVE,
            priority=MessagePriority.HIGH,
            workflow_id=workflow_id,
        ))

        # ============================================================
        # AGENT 1: Research Agent
        # ============================================================
        print("\n" + "=" * 60)
        print("AGENT 1: Research Agent")
        print("=" * 60)

        board.update_agent_status(AgentStatus(
            agent_id="research-agent", agent_name="Research Agent",
            role="Researcher", state="running",
        ))

        # Write comms state (board + inbox) before launch
        from agentos.comms.comms_state import write_comms_state
        pending = bus.receive("research-agent")
        write_comms_state(workspace, board, pending, "research-agent", workflow_id)
        write_board_state(workspace, board)  # Also write board.md for fallback
        write_inbox(workspace, pending)
        print(f"  Inbox: {len(pending)} message(s)")

        research_output = run_claude(
            prompt=(
                "You are a Research Agent. Write a brief research finding about "
                "AI agent communication protocols (A2A and MCP).\n\n"
                "Steps:\n"
                "1. Use the read_board tool to see the project context\n"
                "2. Use check_messages to see messages from your manager\n"
                "3. Write your finding (2-3 sentences) to finding.md\n"
                "4. Use post_to_board to share your finding with the team\n"
                "5. Use send_message to tell the analysis-agent about your finding\n"
                "6. Write manifest.json summarizing your work.\n"
            ),
            workspace=workspace,
        )

        # Route outbox
        n = route_outbox(workspace, board, bus, "research-agent", workflow_id)
        print(f"  Outbox: {n} message(s) routed")

        # Check outputs
        finding = workspace / "finding.md"
        if finding.exists():
            print(f"  finding.md: {finding.read_text().strip()[:200]}")
        else:
            print("  finding.md: NOT CREATED")

        board.update_agent_status(AgentStatus(
            agent_id="research-agent", agent_name="Research Agent",
            role="Researcher", state="succeeded",
        ))

        # ============================================================
        # AGENT 2: Analysis Agent
        # ============================================================
        print("\n" + "=" * 60)
        print("AGENT 2: Analysis Agent")
        print("=" * 60)

        board.update_agent_status(AgentStatus(
            agent_id="analysis-agent", agent_name="Analysis Agent",
            role="Analyst", state="running",
        ))

        # Clean inbox/outbox for agent 2, keep finding.md
        inbox_dir = workspace / ".agentos" / "inbox"
        if inbox_dir.exists():
            for f in inbox_dir.glob("msg-*"):
                f.unlink()
        manifest = workspace / "manifest.json"
        if manifest.exists():
            manifest.unlink()

        # Write updated comms state for analyst
        pending_analyst = bus.receive("analysis-agent")
        write_comms_state(workspace, board, pending_analyst, "analysis-agent", workflow_id)
        write_board_state(workspace, board)
        write_inbox(workspace, pending_analyst)
        print(f"  Inbox: {len(pending_analyst)} message(s)")

        analysis_output = run_claude(
            prompt=(
                "You are an Analysis Agent reviewing the Research Agent's work.\n\n"
                "Steps:\n"
                "1. Use read_board to see the project context and research findings\n"
                "2. Use check_messages for messages from the Research Agent\n"
                "3. Read finding.md if it exists\n"
                "4. Write a brief analysis (2-3 sentences) to analysis.md\n"
                "5. Use post_to_board with section='decision' to share your conclusion\n"
                "6. Write manifest.json summarizing your work.\n"
            ),
            workspace=workspace,
        )

        n2 = route_outbox(workspace, board, bus, "analysis-agent", workflow_id)
        print(f"  Outbox: {n2} message(s) routed")

        analysis = workspace / "analysis.md"
        if analysis.exists():
            print(f"  analysis.md: {analysis.read_text().strip()[:200]}")
        else:
            print("  analysis.md: NOT CREATED")

        board.update_agent_status(AgentStatus(
            agent_id="analysis-agent", agent_name="Analysis Agent",
            role="Analyst", state="succeeded",
        ))

        # ============================================================
        # Results
        # ============================================================
        print("\n" + "=" * 60)
        print("FINAL BOARD STATE")
        print("=" * 60)
        print(board.render_compact(max_tokens=500))

        print("\n" + "=" * 60)
        print("EVENT LOG SUMMARY")
        print("=" * 60)
        all_events = event_log.query(workflow_id=workflow_id)
        type_counts: dict[str, int] = {}
        for e in all_events:
            t = str(e.event_type)
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"Total events: {len(all_events)}")
        for t in sorted(type_counts):
            print(f"  {t}: {type_counts[t]}")

        print("\n" + "=" * 60)
        print("WORKSPACE FILES")
        print("=" * 60)
        for f in sorted(workspace.rglob("*")):
            if f.is_file() and ".agentos" not in str(f):
                print(f"  {f.relative_to(workspace)}")

        print("\nDone.")


if __name__ == "__main__":
    main()
