#!/usr/bin/env python3
"""Live workspace — concurrent agents with human participation.

Usage:
    python examples/workspace_live.py <workspace.yaml>

This is the real AgentOS experience:
- Agents run concurrently in the background
- The board updates in real-time as agents work
- You can post, message, claim tasks, create tasks at any time
- The coordinator watches and adapts the team
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos.comms.comms_state import (
    read_board_file,
    read_human_inbox,
    write_human_command,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.loader import load_workspace_config
from agentos.workspace.runtime import WorkspaceRuntime
from agentos.workspace.schemas import SupervisorConfig

# ── Terminal helpers ────────────────────────────────────────────────

CLEAR_LINE = "\033[2K\r"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"


def _short(text: str, max_len: int = 80) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


# ── Event display ──────────────────────────────────────────────────

_events: list[dict] = []
_events_lock = threading.Lock()


def on_event(event: dict):
    """Called by supervisor for every event."""
    with _events_lock:
        _events.append(event)
        if len(_events) > 200:
            _events[:] = _events[-100:]


def format_event(e: dict) -> str:
    """Format an event for terminal display."""
    t = e.get("type", "")
    if t == "agent_spawned":
        return f"  {GREEN}●{RESET} {BOLD}{e.get('agent', '?')}{RESET} spawned for: {e.get('task', '?')}"
    if t == "agent_activity":
        return f"  {BLUE}│{RESET} {DIM}{e.get('agent', '?')}{RESET}: {e.get('activity', '?')}"
    if t == "agent_completed":
        files = e.get("files", [])
        f_str = f" → {', '.join(files[:3])}" if files else ""
        return f"  {GREEN}✓{RESET} {BOLD}{e.get('agent', '?')}{RESET} completed: {e.get('task', '?')}{f_str}"
    if t == "agent_killed":
        return f"  {RED}✗{RESET} {e.get('agent', '?')} killed: {e.get('reason', '?')}"
    if t == "board_post":
        return f"  {CYAN}📋{RESET} {e.get('author', '?')}: {_short(e.get('content', ''), 60)}"
    if t == "message_to_human":
        return f"  {YELLOW}💬{RESET} {e.get('from', '?')} → you: {_short(e.get('content', ''), 60)}"
    if t == "message_routed":
        return f"  {DIM}💬 {e.get('from', '?')} → {e.get('to', '?')}{RESET}"
    if t == "human_command":
        return f"  {YELLOW}>{RESET} You: {e.get('action', '?')}"
    if t == "workspace_started":
        return f"  {GREEN}▶{RESET} Workspace started: {e.get('name', '?')}"
    if t == "workspace_completed":
        return f"  {GREEN}■{RESET} Workspace completed: {e.get('reason', '?')}"
    if t == "status":
        verb = e.get("verb", "")
        msg = e.get("message", "")
        return f"  {DIM}⠿ {verb}: {msg}{RESET}"
    return ""  # Don't show unknown events


# ── Main ────────────────────────────────────────────────────────────

async def main():
    if len(sys.argv) < 2:
        print("Usage: python examples/workspace_live.py <workspace.yaml>")
        sys.exit(1)

    yaml_path = Path(sys.argv[1])
    if not yaml_path.exists():
        print(f"File not found: {yaml_path}")
        sys.exit(1)

    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        print(f"Claude Code: {r.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: 'claude' CLI not found")
        sys.exit(1)

    # Setup
    tmpdir = Path(tempfile.mkdtemp(prefix="agentos_live_"))
    workspace = tmpdir / "workspace"
    workspace.mkdir()

    config = load_workspace_config(yaml_path)
    event_log = SQLiteEventLog(str(tmpdir / "workspace.db"))
    seq = SeqCounter()
    wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

    # Detect project root
    project_dir = yaml_path.resolve().parent
    if (project_dir / "agentos").is_dir():
        pass
    elif (project_dir.parent / "agentos").is_dir():
        project_dir = project_dir.parent

    runtime = WorkspaceRuntime(config, event_log, seq, wf_id, workspace,
                                project_dir=project_dir)

    # Status callback for spinner
    def status_cb(msg: str, verb: str):
        on_event({"type": "status", "verb": verb, "message": msg})

    runtime.set_status_callback(status_cb)

    print(f"\n{BOLD}AgentOS Live Workspace{RESET}")
    print(f"{'━' * 50}")
    print(f"  Name: {config.name}")
    print(f"  Goal: {_short(config.goal.strip(), 100)}")
    print(f"  Team: {', '.join(p.name for p in config.team)}")
    print(f"  Dir:  {workspace}")
    print(f"{'━' * 50}\n")
    print(f"  {DIM}Commands:{RESET}")
    print(f"    {DIM}Type a message → posts to the board (all agents see it){RESET}")
    print(f"    {DIM}/msg <agent> <text> → direct message to an agent{RESET}")
    print(f"    {DIM}/task <title> → create a new task{RESET}")
    print(f"    {DIM}/claim <task-num> → claim a task as worker{RESET}")
    print(f"    {DIM}/status → show agent states{RESET}")
    print(f"    {DIM}/board → show current board{RESET}")
    print(f"    {DIM}/tasks → show backlog{RESET}")
    print(f"    {DIM}/pause → pause workspace{RESET}")
    print(f"    {DIM}/quit → stop workspace{RESET}")
    print()

    def _process_command(line: str, ws: Path, rt):
        """Process a human command."""
        if line == "/quit" or line == "/q":
            write_human_command(ws, {"action": "complete", "payload": {}})
            print(f"  {YELLOW}Completing workspace...{RESET}")
        elif line == "/pause":
            write_human_command(ws, {"action": "pause", "payload": {}})
            print(f"  {YELLOW}Paused.{RESET}")
        elif line == "/resume":
            write_human_command(ws, {"action": "resume", "payload": {}})
            print(f"  {GREEN}Resumed.{RESET}")
        elif line == "/status":
            board = rt.board.get_state()
            for s in board.team_status:
                icon = "🔵" if s.state == "running" else "⚪" if s.state == "idle" else "🟡"
                task = f" — {s.current_task}" if s.current_task else ""
                print(f"    {icon} {s.agent_name}: {s.state}{task}")
        elif line == "/board":
            print(rt.board.render_compact(max_tokens=400))
        elif line == "/tasks":
            for i, t in enumerate(rt.backlog.get_all_tasks(), 1):
                a = f" → {t.assigned_to}" if t.assigned_to else ""
                print(f"    {i}. [{t.status:12s}] {t.title}{a}")
        elif line.startswith("/msg "):
            parts = line[5:].split(" ", 1)
            if len(parts) == 2:
                write_human_command(ws, {
                    "action": "send_message",
                    "payload": {"to": parts[0], "content": parts[1]},
                })
                print(f"  {DIM}→ {parts[0]}: {parts[1]}{RESET}")
        elif line.startswith("/task "):
            title = line[6:].strip()
            write_human_command(ws, {
                "action": "create_task",
                "payload": {"title": title},
            })
            print(f"  {DIM}Task created: {title}{RESET}")
        elif line.startswith("/claim "):
            try:
                idx = int(line[7:].strip()) - 1
                tasks = rt.backlog.get_all_tasks()
                if 0 <= idx < len(tasks):
                    write_human_command(ws, {
                        "action": "claim_task",
                        "payload": {"task_id": tasks[idx].task_id, "participant": "human"},
                    })
                    print(f"  {DIM}Claimed: {tasks[idx].title}{RESET}")
            except ValueError:
                print(f"  {RED}Usage: /claim <number>{RESET}")
        else:
            # Default: post to board (agents see this on next read_board)
            write_human_command(ws, {
                "action": "post_to_board",
                "payload": {"content": line, "section": "post", "speech_act": "directive"},
            })
            print(f"  {DIM}📋 Posted to board (all agents will see this){RESET}")

    # Run supervisor in background
    sup_config = SupervisorConfig(
        max_concurrent=len([p for p in config.team if p.type == "agent"]),
    )

    supervisor_task = asyncio.create_task(
        runtime.run_concurrent(supervisor_config=sup_config, on_event=on_event)
    )

    # ── Separated input/output using scroll region ──────────────
    # The terminal is split: top area scrolls with events,
    # bottom 2 lines are a fixed input area that never gets overwritten.

    import shutil
    term_h, term_w = shutil.get_terminal_size((80, 24))

    # Setup: scroll region = all but last 2 lines
    SAVE_POS = "\033[s"
    RESTORE_POS = "\033[u"
    SCROLL_REGION = f"\033[1;{term_h - 2}r"  # scroll region: line 1 to line h-2
    MOVE_TO_INPUT = f"\033[{term_h - 1};1H"   # move cursor to input line
    MOVE_TO_OUTPUT = f"\033[{term_h - 2};1H"   # last line of scroll region
    CLEAR_INPUT_LINE = f"\033[{term_h - 1};1H\033[2K"
    CLEAR_STATUS_LINE = f"\033[{term_h};1H\033[2K"
    RESET_SCROLL = "\033[r"

    # Set up the scroll region
    sys.stdout.write(SCROLL_REGION)
    # Draw separator and input prompt on the fixed lines
    sys.stdout.write(f"\033[{term_h - 1};1H{DIM}{'─' * term_w}{RESET}")
    sys.stdout.write(f"\033[{term_h};1H  {YELLOW}>{RESET} ")
    # Move cursor back to scroll region for events
    sys.stdout.write(f"\033[{term_h - 2};1H")
    sys.stdout.flush()

    def _print_event(text: str):
        """Print an event line in the scroll region (top area)."""
        sys.stdout.write(SAVE_POS)
        sys.stdout.write(f"\033[{term_h - 2};1H\n")  # scroll up, new line at bottom of region
        sys.stdout.write(f"\033[2K{text}")
        sys.stdout.write(RESTORE_POS)
        sys.stdout.flush()

    def _set_input_prompt(prompt_text: str = ""):
        """Redraw the input line at the bottom."""
        sys.stdout.write(f"\033[{term_h};1H\033[2K  {YELLOW}>{RESET} {prompt_text}")
        sys.stdout.flush()

    # Input thread
    _input_queue: list[str] = []
    _input_lock = threading.Lock()
    _input_running = True
    _partial_input = ""

    def _input_reader():
        """Read stdin in a background thread."""
        while _input_running:
            try:
                # Move cursor to input line before reading
                sys.stdout.write(f"\033[{term_h};7H")
                sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:
                    break
                with _input_lock:
                    _input_queue.append(line.strip())
                # Redraw input prompt
                _set_input_prompt()
            except (EOFError, OSError):
                break

    input_thread = threading.Thread(target=_input_reader, daemon=True)
    input_thread.start()

    # Event display loop
    last_event_idx = 0
    try:
        while not supervisor_task.done():
            # Display new events in the scroll region
            with _events_lock:
                new_events = _events[last_event_idx:]
                last_event_idx = len(_events)

            for e in new_events:
                text = format_event(e)
                if text:
                    _print_event(text)

            # Check for human input (non-blocking)
            line = None
            with _input_lock:
                if _input_queue:
                    line = _input_queue.pop(0)

            if line is not None and line:
                # Show the command in the event area
                _print_event(f"  {YELLOW}>{RESET} {BOLD}{line}{RESET}")
                _process_command(line, workspace, runtime)
                _set_input_prompt()

            await asyncio.sleep(0.3)

    except KeyboardInterrupt:
        pass

    _input_running = False

    # Reset terminal
    sys.stdout.write(RESET_SCROLL)
    sys.stdout.write(f"\033[{term_h};1H\n")
    sys.stdout.flush()

    write_human_command(workspace, {"action": "complete", "payload": {}})

    # Wait for supervisor to finish
    if not supervisor_task.done():
        supervisor_task.cancel()
        try:
            await supervisor_task
        except asyncio.CancelledError:
            pass

    # Final summary
    print(f"\n{'━' * 50}")
    print(f"  {BOLD}WORKSPACE ENDED{RESET}")
    print(f"{'━' * 50}")
    print(f"\n  {BOLD}Backlog:{RESET}")
    for t in runtime.backlog.get_all_tasks():
        a = f" → {t.assigned_to}" if t.assigned_to else ""
        print(f"    [{t.status:12s}] {t.title}{a}")

    print(f"\n  {BOLD}Files produced:{RESET}")
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and ".agentos" not in str(f) and "backlog" not in str(f):
            print(f"    {f.relative_to(workspace)} ({f.stat().st_size:,} bytes)")

    print(f"\n  Workspace: {workspace}")
    print(f"  Database: {tmpdir / 'workspace.db'}")


if __name__ == "__main__":
    asyncio.run(main())
