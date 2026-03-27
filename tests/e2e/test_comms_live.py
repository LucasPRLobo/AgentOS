"""Live end-to-end test for the communication system with real Claude Code agents.

Run with:
    python -m pytest tests/e2e/test_comms_live.py -v -s --timeout=120

Requires ANTHROPIC_API_KEY to be set.

This test launches two sequential Tier 2 (Claude Code) agents:
  1. Research Agent — reads the board, finds a message in its inbox,
     posts a finding to the board, and writes a reply to the outbox.
  2. Analysis Agent — reads the updated board (which now has Research's
     finding), reads its own inbox, and produces a final summary.

A human directive is injected into Agent 1's inbox before launch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


pytestmark = [
    pytest.mark.e2e,
]


def _run_claude(prompt: str, workspace: Path, max_turns: int = 5) -> str:
    """Launch Claude Code with --print and return raw output."""
    comms_prompt = write_comms_prompt_addition()
    full_prompt = prompt + comms_prompt

    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Agent,TodoWrite,ToolSearch",
        "-p", full_prompt,
    ]

    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout


class TestCommsLiveE2E:
    """Two-agent sequential workflow testing board + direct messaging."""

    def test_two_agent_comms(self, tmp_path):
        # --- Setup infrastructure ---
        db_path = str(tmp_path / "comms_test.db")
        event_log = SQLiteEventLog(db_path)
        seq = SeqCounter()
        workflow_id = "wf-comms-live-test"

        board = BoardManager(event_log, seq, workflow_id)
        bus = MessageBus(event_log, seq, workflow_id)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # --- Setup initial board state ---
        board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="human",
            author_id="human-manager",
            content="Project goal: Research and summarize the concept of 'agent communication protocols'. Focus on A2A and MCP.",
            speech_act=SpeechAct.DIRECTIVE,
            pinned=True,
        ))
        board.update_agent_status(AgentStatus(
            agent_id="research-agent",
            agent_name="Research Agent",
            role="Researcher",
            state="pending",
        ))
        board.update_agent_status(AgentStatus(
            agent_id="analysis-agent",
            agent_name="Analysis Agent",
            role="Analyst",
            state="pending",
        ))

        # --- Human sends a directive to research agent ---
        human_msg = DirectMessage(
            sender_type="human",
            sender_id="human-manager",
            recipient_type="agent",
            recipient_id="research-agent",
            content="Focus specifically on how A2A and MCP complement each other. Keep your finding brief — 2-3 sentences max.",
            speech_act=SpeechAct.DIRECTIVE,
            priority=MessagePriority.HIGH,
            workflow_id=workflow_id,
        )
        bus.send(human_msg)

        # === AGENT 1: Research Agent ===
        print("\n=== Launching Research Agent ===")
        board.update_agent_status(AgentStatus(
            agent_id="research-agent", agent_name="Research Agent",
            role="Researcher", state="running",
        ))

        # Write board + inbox to workspace
        write_board_state(workspace, board)
        pending = bus.receive("research-agent")
        write_inbox(workspace, pending)

        research_output = _run_claude(
            prompt=(
                "You are a Research Agent on a team. Your task is to write a brief "
                "research finding about AI agent communication protocols.\n\n"
                "IMPORTANT INSTRUCTIONS:\n"
                "1. First, read .agentos/board.md to see the project context\n"
                "2. Check .agentos/inbox/ for messages from your manager\n"
                "3. Write your finding (2-3 sentences) to a file: finding.md\n"
                "4. Post your key finding to the board by writing a JSON file to "
                ".agentos/outbox/finding.json with format: "
                '{"to": "board", "content": "your finding summary", "section": "post"}\n'
                "5. Send a message to the Analysis Agent by writing another JSON file to "
                ".agentos/outbox/to-analyst.json with format: "
                '{"to": "analysis-agent", "content": "brief message about what you found"}\n'
                "6. Create manifest.json with your summary and findings.\n"
            ),
            workspace=workspace,
            max_turns=8,
        )

        print(f"Research Agent output length: {len(research_output)} chars")

        # Read outbox — route messages
        outbox_msgs = read_outbox(workspace)
        print(f"Research Agent outbox messages: {len(outbox_msgs)}")
        for msg_data in outbox_msgs:
            print(f"  → to={msg_data.get('to')}: {msg_data.get('content', '')[:80]}")
            if msg_data.get("to") == "board":
                board.post(BoardPost(
                    section=BoardSection(msg_data.get("section", "post")),
                    author_type="agent",
                    author_id="research-agent",
                    content=msg_data["content"],
                    speech_act=SpeechAct.INFORM,
                ))
            else:
                bus.send(DirectMessage(
                    sender_type="agent",
                    sender_id="research-agent",
                    recipient_type="agent",
                    recipient_id=msg_data["to"],
                    content=msg_data["content"],
                    speech_act=SpeechAct(msg_data.get("speech_act", "inform")),
                    workflow_id=workflow_id,
                ))

        board.update_agent_status(AgentStatus(
            agent_id="research-agent", agent_name="Research Agent",
            role="Researcher", state="succeeded",
        ))

        # Check research agent produced something
        finding_file = workspace / "finding.md"
        finding_exists = finding_file.exists()
        print(f"finding.md exists: {finding_exists}")
        if finding_exists:
            print(f"finding.md content: {finding_file.read_text()[:200]}")

        # === AGENT 2: Analysis Agent ===
        print("\n=== Launching Analysis Agent ===")
        board.update_agent_status(AgentStatus(
            agent_id="analysis-agent", agent_name="Analysis Agent",
            role="Analyst", state="running",
        ))

        # Clear workspace for agent 2 (but keep finding.md)
        for f in (workspace / ".agentos" / "inbox").glob("msg-*"):
            f.unlink()
        for f in (workspace / ".agentos" / "outbox").glob("*.json"):
            f.unlink()
        manifest = workspace / "manifest.json"
        if manifest.exists():
            manifest.unlink()

        # Write updated board + inbox for analysis agent
        write_board_state(workspace, board)
        pending_for_analyst = bus.receive("analysis-agent")
        write_inbox(workspace, pending_for_analyst)

        analysis_output = _run_claude(
            prompt=(
                "You are an Analysis Agent on a team. Your task is to review "
                "the Research Agent's finding and write a brief analysis.\n\n"
                "IMPORTANT INSTRUCTIONS:\n"
                "1. Read .agentos/board.md to see the project context and research findings\n"
                "2. Check .agentos/inbox/ for messages from the Research Agent\n"
                "3. If finding.md exists, read it\n"
                "4. Write a brief analysis (2-3 sentences) to analysis.md\n"
                "5. Post your conclusion to the board by writing to "
                ".agentos/outbox/conclusion.json: "
                '{"to": "board", "content": "your conclusion", "section": "decision"}\n'
                "6. Create manifest.json with your summary.\n"
            ),
            workspace=workspace,
            max_turns=8,
        )

        print(f"Analysis Agent output length: {len(analysis_output)} chars")

        # Read outbox
        outbox_msgs_2 = read_outbox(workspace)
        print(f"Analysis Agent outbox messages: {len(outbox_msgs_2)}")
        for msg_data in outbox_msgs_2:
            print(f"  → to={msg_data.get('to')}: {msg_data.get('content', '')[:80]}")
            if msg_data.get("to") == "board":
                board.post(BoardPost(
                    section=BoardSection(msg_data.get("section", "post")),
                    author_type="agent",
                    author_id="analysis-agent",
                    content=msg_data["content"],
                ))

        # === Verify results ===
        print("\n=== Final Board State ===")
        final_board = board.render_compact(max_tokens=500)
        print(final_board)

        print("\n=== Event Log ===")
        all_events = event_log.query(workflow_id=workflow_id)
        event_types = [e.event_type for e in all_events]
        print(f"Total events: {len(all_events)}")
        for et in sorted(set(str(t) for t in event_types)):
            count = sum(1 for t in event_types if str(t) == et)
            print(f"  {et}: {count}")

        # --- Assertions ---
        # Board should have the original announcement + at least one agent post
        state = board.get_state()
        assert len(state.announcements) >= 1, "Board should have pinned announcement"

        total_posts = (
            len(state.recent_posts) + len(state.decisions) +
            len(state.announcements) + len(state.open_questions)
        )
        assert total_posts >= 2, (
            f"Board should have at least 2 posts (announcement + agent post), "
            f"got {total_posts}"
        )

        # Event log should have board and message events
        assert any(
            str(t) == "board.post_created" for t in event_types
        ), "Should have board.post_created events"

        assert any(
            str(t) == "direct_message.sent" for t in event_types
        ), "Should have direct_message.sent events"

        # At least one workspace file should exist
        analysis_file = workspace / "analysis.md"
        assert finding_exists or analysis_file.exists(), (
            "At least one agent should have produced a file"
        )

        print("\n=== TEST PASSED ===")
