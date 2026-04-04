#!/usr/bin/env python3
"""AgentOS Live Workspace — Terminal UI for concurrent agent collaboration.

Usage:
    python examples/workspace_live.py <workspace.yaml>

Navigation:
    F1                Home (coordinator chat)
    F2                Agent DMs (← → to cycle agents)
    F3                Board
    F4                Tasks
    Ctrl+← / Ctrl+→  Cycle views
    Ctrl+Q            Quit
    Ctrl+P            Pause/Resume
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


COMMANDS = [
    "/board", "/tasks", "/claim ", "/task ", "/msg ",
    "/files", "/status", "/pause", "/resume", "/quit", "/help",
]


class CommandSuggester(SuggestFromList):
    def __init__(self):
        super().__init__(COMMANDS, case_sensitive=False)

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/"):
            return None
        return await super().get_suggestion(value)


class WorkspaceTUI(App):
    TITLE = "AgentOS"
    ENABLE_COMMAND_PALETTE = False
    # Hold Shift + mouse drag to select text for copying
    # (Shift bypasses Textual's mouse capture in most terminals)

    CSS = """
    Screen { background: $surface-darken-1; }

    #header {
        height: 1;
        background: $primary-background;
        color: $text;
        padding: 0 2;
    }

    #body { height: 1fr; }

    #sidebar {
        width: 30;
        border-right: solid $surface-lighten-2;
    }
    #sidebar-label {
        height: 1; color: $text-muted;
        background: $surface; padding: 0 1;
    }
    #agent-list { height: 1fr; padding: 0 1; overflow-y: auto; }
    #task-label {
        height: 1; color: $text-muted;
        background: $surface; padding: 0 1;
    }
    #task-summary {
        height: auto; max-height: 14;
        border-top: solid $surface-lighten-1;
        padding: 0 1; overflow-y: auto;
    }

    #main { width: 1fr; }

    #chat-label {
        height: 1; color: $text;
        background: $primary-background; padding: 0 1;
    }
    #chat-log {
        height: 1fr; padding: 0 1;
        scrollbar-size: 1 1;
    }

    /* Activity strip — compact, dim */
    #activity-strip {
        height: 4;
        border-top: dashed $surface-lighten-1;
        padding: 0 1;
        scrollbar-size: 1 1;
    }

    #input-bar {
        height: 3;
        background: $surface;
        border-top: solid $primary;
        padding: 0 1;
    }
    #cmd-input { width: 1fr; }
    #view-tag {
        width: auto; min-width: 16;
        color: $text-muted;
        padding: 0 1;
        content-align: right middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("ctrl+p", "toggle_pause", "Pause/Resume"),
        Binding("ctrl+right", "next_view", "Next view", priority=True),
        Binding("ctrl+left", "prev_view", "Prev view", priority=True),
        Binding("f1", "go_home", "Home", priority=True),
        Binding("f2", "go_agents", "Agents", priority=True),
        Binding("f3", "go_board", "Board", priority=True),
        Binding("f4", "go_tasks", "Tasks", priority=True),
    ]

    current_view: str = "home"
    agent_index: int = 0

    def __init__(self, yaml_path: Path | None = None, mock: bool = False,
                 skip_coordinator: bool = False):
        super().__init__()
        self.yaml_path = yaml_path
        self.mock = mock
        self.skip_coordinator = skip_coordinator
        self.blank_mode = yaml_path is None  # No YAML = blank workspace
        self._setup_messages: list[str] = []  # Setup conversation history
        self._setup_started = False
        self.runtime = None
        self.supervisor = None
        self.workspace = None
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._seen: set[int] = set()
        self._agent_ids: list[str] = []
        self._views = ["home", "board", "tasks"]
        self._chat_history: dict[str, list[str]] = {}
        self._board_posts: list[dict] = []
        self._total_tokens: int = 0  # Track total token usage

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("[bold dim]AGENTS[/]", id="sidebar-label")
                yield Static("", id="agent-list")
                yield Static("[bold dim]TASKS[/]", id="task-label")
                yield Static("", id="task-summary")
            with Vertical(id="main"):
                yield Static("[bold]COORDINATOR[/]", id="chat-label")
                yield RichLog(id="chat-log", wrap=True, markup=True)
                yield RichLog(id="activity-strip", wrap=True, markup=True)
        with Horizontal(id="input-bar"):
            yield Input(
                placeholder="Chat with coordinator… (or /command)",
                id="cmd-input",
                suggester=CommandSuggester(),
            )
            yield Static("[dim]🏠 home[/]", id="view-tag")
        yield Footer()

    async def on_mount(self) -> None:
        if not self.mock and not self.blank_mode:
            try:
                subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
            except FileNotFoundError:
                self._chat_write("[red]ERROR: claude CLI not found[/]")
                return

        # Blank mode: start with just the coordinator conversation
        if self.blank_mode:
            self._tmpdir = Path(tempfile.mkdtemp(prefix="agentos_live_"))
            self.workspace = self._tmpdir / "workspace"
            self.workspace.mkdir()
            self.query_one("#header").update(
                " [bold green]AgentOS[/] │ New Workspace"
            )
            self._add_to_view("home", "[yellow]coordinator[/]: Hi! What would you like to work on?")
            self._add_to_view("home", "")
            self._add_to_view("home", "[dim]Describe your project and I'll suggest a team.[/]")
            self.set_interval(1.0, self._refresh)
            return

        tmpdir = Path(tempfile.mkdtemp(prefix="agentos_live_"))
        self._tmpdir = tmpdir
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

        self.query_one("#header").update(
            f" [bold green]AgentOS[/] │ {config.name}"
        )

        self._add_to_view("home", f"[dim]Goal: {config.goal.strip()[:150]}[/]")
        self._add_to_view("home", f"[dim]Team: {', '.join(p.name for p in config.team)}[/]")
        self._add_to_view("home", "")

        if self.mock:
            self._add_to_view("home", "[yellow]coordinator[/]: Mock mode — tasks pre-loaded, no real agents.")
            self._add_to_view("home", "")
            self._setup_mock()
        elif self.skip_coordinator:
            self._add_to_view("home", "[yellow]coordinator[/]: Tasks pre-loaded. Launching agents now.")
            self._add_to_view("home", "")
            self._preload_tasks()
            self.run_supervisor()
        else:
            self._add_to_view("home", "[yellow]coordinator[/]: Starting up… I'll read the project and set up the team.")
            self.run_supervisor()

        self.set_interval(1.0, self._refresh)

    # ── Pre-load tasks (skip coordinator) ─────────────────────────

    def _preload_tasks(self) -> None:
        """Pre-load tasks so the supervisor skips coordinator decomposition."""
        from agentos.workspace.schemas import BacklogTask

        self.runtime.start()

        t1 = self.runtime.add_task(BacklogTask(
            title="Research dashboard UX patterns",
            description="Research Linear, Asana, Notion UX patterns. Write findings to ux-research.md.",
            created_by="coordinator", suggested_for="ui-researcher", priority="high",
        ))
        t2 = self.runtime.add_task(BacklogTask(
            title="Audit existing frontend components",
            description="Review existing React components in agentos/dashboard/frontend/src/. Identify gaps. Write to gap-analysis.md.",
            created_by="coordinator", suggested_for="designer", priority="high",
        ))
        t3 = self.runtime.add_task(BacklogTask(
            title="Design component architecture",
            description="Design React component tree, state management, WebSocket integration. Write to architecture.md.",
            created_by="coordinator", suggested_for="architect", priority="normal",
            depends_on=[t1, t2],
        ))
        self.runtime.backlog.recompute_priorities()

        self._add_to_view("home", f"  [green]●[/] ui-researcher → Research dashboard UX patterns")
        self._add_to_view("home", f"  [green]●[/] designer → Audit existing frontend components")
        self._add_to_view("home", f"  [dim]○[/] architect → waiting (depends on research + audit)")

    # ── Mock mode ──────────────────────────────────────────────────

    def _setup_mock(self) -> None:
        """Pre-load tasks and simulate agent activity. Zero tokens."""
        from agentos.workspace.schemas import BacklogTask
        from agentos.comms.schemas import BoardPost, BoardSection, SpeechAct

        self.runtime.start()

        # Pre-load tasks (skip coordinator decomposition)
        t1 = self.runtime.add_task(BacklogTask(
            title="Research dashboard UX patterns",
            description="Research Linear, Asana, Notion UX patterns for dashboards.",
            created_by="coordinator", suggested_for="ui-researcher", priority="high",
        ))
        t2 = self.runtime.add_task(BacklogTask(
            title="Audit existing frontend components",
            description="Review existing React components and identify gaps.",
            created_by="coordinator", suggested_for="designer", priority="high",
        ))
        t3 = self.runtime.add_task(BacklogTask(
            title="Design React component architecture",
            description="Design component tree, state management, WebSocket integration.",
            created_by="coordinator", suggested_for="architect", priority="normal",
            depends_on=[t1, t2],
        ))
        self.runtime.backlog.recompute_priorities()

        # Simulate some board activity
        self.runtime.board.post(BoardPost(
            section=BoardSection.POST, author_type="agent", author_id="coordinator",
            content="Team set up. 3 tasks created. Research and audit running in parallel, architecture will follow.",
            speech_act=SpeechAct.INFORM,
        ))

        self._add_to_view("home", "[yellow]coordinator[/]: Team set up. 3 tasks created.")
        self._add_to_view("home", "  [green]●[/] ui-researcher → Research dashboard UX patterns")
        self._add_to_view("home", "  [green]●[/] designer → Audit existing frontend components")
        self._add_to_view("home", "  [dim]○[/] architect → waiting for research + audit")
        self._add_to_view("home", "")
        self._add_to_view("home", "[yellow]coordinator[/]: What aspects should we prioritize?")

        # Start the mock supervisor (simulates tick updates without real agents)
        self._run_mock_supervisor()

    @work(thread=True)
    def _run_mock_supervisor(self) -> None:
        """Simulated supervisor — just processes human commands and updates UI."""
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()

        from agentos.comms.comms_state import read_human_commands, write_board_file
        from agentos.comms.schemas import BoardPost, BoardSection, SpeechAct

        self.runtime.board.update_agent_status(
            __import__("agentos.comms.schemas", fromlist=["AgentStatus"]).AgentStatus(
                agent_id="coordinator", agent_name="coordinator",
                role="Project coordination", state="idle",
            )
        )

        while self.runtime.state.status == "active":
            # Process human commands
            if self.workspace:
                cmds = read_human_commands(self.workspace)
                for cmd in cmds:
                    action = cmd.get("action", "")
                    payload = cmd.get("payload", {})

                    if action == "post_to_board":
                        content = payload.get("content", "")
                        self.runtime.board.post(BoardPost(
                            section=BoardSection(payload.get("section", "post")),
                            author_type="human", author_id="human",
                            content=content,
                            speech_act=SpeechAct(payload.get("speech_act", "inform")),
                        ))
                        with self._lock:
                            self._events.append({
                                "type": "board_post", "author": "human", "content": content,
                            })
                        # Simulate coordinator response
                        import random
                        responses = [
                            f"Got it. I'll pass that to the team.",
                            f"Noted. Adjusting priorities accordingly.",
                            f"Good point. I'll have the researcher look into that.",
                            f"Understood. Let me update the plan.",
                        ]
                        resp = random.choice(responses)
                        with self._lock:
                            self._events.append({
                                "type": "board_post", "author": "coordinator", "content": resp,
                            })
                        self.runtime.board.post(BoardPost(
                            section=BoardSection.POST, author_type="agent",
                            author_id="coordinator", content=resp,
                            speech_act=SpeechAct.INFORM,
                        ))

                    elif action == "send_message":
                        to = payload.get("to", "")
                        content = payload.get("content", "")
                        # Simulate agent response
                        if to and content:
                            import random
                            agent_responses = [
                                f"Thanks for the direction. I'll focus on that.",
                                f"Good question. Based on what I've found so far, I'd suggest we consider a three-panel layout.",
                                f"I'll look into that. Give me a moment to check the codebase.",
                                f"Interesting point. Let me adjust my approach.",
                            ]
                            resp = random.choice(agent_responses)
                            with self._lock:
                                self._events.append({
                                    "type": "message_to_human", "from": to, "content": resp,
                                })

                    elif action == "complete":
                        self.runtime.complete()
                        break
                    elif action == "pause":
                        self.runtime.pause()

                # Write shared state
                board_state = self.runtime.board.get_state()
                board_data = board_state.model_dump(mode="json")
                board_data["_compact"] = self.runtime.board.render_compact(max_tokens=400)
                write_board_file(self.workspace, board_data)

            loop.run_until_complete(_asyncio.sleep(2.0))

    # ── Blank workspace setup ────────────────────────────────────

    @work(thread=True)
    def _handle_setup_message(self, text: str) -> None:
        """Handle a message during blank workspace setup.

        The setup coordinator is a full Claude Code session with tool access.
        It can read files, search the web, explore the codebase — just like
        when you start a conversation with Claude Code directly.
        """
        self._setup_messages.append(text)
        self._add_to_view("home", f"[cyan bold]you[/]: {text}")

        all_messages = "\n".join(f"Human: {m}" for m in self._setup_messages)

        prompt = (
            f"You are the AgentOS setup coordinator. Help the user define their project.\n"
            f"You have full tool access — read files, search the web, explore the codebase.\n\n"
            f"Conversation so far:\n{all_messages}\n\n"
            f"## Your process:\n"
            f"1. Explore the codebase/web if needed to understand the project\n"
            f"2. Ask clarifying questions if you need more info\n"
            f"3. When ready, PRESENT the team proposal clearly in your response:\n"
            f"   - List each agent: name, role, what they'll do\n"
            f"   - Suggest a budget\n"
            f"   - Ask the user to approve or adjust\n"
            f"4. ONLY write `_setup_output/config.json` AFTER the user says yes/approved\n\n"
            f"The config format when writing:\n"
            f'{{"ready": true, "name": "Project Name", "goal": "...", '
            f'"team": [{{"name": "agent-name", "specialization": "what they do"}}], '
            f'"budget_usd": 8.0}}\n\n'
            f"IMPORTANT: Show the plan to the user FIRST. Do NOT write ready:true until they approve.\n"
            f"Respond conversationally — explain your thinking."
        )

        try:
            cmd = [
                "claude", "--print",
                "--output-format", "stream-json",
                "--verbose",
                "--max-turns", "10",
                "--model", "sonnet",
                "--permission-mode", "bypassPermissions",
                "--name", "agentos-setup",
            ]

            # Give access to the project directory
            project_dir = Path.cwd()
            if (project_dir / "agentos").is_dir():
                cmd.extend(["--add-dir", str(project_dir)])
            elif (project_dir.parent / "agentos").is_dir():
                cmd.extend(["--add-dir", str(project_dir.parent)])

            if self._setup_started:
                cmd.append("--continue")

            cmd.extend(["-p", prompt])

            # Ensure output dir exists
            if self.workspace:
                (self.workspace / "_setup_output").mkdir(exist_ok=True)

            # Stream the response — show tool calls live
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace) if self.workspace else None,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

            import json as _json
            response_text = ""

            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = _json.loads(line)
                except _json.JSONDecodeError:
                    continue

                if event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            response_text = block.get("text", "")
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            desc = self._describe_setup_tool(name, inp)
                            if desc:
                                self._activity_write(f"[dim]coordinator: {desc}[/]")

            # Drain stderr
            proc.stderr.read()
            proc.wait()
            self._setup_started = True

            # Show the response
            if response_text:
                self._add_to_view("home", f"[yellow]coordinator[/]: {response_text}")

            # Check if config was written to file
            config_path = self.workspace / "_setup_output" / "config.json" if self.workspace else None
            if config_path and config_path.exists():
                try:
                    config_data = _json.loads(config_path.read_text())
                    if config_data.get("ready"):
                        self._add_to_view("home", "")
                        self._add_to_view("home", "[green]Setting up workspace...[/]")
                        self._initialize_from_config(config_data)
                except _json.JSONDecodeError:
                    pass

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            self._add_to_view("home", f"[red]Setup failed: {exc}[/]")

    @staticmethod
    def _describe_setup_tool(name: str, inp: dict) -> str:
        """Human-readable tool call for setup coordinator."""
        clean = name.replace("mcp__agentos-comms__", "")
        def _short(p: str) -> str:
            parts = p.replace("\\", "/").split("/")
            return "/".join(parts[-2:]) if len(parts) > 2 else p
        if name == "Read":
            return f"📖 Reading {_short(inp.get('file_path', inp.get('path', '?')))}"
        if name == "Glob":
            return f"🔍 Finding: {inp.get('pattern', '?')}"
        if name == "Grep":
            return f"🔎 Searching: {inp.get('pattern', '?')[:40]}"
        if name == "Bash":
            return f"⚡ {inp.get('command', '?')[:60]}"
        if name in ("WebSearch", "WebFetch"):
            return f"🌐 {name}: {inp.get('query', inp.get('url', '?'))[:50]}"
        if name == "Write":
            return f"✏️  Writing {_short(inp.get('file_path', '?'))}"
        if name:
            return f"🔧 {name}"
        return ""

    def _initialize_from_config(self, config_dict: dict) -> None:
        """Create workspace from the coordinator's proposed config."""
        from agentos.kernel.event_log import SQLiteEventLog
        from agentos.kernel.seq import SeqCounter
        from agentos.schemas.budget import BudgetSpec
        from agentos.workspace.runtime import WorkspaceRuntime
        from agentos.workspace.schemas import WorkspaceConfig, WorkspaceParticipant

        team = []
        for t in config_dict.get("team", []):
            team.append(WorkspaceParticipant(
                name=t.get("name", "agent"),
                type=t.get("type", "agent"),
                specialization=t.get("specialization", ""),
            ))
        # Always add the human
        if not any(t.get("type") == "human" for t in config_dict.get("team", [])):
            team.append(WorkspaceParticipant(name="human", type="human"))

        budget_usd = config_dict.get("budget_usd", config_dict.get("budget", {}).get("max_cost_usd", 8.0))
        config = WorkspaceConfig(
            name=config_dict.get("name", "New Workspace"),
            goal=config_dict.get("goal", ""),
            team=team,
            budget=BudgetSpec(max_cost_usd=float(budget_usd)),
        )

        event_log = SQLiteEventLog(str(self._tmpdir / "workspace.db"))
        seq = SeqCounter()
        wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

        # Detect project dir
        project_dir = Path.cwd()
        if (project_dir / "agentos").is_dir():
            pass
        elif (project_dir.parent / "agentos").is_dir():
            project_dir = project_dir.parent

        self.runtime = WorkspaceRuntime(config, event_log, seq, wf_id, self.workspace,
                                         project_dir=project_dir)

        self._agent_ids = [p.name for p in config.team if p.type == "agent"]
        self._views = ["home"] + [f"agent:{a}" for a in self._agent_ids] + ["board", "tasks"]

        self.query_one("#header").update(
            f" [bold green]AgentOS[/] │ {config.name}"
        )

        self._add_to_view("home", f"[dim]Name: {config.name}[/]")
        self._add_to_view("home", f"[dim]Team: {', '.join(p.name for p in config.team)}[/]")
        self._add_to_view("home", "")
        self._add_to_view("home", "[yellow]coordinator[/]: Workspace ready. Launching agents...")

        # Switch from blank mode to active mode
        self.blank_mode = False
        self.run_supervisor()

    # ── Message routing ──────────────────────────────────────────

    def _add_to_view(self, view: str, msg: str) -> None:
        """Add a message to a specific view's history."""
        self._chat_history.setdefault(view, []).append(msg)
        # If we're currently on that view, also write to the log
        if view == self.current_view:
            self._chat_write(msg)

    def _chat_write(self, msg: str) -> None:
        """Write directly to the visible chat log."""
        try:
            self.query_one("#chat-log", RichLog).write(msg)
        except Exception:
            pass

    def _activity_write(self, msg: str) -> None:
        """Write to the activity strip."""
        try:
            self.query_one("#activity-strip", RichLog).write(msg)
        except Exception:
            pass

    # ── Supervisor ────────────────────────────────────────────────

    @work(thread=True)
    def run_supervisor(self) -> None:
        loop = asyncio.new_event_loop()

        def event_cb(event):
            with self._lock:
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

        with self._lock:
            events = list(self._events)

        for event in events:
            eid = id(event)
            if eid in self._seen:
                continue
            self._seen.add(eid)
            self._route_event(event)

        self._update_sidebar()
        self._update_header()

    def _route_event(self, e: dict) -> None:
        """Route events to the correct view — NOT everything to the chat."""
        t = e.get("type", "")

        if t == "board_post":
            author = e.get("author", "?")
            content = e.get("content", "")
            # Skip raw board renders that leak into events
            if "[WORKSPACE BOARD" in content or "[END BOARD]" in content:
                return
            if content.startswith("PINNED:") or content.startswith("Team:"):
                return
            self._board_posts.append(e)

            # Board view: show full post
            if author == "human":
                self._add_to_view("board", f"[cyan bold]you[/]: {content}")
            else:
                self._add_to_view("board", f"[magenta]{author}[/]: {content}")

            # Home view: coordinator and human messages show FULL, others compact
            if author == "coordinator":
                self._add_to_view("home", f"[yellow]coordinator[/]: {content}")
            elif author == "human":
                pass  # Already shown when the user typed it
            else:
                # Other agents' board posts: compact one-liner
                short = content[:80] + "…" if len(content) > 80 else content
                self._add_to_view("home", f"  [dim]📋 {author}:[/] {short}")

        elif t == "agent_spawned":
            agent = e.get("agent", "?")
            task = e.get("task", "?")
            self._add_to_view("home", f"  [green]●[/] [bold]{agent}[/] started: {task}")
            self._add_to_view(f"agent:{agent}", f"[dim]Started task: {task}[/]")

        elif t == "agent_completed":
            agent = e.get("agent", "?")
            task = e.get("task", "?")
            files = e.get("files", [])
            f_str = f" → {', '.join(files[:3])}" if files else ""
            self._add_to_view("home", f"  [green]✓[/] [bold]{agent}[/] completed: {task}{f_str}")
            self._add_to_view(f"agent:{agent}", f"[green]Completed: {task}{f_str}[/]")

        elif t == "agent_killed":
            agent = e.get("agent", "?")
            reason = e.get("reason", "?")
            self._add_to_view("home", f"  [red]✗[/] {agent} killed: {reason}")
            self._add_to_view(f"agent:{agent}", f"[red]Killed: {reason}[/]")

        elif t == "agent_activity":
            agent = e.get("agent", "?")
            activity = e.get("activity", "")
            # Always show in activity strip (bottom)
            self._activity_write(f"[dim]{agent}: {activity}[/]")
            # Show in agent's dedicated chat view
            self._add_to_view(f"agent:{agent}", f"  [dim]{activity}[/]")

        elif t == "message_to_human":
            sender = e.get("from", "?")
            content = e.get("content", "")
            # Full message in the sender's agent chat view
            self._add_to_view(f"agent:{sender}", f"[yellow]{sender}[/]: {content}")
            # Compact notification on home
            short = content[:80] + "…" if len(content) > 80 else content
            self._add_to_view("home", f"  [yellow]💬 {sender}[/]: {short}")
            self._add_to_view(f"agent:{sender}", f"[yellow]{sender}[/]: {content}")

        elif t == "workspace_completed":
            self._add_to_view("home", f"[green bold]■ Workspace completed: {e.get('reason', '?')}[/]")

        elif t == "plan_created":
            count = e.get("task_count", 0)
            self._add_to_view("home", f"  [yellow]coordinator[/]: Plan ready — {count} tasks created.")

        elif t == "agent_usage":
            inp = e.get("input_tokens", 0)
            out = e.get("output_tokens", 0)
            self._total_tokens += inp + out

        elif t == "status":
            verb = e.get("verb", "")
            msg = e.get("message", "")
            if verb in ("Coordinator", "Planning"):
                self._activity_write(f"[dim]{verb}: {msg}[/]")

    # ── Sidebar updates ───────────────────────────────────────────

    def _update_sidebar(self) -> None:
        if not self.runtime:
            return

        board = self.runtime.board.get_state()
        active = getattr(self.supervisor, '_active', {}) if self.supervisor else {}

        agent_lines = []
        for s in board.team_status:
            aid = s.agent_id
            is_human = any(p.type == "human" and p.name == aid for p in self.runtime.config.team)
            is_running = aid in active

            if is_running:
                last = self._last_activity(aid)
                elapsed = self._agent_elapsed(active.get(aid))
                short = (last[:18] + "…") if len(last) > 18 else last if last else ""
                agent_lines.append(f"[green]●[/] [bold]{aid}[/]\n  [dim]{short} {elapsed}[/]")
            elif is_human:
                agent_lines.append(f"[cyan]◉[/] [bold]{aid}[/] [dim](you)[/]")
            elif aid == "coordinator" or aid == "Coordinator":
                agent_lines.append(f"[yellow]◆[/] [dim]{aid}[/]")
            else:
                agent_lines.append(f"[dim]○ {aid}[/]")

        try:
            self.query_one("#agent-list").update("\n".join(agent_lines) or "[dim]No agents[/]")
        except Exception:
            pass

        tasks = self.runtime.backlog.get_all_tasks()
        task_lines = []
        for t in tasks[:10]:
            icon = "[green]✓[/]" if t.status == "done" else "[yellow]●[/]" if "progress" in t.status else "[red]🔒[/]" if t.status == "blocked" else "[dim]○[/]"
            name = (t.title[:20] + "…") if len(t.title) > 20 else t.title
            task_lines.append(f"{icon} {name}")
        if len(tasks) > 10:
            task_lines.append(f"[dim]+{len(tasks) - 10} more[/]")

        try:
            self.query_one("#task-summary").update("\n".join(task_lines) or "[dim]No tasks[/]")
        except Exception:
            pass

    def _update_header(self) -> None:
        if not self.runtime:
            return
        tasks = self.runtime.backlog.get_all_tasks()
        done = sum(1 for t in tasks if t.status == "done")
        status = self.runtime.state.status
        icon = "[green]●[/]" if status == "active" else "[yellow]●[/]"
        n_active = len(getattr(self.supervisor, '_active', {})) if self.supervisor else 0

        tokens_str = ""
        if self._total_tokens > 0:
            if self._total_tokens > 1_000_000:
                tokens_str = f" │ {self._total_tokens / 1_000_000:.1f}M tokens"
            elif self._total_tokens > 1_000:
                tokens_str = f" │ {self._total_tokens / 1_000:.0f}K tokens"
            else:
                tokens_str = f" │ {self._total_tokens} tokens"

        try:
            self.query_one("#header").update(
                f" [bold green]AgentOS[/] │ {self.runtime.config.name} │ "
                f"{icon} {status.upper()} │ {done}/{len(tasks)} tasks │ "
                f"{n_active} running{tokens_str}"
            )
        except Exception:
            pass

    def _last_activity(self, agent_id: str) -> str:
        with self._lock:
            for e in reversed(self._events):
                if e.get("type") == "agent_activity" and e.get("agent") == agent_id:
                    return e.get("activity", "")
        return ""

    def _agent_elapsed(self, info) -> str:
        if not info:
            return ""
        launch = getattr(info, "_launch_mono", None)
        if not launch:
            return ""
        e = time.monotonic() - launch
        return f"{e:.0f}s" if e < 60 else f"{e / 60:.1f}m"

    # ── Input ─────────────────────────────────────────────────────

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
        # Blank mode: setup conversation
        if self.blank_mode and not self.runtime:
            self._handle_setup_message(text)
            return

        if not self.workspace:
            return
        from agentos.comms.comms_state import write_human_command

        view = self.current_view

        if view == "home":
            # Talking to coordinator → post as directive on board
            self._add_to_view("home", f"[cyan bold]you[/]: {text}")
            write_human_command(self.workspace, {
                "action": "post_to_board",
                "payload": {"content": text, "section": "post", "speech_act": "directive"},
            })

        elif view.startswith("agent:"):
            # DM to specific agent
            agent_id = view.split(":", 1)[1]
            self._add_to_view(view, f"[cyan bold]you[/]: {text}")
            write_human_command(self.workspace, {
                "action": "send_message",
                "payload": {"to": agent_id, "content": text},
            })

        elif view == "board":
            # Post to board
            self._add_to_view("board", f"[cyan bold]you[/]: {text}")
            write_human_command(self.workspace, {
                "action": "post_to_board",
                "payload": {"content": text, "section": "post", "speech_act": "inform"},
            })

    def _handle_command(self, line: str) -> None:
        from agentos.comms.comms_state import write_human_command

        if line in ("/quit", "/q"):
            if self.workspace:
                write_human_command(self.workspace, {"action": "complete", "payload": {}})
            self._chat_write("[yellow]Stopping…[/]")
            self.set_timer(1.5, self.exit)

        elif line == "/pause":
            if self.workspace:
                write_human_command(self.workspace, {"action": "pause", "payload": {}})
            self._chat_write("[yellow]Paused.[/]")

        elif line == "/resume":
            if self.workspace:
                write_human_command(self.workspace, {"action": "resume", "payload": {}})
            self._chat_write("[green]Resumed.[/]")

        elif line == "/tasks":
            if self.runtime:
                self._chat_write("[bold]Tasks:[/]")
                for i, t in enumerate(self.runtime.backlog.get_all_tasks(), 1):
                    a = f" → {t.assigned_to}" if t.assigned_to else ""
                    icon = "✓" if t.status == "done" else "●" if "progress" in t.status else "🔒" if t.status == "blocked" else "○"
                    self._chat_write(f"  {icon} {i}. [{t.status}] {t.title}{a}")

        elif line == "/board":
            if self.runtime:
                self._chat_write(self.runtime.board.render_compact(max_tokens=500))

        elif line == "/files":
            if self.workspace:
                self._chat_write("[bold]Files:[/]")
                for f in sorted(self.workspace.rglob("*")):
                    if f.is_file() and ".agentos" not in str(f) and "backlog" not in str(f):
                        self._chat_write(f"  {f.relative_to(self.workspace)} ({f.stat().st_size:,}b)")

        elif line == "/status":
            if self.runtime:
                board = self.runtime.board.get_state()
                self._chat_write("[bold]Agent status:[/]")
                for s in board.team_status:
                    last = self._last_activity(s.agent_id)
                    extra = f" — {last}" if last else ""
                    self._chat_write(f"  {s.agent_name}: {s.state}{extra}")

        elif line.startswith("/msg "):
            parts = line[5:].split(" ", 1)
            if len(parts) == 2 and self.workspace:
                agent_id, content = parts
                write_human_command(self.workspace, {
                    "action": "send_message",
                    "payload": {"to": agent_id, "content": content},
                })
                self._add_to_view(f"agent:{agent_id}", f"[cyan bold]you[/]: {content}")
                self._chat_write(f"[cyan]→ {agent_id}[/]: {content}")
            else:
                self._chat_write("[dim]Usage: /msg <agent> <text>[/]")

        elif line.startswith("/task "):
            title = line[6:].strip()
            if self.workspace:
                write_human_command(self.workspace, {
                    "action": "create_task",
                    "payload": {"title": title},
                })
                self._chat_write(f"[dim]Task created: {title}[/]")

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
                        self._chat_write(f"[dim]Claimed: {tasks[idx].title}[/]")
                    else:
                        self._chat_write("[red]Invalid task number[/]")
                except ValueError:
                    self._chat_write("[dim]Usage: /claim <number>[/]")

        elif line == "/help":
            self._chat_write("[bold]Commands:[/]")
            self._chat_write("  [cyan]/board[/]       Show full board")
            self._chat_write("  [cyan]/tasks[/]       Show task list")
            self._chat_write("  [cyan]/claim N[/]     Claim task N")
            self._chat_write("  [cyan]/task Title[/]  Create new task")
            self._chat_write("  [cyan]/msg A text[/]  DM agent A")
            self._chat_write("  [cyan]/files[/]       Workspace files")
            self._chat_write("  [cyan]/status[/]      Agent details")
            self._chat_write("  [cyan]/pause[/]       Pause workspace")
            self._chat_write("  [cyan]/quit[/]        Stop and exit")
            self._chat_write("")
            self._chat_write("[bold]Navigation:[/]")
            self._chat_write("  F1           Home (coordinator)")
            self._chat_write("  F2           Agent DMs (← → cycle)")
            self._chat_write("  F3           Board")
            self._chat_write("  F4           Tasks")
            self._chat_write("  Ctrl+← →    Cycle views")

        else:
            self._chat_write("[dim]Unknown command. Type /help[/]")

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
        if not self._agent_ids or not self.current_view.startswith("agent:"):
            return
        self.agent_index = (self.agent_index + 1) % len(self._agent_ids)
        self.current_view = f"agent:{self._agent_ids[self.agent_index]}"
        self._switch_view()

    def action_prev_agent(self) -> None:
        if not self._agent_ids or not self.current_view.startswith("agent:"):
            return
        self.agent_index = (self.agent_index - 1) % len(self._agent_ids)
        self.current_view = f"agent:{self._agent_ids[self.agent_index]}"
        self._switch_view()

    def _switch_view(self) -> None:
        """Rebuild the chat log for the current view."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()

        view = self.current_view

        # View label + placeholder
        if view == "home":
            label = "[bold]COORDINATOR[/]"
            placeholder = "Chat with coordinator… (or /command)"
            tag = "🏠 home"
        elif view.startswith("agent:"):
            agent_id = view.split(":", 1)[1]
            label = f"[bold]💬 {agent_id}[/]"
            placeholder = f"Message {agent_id}…"
            tag = f"💬 {agent_id}"
            # Update agent_index to match
            if agent_id in self._agent_ids:
                self.agent_index = self._agent_ids.index(agent_id)
        elif view == "board":
            label = "[bold]📋 BOARD[/]"
            placeholder = "Post to the board…"
            tag = "📋 board"
        elif view == "tasks":
            label = "[bold]📝 TASKS[/]"
            placeholder = "/claim N or /task Title"
            tag = "📝 tasks"
        else:
            label = "[bold]?[/]"
            placeholder = ""
            tag = "?"

        try:
            self.query_one("#chat-label").update(label)
            self.query_one("#cmd-input", Input).placeholder = placeholder
            self.query_one("#view-tag").update(f"[dim]{tag}[/]")
        except Exception:
            pass

        # Replay history for this view
        history = self._chat_history.get(view, [])
        for msg in history[-50:]:  # last 50 messages
            chat_log.write(msg)

        # For tasks view, show current task list
        if view == "tasks" and self.runtime and not history:
            for i, t in enumerate(self.runtime.backlog.get_all_tasks(), 1):
                a = f" → {t.assigned_to}" if t.assigned_to else ""
                icon = "✓" if t.status == "done" else "●" if "progress" in t.status else "🔒" if t.status == "blocked" else "○"
                chat_log.write(f"  {icon} {i}. [{t.status}] {t.title}{a}")

        # For board view with no history, show current board
        if view == "board" and self.runtime and not history:
            chat_log.write(self.runtime.board.render_compact(max_tokens=600))

    def action_go_home(self) -> None:
        self.current_view = "home"
        self._switch_view()

    def action_go_agents(self) -> None:
        if self._agent_ids:
            self.current_view = f"agent:{self._agent_ids[self.agent_index]}"
            self._switch_view()

    def action_go_board(self) -> None:
        self.current_view = "board"
        self._switch_view()

    def action_go_tasks(self) -> None:
        self.current_view = "tasks"
        self._switch_view()

    def action_quit_app(self) -> None:
        self._handle_command("/quit")

    def action_toggle_pause(self) -> None:
        if self.runtime and self.runtime.state.status == "active":
            self._handle_command("/pause")
        else:
            self._handle_command("/resume")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    mock = "--mock" in flags
    skip_coord = "--skip-coordinator" in flags

    if not args:
        # Blank workspace: start with just the coordinator
        app = WorkspaceTUI(yaml_path=None)
        app.run()
        return

    yaml_path = Path(args[0])
    if not yaml_path.exists():
        print(f"File not found: {yaml_path}")
        sys.exit(1)

    app = WorkspaceTUI(yaml_path, mock=mock, skip_coordinator=skip_coord)
    app.run()


if __name__ == "__main__":
    main()
