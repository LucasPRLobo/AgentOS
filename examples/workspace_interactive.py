#!/usr/bin/env python3
"""Interactive workspace session — the real AgentOS experience.

Usage:
    python examples/workspace_interactive.py <workspace.yaml>
    python examples/workspace_interactive.py examples/dashboard_design.yaml

Flow:
1. Load workspace config
2. Start workspace — board created, team registered
3. Coordinator (Claude Code) decomposes goal → you review tasks
4. You approve, modify, or add tasks
5. Workers execute autonomously
6. You review outputs, interact via board/messages
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
from agentos.workspace.schemas import BacklogTask, BacklogTaskStatus


def print_header(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_board(runtime: WorkspaceRuntime) -> None:
    print(runtime.board.render_compact(max_tokens=500))


def print_backlog(runtime: WorkspaceRuntime) -> None:
    tasks = runtime.backlog.get_all_tasks()
    if not tasks:
        print("  (empty)")
        return
    for i, t in enumerate(tasks):
        assigned = f" → {t.assigned_to}" if t.assigned_to else ""
        deps = f" [blocked by {len(t.depends_on)}]" if t.depends_on and t.status == "blocked" else ""
        print(f"  {i+1}. [{t.status:12s}] {t.title}{assigned}{deps}")
        if t.description:
            desc = t.description[:100].replace('\n', ' ')
            print(f"     {desc}{'...' if len(t.description) > 100 else ''}")


def print_files(workspace: Path) -> None:
    files = []
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and ".agentos" not in str(f) and "_coordinator" not in str(f) and "backlog" not in str(f):
            files.append(f)
    if not files:
        print("  (none)")
        return
    for f in files:
        print(f"  {f.relative_to(workspace)} ({f.stat().st_size:,} bytes)")


def prompt_user(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
        return answer if answer else default
    except (EOFError, KeyboardInterrupt):
        print("\nExiting.")
        sys.exit(0)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python examples/workspace_interactive.py <workspace.yaml>")
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
        print("ERROR: 'claude' CLI not found on PATH")
        sys.exit(1)

    # Setup
    tmpdir = Path(tempfile.mkdtemp(prefix="agentos_interactive_"))
    workspace = tmpdir / "workspace"
    workspace.mkdir()

    config = load_workspace_config(yaml_path)
    event_log = SQLiteEventLog(str(tmpdir / "workspace.db"))
    seq = SeqCounter()
    wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

    runtime = WorkspaceRuntime(config, event_log, seq, wf_id, workspace)

    # ================================================================
    # STEP 1: Show workspace config
    # ================================================================
    print_header("WORKSPACE CONFIG")
    print(f"  Name: {config.name}")
    print(f"  Goal: {config.goal.strip()[:200]}")
    print(f"  Team mode: {config.team_mode}")
    print(f"  Budget: ${config.budget.max_cost_usd or 'unlimited'}")
    print(f"\n  Team:")
    for p in config.team:
        roles = ", ".join(str(r) for r in p.roles)
        print(f"    - {p.name} ({p.type}, {roles})")
        if p.specialization:
            print(f"      {p.specialization[:80]}")
    if config.acceptance_criteria:
        print(f"\n  Acceptance criteria:")
        for c in config.acceptance_criteria:
            print(f"    - {c}")

    proceed = prompt_user("\nStart this workspace?", "yes")
    if proceed.lower() not in ("yes", "y", ""):
        print("Cancelled.")
        return

    # ================================================================
    # STEP 2: Start workspace
    # ================================================================
    runtime.start()
    print_header("WORKSPACE STARTED")
    print_board(runtime)

    # ================================================================
    # STEP 3: Coordinator decomposes goal
    # ================================================================
    print_header("COORDINATOR: DECOMPOSING GOAL")
    print("  Launching coordinator as Claude Code instance...")
    print("  The coordinator will read the goal and produce a task plan.\n")

    from agentos.workspace.coordinator_runner import run_decomposition

    tasks = run_decomposition(
        config=config,
        workspace=workspace,
        board=runtime.board,
        bus=runtime.bus,
        backlog=runtime.backlog,
        workflow_id=wf_id,
    )

    if not tasks:
        print("  Coordinator did not produce tasks.")
        print("  You can add tasks manually.\n")
    else:
        print(f"\n  Coordinator created {len(tasks)} tasks:\n")

    print_header("PROPOSED TASK PLAN")
    print_backlog(runtime)

    # ================================================================
    # STEP 4: Human reviews and modifies
    # ================================================================
    print()
    while True:
        action = prompt_user(
            "Action? (run / add <title> / remove <num> / board / quit)",
            "run",
        )

        if action.lower() in ("run", "r", ""):
            break
        elif action.lower() in ("quit", "q"):
            print("Cancelled.")
            return
        elif action.lower() in ("board", "b"):
            print_board(runtime)
        elif action.lower().startswith("add "):
            title = action[4:].strip()
            desc = prompt_user("  Description", "")
            suggested = prompt_user("  Assign to (agent name or empty)", "")
            task = BacklogTask(
                title=title,
                description=desc,
                created_by="human",
                suggested_for=suggested or None,
            )
            runtime.add_task(task)
            print(f"  Added: {title}")
            print_backlog(runtime)
        elif action.lower().startswith("remove "):
            try:
                idx = int(action.split()[1]) - 1
                all_tasks = runtime.backlog.get_all_tasks()
                if 0 <= idx < len(all_tasks):
                    runtime.backlog.cancel_task(all_tasks[idx].task_id, "removed by human")
                    print(f"  Removed: {all_tasks[idx].title}")
                else:
                    print("  Invalid task number.")
            except (ValueError, IndexError):
                print("  Usage: remove <number>")
        else:
            print("  Unknown command. Try: run, add <title>, remove <num>, board, quit")

    # ================================================================
    # STEP 5: Execute autonomously
    # ================================================================
    print_header("EXECUTING TASKS")
    print("  Workers are executing autonomously.")
    print("  Each agent will use MCP comms tools to read the board")
    print("  and communicate with the team.\n")

    result = await runtime.run(max_cycles=20, use_coordinator_agent=False)

    # ================================================================
    # STEP 6: Results
    # ================================================================
    print_header("EXECUTION COMPLETE")
    print(f"  Status: {'COMPLETE' if result.get('complete') else 'INCOMPLETE'}")
    print(f"  Reason: {result.get('reason', 'unknown')}")
    print(f"  Cycles: {result.get('cycles', 0)}")

    print_header("FINAL BOARD")
    print_board(runtime)

    print_header("FINAL BACKLOG")
    print_backlog(runtime)

    print_header("WORKSPACE FILES")
    print_files(workspace)

    # Show file contents
    for f in sorted(workspace.rglob("*")):
        if (
            f.is_file()
            and f.suffix in (".md", ".txt")
            and ".agentos" not in str(f)
            and "_coordinator" not in str(f)
            and "backlog" not in str(f)
        ):
            print_header(f"FILE: {f.relative_to(workspace)}")
            content = f.read_text()
            if len(content) > 1500:
                print(content[:1500])
                print(f"\n  ... ({len(content):,} chars total, truncated)")
            else:
                print(content)

    # ================================================================
    # STEP 7: Human review
    # ================================================================
    print_header("REVIEW")
    review = prompt_user("Satisfied with the output? (yes / no / comment)", "yes")

    if review.lower() in ("yes", "y", ""):
        runtime.complete()
        print("\n  Workspace marked as COMPLETED.")
    else:
        print(f"\n  Feedback noted: {review}")
        print("  In a full implementation, the coordinator would replan based on your feedback.")

    # Event log summary
    events = event_log.query(workflow_id=wf_id)
    type_counts: dict[str, int] = {}
    for e in events:
        t = str(e.event_type)
        type_counts[t] = type_counts.get(t, 0) + 1
    print_header("EVENT LOG")
    print(f"  Total events: {len(events)}")
    for t in sorted(type_counts):
        print(f"    {t}: {type_counts[t]}")

    print(f"\n  Workspace dir: {workspace}")
    print(f"  Database: {tmpdir / 'workspace.db'}")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
