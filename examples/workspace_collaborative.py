#!/usr/bin/env python3
"""Collaborative workspace — discussion-driven execution.

Usage:
    python examples/workspace_collaborative.py <workspace.yaml>
    python examples/workspace_collaborative.py examples/dashboard_design.yaml

The coordinator discusses with you at every decision point:
- Kickoff: asks about priorities before planning
- Task specs: proposes approach, you adjust
- Execution: agents work with MCP comms tools
- Review: coordinator presents output, you decide next steps
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


import threading
import time as _time

# Spinner for status messages
_spinner_active = False
_spinner_thread = None

def _spinner(message: str, verb: str):
    """Background spinner showing current activity."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while _spinner_active:
        frame = frames[i % len(frames)]
        print(f"\r  {frame} {verb}: {message}", end="", flush=True)
        _time.sleep(0.1)
        i += 1
    print(f"\r  ✓ {verb}: {message}" + " " * 20)


def start_spinner(message: str, verb: str = "Working"):
    global _spinner_active, _spinner_thread
    stop_spinner()
    _spinner_active = True
    _spinner_thread = threading.Thread(target=_spinner, args=(message, verb), daemon=True)
    _spinner_thread.start()


def stop_spinner():
    global _spinner_active, _spinner_thread
    if _spinner_active:
        _spinner_active = False
        if _spinner_thread:
            _spinner_thread.join(timeout=1)
        _spinner_thread = None


def status_callback(message: str, verb: str = "Working") -> None:
    """Show a spinner with the current activity."""
    stop_spinner()
    start_spinner(message, verb)


def human_input(prompt: str, options: list[str] | None = None) -> str:
    """Get input from the human via terminal."""
    stop_spinner()
    print()
    print("─" * 60)
    print(prompt)
    if options:
        print()
        for i, opt in enumerate(options):
            print(f"  {chr(97 + i)}) {opt}")
        print()
    try:
        response = input("  You: ").strip()
        print("─" * 60)
        return response
    except (EOFError, KeyboardInterrupt):
        print("\nExiting.")
        sys.exit(0)


def print_header(text: str) -> None:
    stop_spinner()
    print(f"\n{'═' * 60}")
    print(f"  {text}")
    print(f"{'═' * 60}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python examples/workspace_collaborative.py <workspace.yaml>")
        sys.exit(1)

    yaml_path = Path(sys.argv[1])
    if not yaml_path.exists():
        print(f"File not found: {yaml_path}")
        sys.exit(1)

    # Check claude CLI
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        print(f"Claude Code: {r.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: 'claude' CLI not found")
        sys.exit(1)

    # Setup
    tmpdir = Path(tempfile.mkdtemp(prefix="agentos_collab_"))
    workspace = tmpdir / "workspace"
    workspace.mkdir()

    config = load_workspace_config(yaml_path)
    event_log = SQLiteEventLog(str(tmpdir / "workspace.db"))
    seq = SeqCounter()
    wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

    # Detect project root (where the YAML lives, or current dir)
    project_dir = yaml_path.resolve().parent
    if (project_dir / "agentos").is_dir():
        pass  # YAML is in the project root
    elif (project_dir.parent / "agentos").is_dir():
        project_dir = project_dir.parent  # YAML is in examples/

    runtime = WorkspaceRuntime(config, event_log, seq, wf_id, workspace,
                                project_dir=project_dir)

    # Set callbacks — this is what makes it interactive
    runtime.set_human_input(human_input)
    runtime.set_status_callback(status_callback)

    # Start
    runtime.start()

    print_header("WORKSPACE STARTED")
    print(f"  Name: {config.name}")
    print(f"  Goal: {config.goal.strip()[:200]}")
    print(f"  Team: {', '.join(p.name for p in config.team)}")
    print(f"  Mode: {config.team_mode}")
    print()
    print(runtime.board.render_compact(max_tokens=300))

    # Run with discussions enabled
    print_header("RUNNING (interactive mode)")
    print("  The coordinator will discuss with you at each decision point.")
    print("  Answer questions, approve plans, and review outputs.")
    print()

    result = await runtime.run(
        max_cycles=20,
        use_coordinator_agent=True,
        interactive=True,
    )

    # Results
    stop_spinner()
    print_header("RESULT")
    print(f"  Complete: {result.get('complete')}")
    print(f"  Reason: {result.get('reason')}")
    print(f"  Cycles: {result.get('cycles')}")

    print_header("FINAL BOARD")
    print(runtime.board.render_compact(max_tokens=500))

    print_header("BACKLOG")
    for t in runtime.backlog.get_all_tasks():
        assigned = f" → {t.assigned_to}" if t.assigned_to else ""
        spec = f" [spec: {t.spec[:40]}...]" if t.spec else ""
        print(f"  [{t.status:14s}] {t.title}{assigned}{spec}")

    print_header("DISCUSSIONS")
    for d in runtime.discussions.get_all():
        decision = f" → {d.decision}" if d.decision else ""
        print(f"  [{d.status:8s}] {d.title}{decision}")

    print_header("FILES")
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and ".agentos" not in str(f) and "_coordinator" not in str(f) and "backlog" not in str(f):
            print(f"  {f.relative_to(workspace)} ({f.stat().st_size:,} bytes)")

    # Show project artifacts
    for name in ("PROJECT.md", "PLAN.md", "DECISIONS.md", "STATE.md"):
        fpath = workspace / name
        if fpath.exists():
            print_header(f"ARTIFACT: {name}")
            content = fpath.read_text()
            print(content[:800] if len(content) > 800 else content)

    print(f"\n  Workspace dir: {workspace}")
    print(f"  Database: {tmpdir / 'workspace.db'}")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
