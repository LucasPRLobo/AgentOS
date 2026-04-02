#!/usr/bin/env python3
"""AgentOS Live Workspace — Terminal UI for concurrent agent collaboration.

Usage:
    python examples/workspace_live.py <workspace.yaml>

Navigation:
    Tab         Cycle views: Home → Agent chats → Board → Tasks
    ← →         Cycle agents (in agent chat view)
    Ctrl+Q      Quit
    Ctrl+P      Pause/Resume

Input:
    Type text   Chat with coordinator (home) or current agent
    /board      Post to shared board
    /tasks      Show task list
    /claim N    Claim task N as worker
    /task Title Create new task
    /msg A text Direct message agent A
    /files      Show workspace files
    /status     Show detailed status
    /quit       Stop workspace
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Input, RichLog, Static


# ── Command autocomplete ───────────────────────────────────────────

COMMANDS = [
    "/board", "/tasks", "/claim ", "/task ", "/msg ",
    "/files", "/status", "/pause", "/resume", "/quit",
    "/help",
]


class CommandSuggester(SuggestFromList):
    """Autocomplete for /commands."""

    def __init__(self):
        super().__init__(COMMANDS, case_sensitive=False)

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/"):
            return None
        return await super().get_suggestion(value)


# ── App ────────────────────────────────────────────────────────────

class WorkspaceTUI(App):
    """AgentOS workspace — messenger-style terminal interface."""

    TITLE = "AgentOS"

    CSS = """
    Screen {
        background: $surface-darken-1;
    }

    #header {
        height: 1;
        background: $primary-background;
        color: $text;
        padding: 0 2;
    }

    #body {
        height: 1fr;
    }

    /* Left column: agents + tasks */
    #sidebar {
        width: 32;
        border-right: solid $surface-lighten-2;
    }

    #sidebar-label {
        height: 1;
        color: $text-muted;
        background: $surface;
        padding: 0 1;
    }

    #agent-list {
        height: 1fr;
        padding: 0 1;
    }

    #task-summary {
        height: auto;
        max-height: 12;
        border-top: solid $surface-lighten-1;
        padding: 0 1;
    }

    #task-label {
        height: 1;
        color: $text-muted;
        background: $surface;
        padding: 0 1;
    }

    /* Right column: chat */
    #chat-area {
        width: 1fr;
    }

    #chat-label {
        height: 1;
        color: $text;
        background: $surface;
        padding: 0 1;
    }

    #chat-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #activity-log {
        height: 6;
        border-top: dashed $surface-lighten-1;
        padding: 0 1;
        scrollbar-size: 1 1;
        color: $text-muted;
    }

    #input-bar {
        height: 3;
        background: $surface;
        border-top: solid $primary;
        padding: 0 1;
    }

    #cmd-input {
        width: 1fr;
    }

    #view-indicator {
        width: auto;
        min-width: 10;
        color: $text-muted;
        padding: 0 1;
        content-align: right middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("ctrl+p", "toggle_pause", "Pause/Resume"),
        Binding("tab", "next_view", "Next view"),
        Binding("shift+tab", "prev_view", "Prev view"),
        Binding("right", "next_agent", "Next agent", show=False),
        Binding("left", "prev_agent", "Prev agent", show=False),
    ]

    # Views: home, agent:<id>, board, tasks
    current_view: str = "home"
    agent_index: int = 0

    def __init__(self, yaml_path: Path):
        super().__init__()
        self.yaml_path = yaml_path
        self.runtime = None
        self.supervisor = None
        self.workspace = None
        self._events: list[dict] = []
        self._events_lock = threading.Lock()
        self._seen: set[int] = set()
        self._agent_ids: list[str] = []
        self._views = ["home", "board", "tasks"]

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("[bold dim]AGENTS[/]", id="sidebar-label")
                yield Static("", id="agent-list")
                yield Static("[bold dim]TASKS[/]", id="task-label")
                yield Static("", id="task-summary")
            with Vertical(id="chat-area"):
                yield Static("[bold dim]COORDINATOR[/]", id="chat-label")
                yield RichLog(id="chat-log", wrap=True, markup=True)
                yield RichLog(id="activity-log", wrap=True, markup=True)
        with Horizontal(id="input-bar"):
            yield Input(
                placeholder="Chat with coordinator… (or /command)",
                id="cmd-input",
                suggester=CommandSuggester(),
            )
            yield Static("[dim]home[/]", id="view-indicator")
        yield Footer()

    async def on_mount(self) -> None:
        try:
            subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            self.chat("[red]ERROR: claude CLI not found[/]")
            return

        tmpdir = Path(tempfile.mkdtemp(prefix="agentos_live_"))
        self.workspace = tmpdir / "workspace"
        self.workspace.mkdir()

        from agentos.workspace.loader import load_workspace_config
        from agentos.kernel.event_log import SQLiteEventLog
        from agentos.kernel.seq import SeqCounter
        from agentos.workspace.runtime import WorkspaceRuntime

        config = load_workspace_config(self.yaml_path)
        event_log = SQLiteEventLog(str(tmpdir / "workspace.db"))
        seq = SeqCounter()
        wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

        project_dir = self.yaml_path.resolve().parent
        if (project_dir / "agentos").is_dir():
            pass
        elif (project_dir.parent / "agentos").is_dir():
            project_dir = project_dir.parent

        self.runtime = WorkspaceRuntime(config, event_log, seq, wf_id, self.workspace,
                                         project_dir=project_dir)

        self._agent_ids = [p.name for p in config.team if p.type == "agent"]
        self._views = ["home"] + [f"agent:{a}" for a in self._agent_ids] + ["board", "tasks"]

        # Header
        self.query_one("#header").update(
            f" [bold green]AgentOS[/] │ {config.name}"
        )

        self.chat(f"[dim]Workspace: {config.name}[/]")
        self.chat(f"[dim]Goal: {config.goal.strip()[:150]}[/]")
        self.chat(f"[dim]Team: {', '.join(p.name for p in config.team)}[/]")
        self.chat("")
        self.chat("[yellow]coordinator[/]: Starting up… I'll read the project and set up the team.")
        self.chat("")

        self.run_supervisor()
        self.set_interval(1.0, self._refresh)

    # ── Supervisor ────────────────────────────────────────────────

    @work(thread=True)
    def run_supervisor(self) -> None:
        loop = asyncio.new_event_loop()

        def event_cb(event):
            with self._events_lock:
                self._events.append(event)
                if len(self._events) > 500:
                    self._events[:] = self._events[-300:]

        def status_cb(msg, verb):
            event_cb({"type": "status", "verb": verb, "message": msg})

        self.runtime.set_status_callback(status_cb)

        from agentos.workspace.schemas import SupervisorConfig
        from agentos.workspace.supervisor import WorkspaceSupervisor

        agent_count = len(self._agent_ids)
        sup_config = SupervisorConfig(max_concurrent=max(agent_count, 1))
        self.supervisor = WorkspaceSupervisor(self.runtime, sup_config)
        self.supervisor.set_event_callback(event_cb)
        self.supervisor.set_status_callback(status_cb)

        loop.run_until_complete(self.supervisor.run())

    # ── Periodic refresh ──────────────────────────────────────────

    def _refresh(self) -> None:
        if not self.runtime:
            return

        # Process new events
        with self._events_lock:
            events = list(self._events)

        for event in events:
            eid = id(event)
            if eid in self._seen:
                continue
            self._seen.add(eid)
            self._handle_event(event)

        # Update sidebar
        self._update_sidebar()
        self._update_header()

    def _handle_event(self, e: dict) -> None:
        t = e.get("type", "")

        if t == "board_post":
            author = e.get("author", "?")
            content = e.get("content", "")[:120]
            if self.current_view == "board":
                if author == "human":
                    self.chat(f"[cyan bold]you[/]: {content}")
                else:
                    self.chat(f"[magenta]{author}[/]: {content}")
            # Also show on home view
            elif self.current_view == "home":
                self.chat(f"[dim]board ›[/] [magenta]{author}[/]: {content[:80]}")

        elif t == "agent_spawned":
            agent = e.get("agent", "?")
            task = e.get("task", "?")
            self.chat(f"[green]● {agent}[/] started: {task}")

        elif t == "agent_completed":
            agent = e.get("agent", "?")
            task = e.get("task", "?")
            files = e.get("files", [])
            f_str = f" → {', '.join(files[:3])}" if files else ""
            self.chat(f"[green]✓ {agent}[/] completed: {task}{f_str}")

        elif t == "agent_killed":
            self.chat(f"[red]✗ {e.get('agent')}[/] killed: {e.get('reason', '?')}")

        elif t == "agent_activity":
            agent = e.get("agent", "?")
            activity = e.get("activity", "")
            # Show in activity log (bottom strip)
            try:
                self.query_one("#activity-log", RichLog).write(
                    f"[dim]{agent}: {activity}[/]"
                )
            except Exception:
                pass
            # If viewing this agent's chat, show there too
            if self.current_view == f"agent:{agent}":
                self.chat(f"[dim]  {activity}[/]")

        elif t == "message_to_human":
            sender = e.get("from", "?")
            content = e.get("content", "")[:100]
            self.chat(f"[yellow]💬 {sender}[/]: {content}")

        elif t == "workspace_completed":
            self.chat(f"[green bold]■ Workspace completed: {e.get('reason', '?')}[/]")

        elif t == "plan_created":
            count = e.get("task_count", 0)
            self.chat(f"[yellow]coordinator[/]: Plan ready — {count} tasks created. Team is starting.")

        elif t == "status":
            verb = e.get("verb", "")
            msg = e.get("message", "")
            # Show coordinator planning activity
            if verb == "Coordinator" or verb == "Planning":
                try:
                    self.query_one("#activity-log", RichLog).write(
                        f"[dim]{verb}: {msg}[/]"
                    )
                except Exception:
                    pass

    def _update_sidebar(self) -> None:
        if not self.runtime:
            return

        board = self.runtime.board.get_state()
        active = getattr(self.supervisor, '_active', {}) if self.supervisor else {}

        # Agent list
        agent_lines = []
        for s in board.team_status:
            aid = s.agent_id
            is_human = any(p.type == "human" and p.name == aid for p in self.runtime.config.team)
            is_running = aid in active

            if is_running:
                last = self._last_activity(aid)
                elapsed = self._agent_elapsed(active.get(aid))
                short_activity = (last[:20] + "…") if len(last) > 20 else last if last else ""
                agent_lines.append(f"[green]●[/] [bold]{aid}[/]\n  [dim]{short_activity} {elapsed}[/]")
            elif is_human:
                agent_lines.append(f"[cyan]◉[/] [bold]{aid}[/] [dim](you)[/]")
            else:
                agent_lines.append(f"[dim]○ {aid}[/]")

        try:
            self.query_one("#agent-list").update("\n".join(agent_lines) if agent_lines else "[dim]No agents[/]")
        except Exception:
            pass

        # Task summary
        tasks = self.runtime.backlog.get_all_tasks()
        task_lines = []
        for t in tasks[:8]:
            icon = "[green]✓[/]" if t.status == "done" else "[yellow]●[/]" if "progress" in t.status else "[red]🔒[/]" if t.status == "blocked" else "[dim]○[/]"
            name = (t.title[:22] + "…") if len(t.title) > 22 else t.title
            task_lines.append(f"{icon} {name}")
        if len(tasks) > 8:
            task_lines.append(f"[dim]  +{len(tasks) - 8} more[/]")

        try:
            self.query_one("#task-summary").update("\n".join(task_lines) if task_lines else "[dim]No tasks yet[/]")
        except Exception:
            pass

    def _update_header(self) -> None:
        if not self.runtime:
            return
        tasks = self.runtime.backlog.get_all_tasks()
        done = sum(1 for t in tasks if t.status == "done")
        status = self.runtime.state.status
        icon = "[green]●[/]" if status == "active" else "[yellow]●[/]"
        active_count = len(getattr(self.supervisor, '_active', {})) if self.supervisor else 0

        try:
            self.query_one("#header").update(
                f" [bold green]AgentOS[/] │ {self.runtime.config.name} │ "
                f"{icon} {status.upper()} │ {done}/{len(tasks)} tasks │ "
                f"{active_count} agents running"
            )
        except Exception:
            pass

    def _last_activity(self, agent_id: str) -> str:
        with self._events_lock:
            for e in reversed(self._events):
                if e.get("type") == "agent_activity" and e.get("agent") == agent_id:
                    return e.get("activity", "")
        return ""

    def _agent_elapsed(self, info) -> str:
        if info is None:
            return ""
        launch = getattr(info, "_launch_mono", None)
        if launch is None:
            return ""
        e = time.monotonic() - launch
        return f"{e:.0f}s" if e < 60 else f"{e / 60:.1f}m"

    # ── Chat output ───────────────────────────────────────────────

    def chat(self, message: str) -> None:
        try:
            self.query_one("#chat-log", RichLog).write(message)
        except Exception:
            pass

    # ── Input handling ────────────────────────────────────────────

    @on(Input.Submitted, "#cmd-input")
    def on_input(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.clear()
        if not line:
            return

        if line.startswith("/"):
            self._handle_command(line)
        else:
            self._handle_message(line)

    def _handle_message(self, text: str) -> None:
        """Send a message — to coordinator (home), to agent (agent view), or to board."""
        if not self.workspace:
            return

        from agentos.comms.comms_state import write_human_command

        if self.current_view == "home":
            # Chat with coordinator — post as directive, coordinator sees it
            self.chat(f"[cyan bold]you[/]: {text}")
            write_human_command(self.workspace, {
                "action": "post_to_board",
                "payload": {"content": text, "section": "post", "speech_act": "directive"},
            })

        elif self.current_view.startswith("agent:"):
            agent_id = self.current_view.split(":", 1)[1]
            self.chat(f"[cyan bold]you → {agent_id}[/]: {text}")
            write_human_command(self.workspace, {
                "action": "send_message",
                "payload": {"to": agent_id, "content": text},
            })

        elif self.current_view == "board":
            self.chat(f"[cyan bold]you[/]: {text}")
            write_human_command(self.workspace, {
                "action": "post_to_board",
                "payload": {"content": text, "section": "post", "speech_act": "inform"},
            })

    def _handle_command(self, line: str) -> None:
        from agentos.comms.comms_state import write_human_command

        if line in ("/quit", "/q"):
            if self.workspace:
                write_human_command(self.workspace, {"action": "complete", "payload": {}})
            self.chat("[yellow]Stopping…[/]")
            self.set_timer(1.5, self.exit)

        elif line == "/pause":
            if self.workspace:
                write_human_command(self.workspace, {"action": "pause", "payload": {}})
            self.chat("[yellow]Paused.[/]")

        elif line == "/resume":
            if self.workspace:
                write_human_command(self.workspace, {"action": "resume", "payload": {}})
            self.chat("[green]Resumed.[/]")

        elif line == "/tasks":
            if self.runtime:
                for i, t in enumerate(self.runtime.backlog.get_all_tasks(), 1):
                    a = f" → {t.assigned_to}" if t.assigned_to else ""
                    icon = "✓" if t.status == "done" else "●" if "progress" in t.status else "🔒" if t.status == "blocked" else "○"
                    self.chat(f"  {icon} {i}. [{t.status}] {t.title}{a}")

        elif line == "/board":
            if self.runtime:
                self.chat(self.runtime.board.render_compact(max_tokens=400))

        elif line == "/files":
            if self.workspace:
                for f in sorted(self.workspace.rglob("*")):
                    if f.is_file() and ".agentos" not in str(f) and "backlog" not in str(f):
                        self.chat(f"  {f.relative_to(self.workspace)} ({f.stat().st_size:,}b)")

        elif line == "/status":
            if self.runtime:
                board = self.runtime.board.get_state()
                for s in board.team_status:
                    last = self._last_activity(s.agent_id)
                    extra = f" — {last}" if last else ""
                    self.chat(f"  {s.agent_name}: {s.state}{extra}")

        elif line.startswith("/msg "):
            parts = line[5:].split(" ", 1)
            if len(parts) == 2 and self.workspace:
                write_human_command(self.workspace, {
                    "action": "send_message",
                    "payload": {"to": parts[0], "content": parts[1]},
                })
                self.chat(f"[cyan]→ {parts[0]}[/]: {parts[1]}")
            else:
                self.chat("[dim]Usage: /msg <agent> <text>[/]")

        elif line.startswith("/task "):
            title = line[6:].strip()
            if self.workspace:
                write_human_command(self.workspace, {
                    "action": "create_task",
                    "payload": {"title": title},
                })
                self.chat(f"[dim]Task created: {title}[/]")

        elif line.startswith("/claim "):
            if self.runtime and self.workspace:
                try:
                    idx = int(line[7:].strip()) - 1
                    tasks = self.runtime.backlog.get_all_tasks()
                    if 0 <= idx < len(tasks):
                        write_human_command(self.workspace, {
                            "action": "claim_task",
                            "payload": {"task_id": tasks[idx].task_id, "participant": "human"},
                        })
                        self.chat(f"[dim]Claimed: {tasks[idx].title}[/]")
                    else:
                        self.chat("[red]Invalid task number[/]")
                except ValueError:
                    self.chat("[dim]Usage: /claim <number>[/]")

        elif line == "/help":
            self.chat("[bold]Commands:[/]")
            self.chat("  [cyan]/board[/]      Show full board")
            self.chat("  [cyan]/tasks[/]      Show task list")
            self.chat("  [cyan]/claim N[/]    Claim task N")
            self.chat("  [cyan]/task Title[/] Create new task")
            self.chat("  [cyan]/msg A text[/] Message agent A")
            self.chat("  [cyan]/files[/]      Show workspace files")
            self.chat("  [cyan]/status[/]     Show agent details")
            self.chat("  [cyan]/pause[/]      Pause workspace")
            self.chat("  [cyan]/quit[/]       Stop and exit")
            self.chat("")
            self.chat("[bold]Navigation:[/]")
            self.chat("  Tab        Cycle views")
            self.chat("  ← →        Cycle agents")
            self.chat("  Ctrl+Q     Quit")

        else:
            self.chat(f"[dim]Unknown command. Type /help for options.[/]")

    # ── View navigation ───────────────────────────────────────────

    def action_next_view(self) -> None:
        idx = self._views.index(self.current_view) if self.current_view in self._views else 0
        self.current_view = self._views[(idx + 1) % len(self._views)]
        self._switch_view()

    def action_prev_view(self) -> None:
        idx = self._views.index(self.current_view) if self.current_view in self._views else 0
        self.current_view = self._views[(idx - 1) % len(self._views)]
        self._switch_view()

    def action_next_agent(self) -> None:
        if self._agent_ids:
            self.agent_index = (self.agent_index + 1) % len(self._agent_ids)
            self.current_view = f"agent:{self._agent_ids[self.agent_index]}"
            self._switch_view()

    def action_prev_agent(self) -> None:
        if self._agent_ids:
            self.agent_index = (self.agent_index - 1) % len(self._agent_ids)
            self.current_view = f"agent:{self._agent_ids[self.agent_index]}"
            self._switch_view()

    def _switch_view(self) -> None:
        """Update UI when switching views."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()

        view = self.current_view
        if view == "home":
            label = "[bold dim]COORDINATOR[/]"
            placeholder = "Chat with coordinator… (or /command)"
            chat_log.write("[dim]Home view — chat with the coordinator, see overview[/]")
            chat_log.write("")
        elif view.startswith("agent:"):
            agent_id = view.split(":", 1)[1]
            label = f"[bold dim]CHAT: {agent_id}[/]"
            placeholder = f"Message {agent_id}…"
            chat_log.write(f"[dim]Direct chat with {agent_id}[/]")
            chat_log.write("")
        elif view == "board":
            label = "[bold dim]BOARD[/]"
            placeholder = "Post to the board…"
            if self.runtime:
                chat_log.write(self.runtime.board.render_compact(max_tokens=600))
        elif view == "tasks":
            label = "[bold dim]TASKS[/]"
            placeholder = "Create task: /task <title>"
            if self.runtime:
                for i, t in enumerate(self.runtime.backlog.get_all_tasks(), 1):
                    a = f" → {t.assigned_to}" if t.assigned_to else ""
                    icon = "✓" if t.status == "done" else "●" if "progress" in t.status else "🔒" if t.status == "blocked" else "○"
                    chat_log.write(f"  {icon} {i}. [{t.status}] {t.title}{a}")
        else:
            label = "[bold dim]???[/]"
            placeholder = ""

        try:
            self.query_one("#chat-label").update(label)
            self.query_one("#cmd-input", Input).placeholder = placeholder
            self.query_one("#view-indicator").update(f"[dim]{view}[/]")
        except Exception:
            pass

    def action_quit_app(self) -> None:
        self._handle_command("/quit")

    def action_toggle_pause(self) -> None:
        if self.runtime and self.runtime.state.status == "active":
            self._handle_command("/pause")
        else:
            self._handle_command("/resume")


def main():
    if len(sys.argv) < 2:
        print("Usage: python examples/workspace_live.py <workspace.yaml>")
        sys.exit(1)

    yaml_path = Path(sys.argv[1])
    if not yaml_path.exists():
        print(f"File not found: {yaml_path}")
        sys.exit(1)

    app = WorkspaceTUI(yaml_path)
    app.run()


if __name__ == "__main__":
    main()
