#!/usr/bin/env python3
"""Autonomous workspace demo — runtime.run() handles everything.

Usage:
    python examples/workspace_auto_demo.py

This demonstrates the fully wired runtime:
1. Load workspace config from YAML
2. Call runtime.run() — that's it
3. Coordinator decomposes, workers execute, completion detected
"""

from __future__ import annotations

import asyncio
import json
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
        print("AgentOS Workspace — Autonomous Demo")
        print("=" * 60)
        print(f"Goal: {config.goal}")
        print(f"Team: {', '.join(p.name for p in config.team)}")
        print()

        # Add tasks manually (in production, coordinator does this via LLM)
        # We skip the LLM call for the demo to avoid extra cost.
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

        print(f"Backlog: {runtime.get_backlog_summary()}")
        print()

        # Run autonomously — this is the key line
        print("Running autonomously...")
        print("-" * 60)
        result = await runtime.run(max_cycles=10)
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
            if f.is_file() and ".agentos" not in str(f):
                print(f"  {f.relative_to(workspace)} ({f.stat().st_size} bytes)")

        # Show report
        report_file = workspace / "report.md"
        if report_file.exists():
            print(f"\n{'=' * 60}")
            print("REPORT")
            print("=" * 60)
            print(report_file.read_text()[:800])

        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
