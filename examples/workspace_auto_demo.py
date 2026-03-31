#!/usr/bin/env python3
"""Autonomous workspace demo — fully end-to-end with Claude Code coordinator.

Usage:
    python examples/workspace_auto_demo.py [--manual-tasks]

Without --manual-tasks (default):
    The coordinator runs as a Claude Code instance, reads the goal,
    decomposes it into tasks, and writes tasks.json. Workers then
    execute autonomously.

With --manual-tasks:
    Tasks are added manually (skips the coordinator LLM call).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.loader import load_workspace_config
from agentos.workspace.runtime import WorkspaceRuntime
from agentos.workspace.schemas import BacklogTask

DEMO_YAML = Path(__file__).parent / "workspace_demo.yaml"


async def main():
    manual_tasks = "--manual-tasks" in sys.argv

    # Check claude CLI
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        print(f"Using: {r.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: 'claude' CLI not found"); sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="agentos_auto_demo_") as tmpdir:
        tmpdir = Path(tmpdir)
        workspace = tmpdir / "workspace"
        workspace.mkdir()

        config = load_workspace_config(DEMO_YAML)
        event_log = SQLiteEventLog(str(tmpdir / "demo.db"))
        seq = SeqCounter()

        runtime = WorkspaceRuntime(config, event_log, seq, "ws-auto-demo", workspace)
        runtime.start()

        print("=" * 60)
        if manual_tasks:
            print("AgentOS Workspace — Autonomous Demo (manual tasks)")
        else:
            print("AgentOS Workspace — Full End-to-End Demo")
            print("Coordinator: Claude Code instance")
        print("=" * 60)
        print(f"Goal: {config.goal}")
        print(f"Team: {', '.join(p.name for p in config.team)}")
        print()

        if manual_tasks:
            # Add tasks manually (skip coordinator LLM call)
            tasks = [
                BacklogTask(
                    title="Research A2A Protocol",
                    description="Research Google's A2A protocol. Write findings to a2a_research.md.",
                    created_by="coordinator",
                    suggested_for="researcher",
                    estimated_minutes=10,
                    priority="high",
                ),
                BacklogTask(
                    title="Research MCP Protocol",
                    description="Research Anthropic's MCP protocol. Write findings to mcp_research.md.",
                    created_by="coordinator",
                    suggested_for="researcher",
                    estimated_minutes=10,
                    priority="high",
                ),
            ]
            research_ids = [runtime.add_task(t) for t in tasks]

            report = BacklogTask(
                title="Write Comparison Report",
                description="Compare A2A and MCP using the research files. Write report.md.",
                created_by="coordinator",
                suggested_for="writer",
                depends_on=research_ids,
                priority="normal",
            )
            runtime.add_task(report)
            runtime.backlog.recompute_priorities()
            print(f"Tasks added manually: {runtime.get_backlog_summary()}")
        else:
            print("Coordinator will decompose the goal using Claude Code...")

        print()

        # Run autonomously
        # use_coordinator_agent=True → coordinator is a Claude Code instance
        # use_coordinator_agent=False → would need coordinator_llm callable
        print("Running autonomously...")
        print("-" * 60)
        result = await runtime.run(
            max_cycles=15,
            use_coordinator_agent=not manual_tasks,
        )
        print("-" * 60)

        # Results
        print(f"\nResult: {result}")

        print(f"\n{'=' * 60}")
        print("FINAL BOARD")
        print("=" * 60)
        print(runtime.board.render_compact(max_tokens=500))

        print(f"\n{'=' * 60}")
        print("BACKLOG")
        print("=" * 60)
        for t in runtime.backlog.get_all_tasks():
            assigned = f" → {t.assigned_to}" if t.assigned_to else ""
            print(f"  [{t.status:12s}] {t.title}{assigned}")

        print(f"\n{'=' * 60}")
        print("FILES")
        print("=" * 60)
        for f in sorted(workspace.rglob("*")):
            if f.is_file() and ".agentos" not in str(f) and "_coordinator_output" not in str(f):
                print(f"  {f.relative_to(workspace)} ({f.stat().st_size} bytes)")

        # Show report or any produced files
        for name in ("report.md", "a2a_research.md", "mcp_research.md"):
            fpath = workspace / name
            if fpath.exists():
                print(f"\n{'=' * 60}")
                print(f"{name.upper()}")
                print("=" * 60)
                print(fpath.read_text()[:500])

        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
