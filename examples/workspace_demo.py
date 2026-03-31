#!/usr/bin/env python3
"""Live demo: workspace runtime with coordinator, workers, and board.

Usage:
    python examples/workspace_demo.py

This demonstrates the full workspace flow:
1. Load workspace config from YAML
2. Coordinator decomposes the goal into tasks (posted to board)
3. Workers claim tasks and execute them (real Claude Code agents)
4. Board updates throughout — findings, status, completion
5. Completion detector assesses whether the goal is met

Requires: `claude` CLI authenticated and available on PATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.adapters.tier2_shared import (
    read_outbox,
    write_board_state,
    write_comms_prompt_addition,
    write_inbox,
)
from agentos.comms.board_manager import BoardManager
from agentos.comms.comms_state import write_comms_state
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import BoardPost, BoardSection, DirectMessage, SpeechAct
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.completion import CompletionDetector
from agentos.workspace.context_summary import ContextSummaryManager
from agentos.workspace.cost_tracker import CostTracker
from agentos.workspace.loader import load_workspace_config
from agentos.workspace.runtime import WorkspaceRuntime
from agentos.workspace.schemas import (
    BacklogTask,
    BacklogTaskStatus,
    WorkspaceParticipant,
)

DEMO_YAML = Path(__file__).parent / "workspace_demo.yaml"


def run_claude(prompt: str, workspace: Path, max_turns: int = 8) -> str:
    """Launch Claude Code with comms prompt and MCP server."""
    comms_addition = (
        "\n\n## Team Communication\n"
        "You have MCP tools for team communication:\n"
        "- **read_board**: See the shared workspace board\n"
        "- **post_to_board**: Share findings with the team\n"
        "- **check_messages**: Check for messages from teammates\n"
        "- **send_message**: Send a message to a teammate\n\n"
        "Call read_board at the START. Post important findings to the board.\n"
    )
    full_prompt = prompt + comms_addition

    cmd = [
        "claude", "--print",
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Agent,TodoWrite,ToolSearch",
    ]

    # Add MCP comms server
    mcp_config = json.dumps({
        "mcpServers": {
            "agentos-comms": {
                "command": sys.executable,
                "args": ["-m", "agentos.comms.mcp_server", "--workspace", str(workspace)],
                "env": {},
            }
        }
    })
    cmd.extend(["--mcp-config", mcp_config, "-p", full_prompt])

    result = subprocess.run(cmd, cwd=str(workspace), capture_output=True, text=True, timeout=180)
    if result.returncode != 0 and result.stderr:
        print(f"  stderr: {result.stderr[:300]}")
    return result.stdout


def route_outbox(workspace, board, bus, sender_id, workflow_id):
    """Route outbox messages through the comms system."""
    from agentos.comms.schemas import DirectMessage as DM, MessagePriority as MP, SpeechAct as SA
    outbox_msgs = read_outbox(workspace)
    for msg_data in outbox_msgs:
        target = msg_data.get("to", "")
        content = msg_data.get("content", "")
        if not content:
            continue
        if target == "board":
            board.post(BoardPost(
                section=BoardSection(msg_data.get("section", "post")),
                author_type="agent", author_id=sender_id,
                content=content, speech_act=SA.INFORM,
            ))
            print(f"    → Board: {content[:80]}")
        else:
            bus.send(DM(
                sender_type="agent", sender_id=sender_id,
                recipient_type="human" if target == "human" else "agent",
                recipient_id=target, content=content,
                speech_act=SA(msg_data.get("speech_act", "inform")),
                workflow_id=workflow_id,
            ))
            print(f"    → {target}: {content[:80]}")
    return len(outbox_msgs)


def main():
    # Check claude is available
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        print(f"Using: {r.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: 'claude' CLI not found"); sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="agentos_workspace_demo_") as tmpdir:
        tmpdir = Path(tmpdir)
        workspace = tmpdir / "workspace"
        workspace.mkdir()

        # --- Load config ---
        config = load_workspace_config(DEMO_YAML)

        # --- Initialize runtime ---
        db = str(tmpdir / "demo.db")
        event_log = SQLiteEventLog(db)
        seq = SeqCounter()
        workflow_id = "ws-demo"

        runtime = WorkspaceRuntime(config, event_log, seq, workflow_id, workspace)
        runtime.start()

        summary_mgr = ContextSummaryManager(workspace)
        cost_tracker = CostTracker(config.budget)
        completion = CompletionDetector(config, runtime.backlog)

        print("=" * 60)
        print("AgentOS Workspace Runtime — Live Demo")
        print("=" * 60)
        print(f"Goal: {config.goal}")
        print(f"Team: {', '.join(p.name for p in config.team)}")
        print(f"Mode: {config.team_mode}")
        print()

        # --- Coordinator decomposes goal (manual simulation) ---
        # In production, the CoordinatorAgent does this via LLM.
        # For this demo, we create tasks directly.
        print("[Coordinator] Decomposing goal into tasks...")

        tasks = [
            BacklogTask(
                title="Research A2A Protocol",
                description="Research Google's Agent-to-Agent (A2A) protocol. "
                    "Focus on: architecture, message format, discovery mechanism, "
                    "task lifecycle, and streaming support. Write findings to a2a_research.md.",
                created_by="coordinator",
                suggested_for="researcher",
                acceptance_criteria=["a2a_research.md produced with key findings"],
                estimated_minutes=10,
                priority="high",
            ),
            BacklogTask(
                title="Research MCP Protocol",
                description="Research Anthropic's Model Context Protocol (MCP). "
                    "Focus on: architecture, tool/resource/prompt primitives, "
                    "transport options, and ecosystem adoption. Write findings to mcp_research.md.",
                created_by="coordinator",
                suggested_for="researcher",
                acceptance_criteria=["mcp_research.md produced with key findings"],
                estimated_minutes=10,
                priority="high",
            ),
        ]

        # Research tasks are independent
        research_ids = []
        for task in tasks:
            tid = runtime.add_task(task)
            research_ids.append(tid)
            print(f"  Task: {task.title} → {task.suggested_for}")

        # Report task depends on both research tasks
        report_task = BacklogTask(
            title="Write Comparison Report",
            description="Using the research findings from a2a_research.md and mcp_research.md, "
                "write a concise comparison report (report.md) covering: "
                "how A2A and MCP complement each other, key differences, "
                "and when to use each. Keep it under 500 words.",
            created_by="coordinator",
            suggested_for="writer",
            depends_on=research_ids,
            acceptance_criteria=["report.md produced", "Covers both protocols"],
            estimated_minutes=10,
            priority="normal",
        )
        report_id = runtime.add_task(report_task)
        print(f"  Task: {report_task.title} → {report_task.suggested_for} (depends on research)")

        completion.set_initial_task_count(3)

        print(f"\nBacklog: {runtime.get_backlog_summary()}")
        print()

        # --- Execute research tasks in parallel ---
        for i, tid in enumerate(research_ids):
            task = runtime.backlog.get_task(tid)
            print(f"{'=' * 60}")
            print(f"WORKER: researcher — {task.title}")
            print(f"{'=' * 60}")

            runtime.claim_task(tid, "researcher")
            runtime.backlog.start_task(tid)

            # Write comms state
            pending = runtime.bus.receive("researcher")
            write_comms_state(workspace, runtime.board, pending, "researcher", workflow_id)
            write_board_state(workspace, runtime.board)

            # Clean outbox from prior run
            outbox_dir = workspace / ".agentos" / "outbox"
            if outbox_dir.exists():
                for f in outbox_dir.glob("*.json"):
                    f.unlink()
            # Clean prior manifest
            manifest = workspace / "manifest.json"
            if manifest.exists():
                manifest.unlink()

            output = run_claude(
                prompt=f"You are a research agent. Your task:\n\n{task.description}\n\n"
                    f"Write your findings to the specified file. "
                    f"Use read_board to see the project context. "
                    f"Post your key finding to the board when done.",
                workspace=workspace,
                max_turns=8,
            )

            n = route_outbox(workspace, runtime.board, runtime.bus, "researcher", workflow_id)
            print(f"  Outbox: {n} message(s) routed")

            # Collect output
            task_output = {"summary": f"Research complete: {task.title}"}
            runtime.complete_task(tid, task_output)
            summary_mgr.update_agent_summary("researcher", task_output, task.title)

            print(f"  Status: DONE\n")

        # --- Report task should now be unblocked ---
        report = runtime.backlog.get_task(report_id)
        print(f"Report task status: {report.status}")
        assert report.status == BacklogTaskStatus.OPEN, f"Expected OPEN, got {report.status}"

        print(f"\n{'=' * 60}")
        print(f"WORKER: writer — {report_task.title}")
        print(f"{'=' * 60}")

        runtime.claim_task(report_id, "writer")
        runtime.backlog.start_task(report_id)

        pending = runtime.bus.receive("writer")
        write_comms_state(workspace, runtime.board, pending, "writer", workflow_id)
        write_board_state(workspace, runtime.board)

        outbox_dir = workspace / ".agentos" / "outbox"
        if outbox_dir.exists():
            for f in outbox_dir.glob("*.json"):
                f.unlink()
        manifest = workspace / "manifest.json"
        if manifest.exists():
            manifest.unlink()

        output = run_claude(
            prompt=f"You are a technical writer. Your task:\n\n{report_task.description}\n\n"
                f"Read the research files (a2a_research.md, mcp_research.md) and "
                f"the board for context. Write report.md. "
                f"Post your conclusion to the board when done.",
            workspace=workspace,
            max_turns=8,
        )

        n = route_outbox(workspace, runtime.board, runtime.bus, "writer", workflow_id)
        print(f"  Outbox: {n} message(s) routed")

        task_output = {"summary": "Comparison report written"}
        runtime.complete_task(report_id, task_output)
        summary_mgr.update_agent_summary("writer", task_output, report_task.title)
        print(f"  Status: DONE\n")

        # --- Check completion ---
        print(f"{'=' * 60}")
        print("COMPLETION CHECK")
        print(f"{'=' * 60}")

        result = completion.check()
        print(f"Complete: {result.complete}")
        print(f"Reason: {result.reason}")
        print(f"Recommendation: {result.recommendation}")

        # --- Final board ---
        print(f"\n{'=' * 60}")
        print("FINAL BOARD STATE")
        print(f"{'=' * 60}")
        print(runtime.board.render_compact(max_tokens=500))

        # --- Workspace files ---
        print(f"\n{'=' * 60}")
        print("WORKSPACE FILES")
        print(f"{'=' * 60}")
        for f in sorted(workspace.rglob("*")):
            if f.is_file() and ".agentos" not in str(f):
                size = f.stat().st_size
                print(f"  {f.relative_to(workspace)} ({size} bytes)")

        # --- Backlog ---
        print(f"\n{'=' * 60}")
        print("BACKLOG SUMMARY")
        print(f"{'=' * 60}")
        for t in runtime.backlog.get_all_tasks():
            assigned = f" → {t.assigned_to}" if t.assigned_to else ""
            print(f"  [{t.status:12s}] {t.title}{assigned}")

        # --- Event log ---
        print(f"\n{'=' * 60}")
        print("EVENT LOG")
        print(f"{'=' * 60}")
        events = event_log.query(workflow_id=workflow_id)
        type_counts: dict[str, int] = {}
        for e in events:
            t = str(e.event_type)
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"Total events: {len(events)}")
        for t in sorted(type_counts):
            print(f"  {t}: {type_counts[t]}")

        # --- Show report if produced ---
        report_file = workspace / "report.md"
        if report_file.exists():
            print(f"\n{'=' * 60}")
            print("REPORT (report.md)")
            print(f"{'=' * 60}")
            print(report_file.read_text()[:1000])

        print("\nDone.")


if __name__ == "__main__":
    main()
