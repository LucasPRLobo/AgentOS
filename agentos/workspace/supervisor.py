"""WorkspaceSupervisor — concurrent, event-driven workspace execution.

Replaces the sequential run() loop. Manages concurrent agent processes,
routes messages, invokes the coordinator reactively, and processes
human commands. The human is a first-class participant: worker and/or
manager, always able to influence the workspace on the next tick.

Every 2-3 seconds the supervisor:
  1. COLLECT — check agent completions, outboxes, human commands
  2. REACT — route messages, process events, invoke coordinator
  3. SPAWN — launch agents for ready tasks (up to concurrency limit)
  4. CHECK — completion, budget, stalls
  5. WRITE — update board.json, agent inboxes, human inbox, artifacts
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from agentos.comms.comms_state import (
    append_event,
    ensure_agent_dir,
    read_agent_status,
    read_all_agent_outboxes,
    read_human_commands,
    write_agent_inbox,
    write_board_file,
    write_human_inbox,
)
from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)
from agentos.workspace.schemas import (
    AgentProcessState,
    BacklogTask,
    BacklogTaskStatus,
    HumanCommand,
    SupervisorConfig,
    WorkspaceStatus,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)


class WorkspaceSupervisor:
    """Persistent supervisor for concurrent workspace execution.

    The supervisor is a polling loop — not an executor. It monitors
    shared state files, reacts to events, and manages concurrent
    Claude Code agent processes.

    The human participates via .agentos/human/commands.json (CLI/dashboard
    writes commands, supervisor reads them each tick).
    """

    def __init__(self, runtime, config: SupervisorConfig | None = None):
        self._rt = runtime
        self._config = config or SupervisorConfig()
        self._active: dict[str, AgentProcessState] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._stdout_threads: dict[str, threading.Thread] = {}
        self._tick_count = 0
        self._last_coordinator_time = 0.0

        # Callbacks (set by CLI/dashboard)
        self._on_event = None       # fn(event_dict) — for live display
        self._on_status = None      # fn(message, verb) — for spinner

    def set_event_callback(self, fn) -> None:
        """Set callback for live events (displayed to human)."""
        self._on_event = fn

    def set_status_callback(self, fn) -> None:
        """Set callback for status spinner."""
        self._on_status = fn

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> dict:
        """Run the supervisor until workspace completes or is paused."""
        self._rt.start()
        self._emit_event("workspace_started", {"name": self._rt.config.name})

        # Initial decomposition if no tasks
        if not self._rt.backlog.get_all_tasks():
            self._status("Coordinator decomposing goal...", "Planning")
            await self._invoke_coordinator("decompose")

        # Write initial shared state
        self._write_shared_state()

        # Main loop
        while self._rt.state.status == WorkspaceStatus.ACTIVE:
            await self._tick()
            await asyncio.sleep(self._config.poll_interval)

        return {
            "complete": self._rt.state.status == WorkspaceStatus.COMPLETED,
            "reason": str(self._rt.state.status),
            "ticks": self._tick_count,
        }

    # ------------------------------------------------------------------
    # Tick — the heartbeat of the workspace
    # ------------------------------------------------------------------

    async def _tick(self):
        """Single supervisor cycle."""
        self._tick_count += 1

        # 1. COLLECT
        completed = self._check_completed_agents()
        outbox_msgs = read_all_agent_outboxes(self._rt._workspace_dir)
        human_cmds = read_human_commands(self._rt._workspace_dir)

        # 2. REACT
        for info in completed:
            self._on_agent_completed(info)

        for agent_id, msgs in outbox_msgs.items():
            for msg in msgs:
                self._route_message(agent_id, msg)

        for cmd_data in human_cmds:
            cmd = HumanCommand(**cmd_data) if isinstance(cmd_data, dict) else cmd_data
            self._process_human_command(cmd)

        # Check stalls
        self._check_stalls()

        # 3. SPAWN (up to concurrency limit)
        if self._config.auto_spawn:
            self._spawn_ready_agents()

        # 4. CHECK
        result = self._rt._completion.check()
        if result.complete:
            self._rt.complete()
            self._emit_event("workspace_completed", {"reason": result.reason})
            return

        # 5. WRITE
        self._write_shared_state()

    # ------------------------------------------------------------------
    # Agent process management
    # ------------------------------------------------------------------

    def _spawn_agent(self, agent_id: str, task: BacklogTask) -> None:
        """Launch a Claude Code instance for a task. Non-blocking."""
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        ensure_agent_dir(workspace, agent_id)

        # Claim and start the task
        try:
            self._rt.claim_task(task.task_id, agent_id)
            self._rt.backlog.start_task(task.task_id)
        except ValueError as exc:
            logger.warning("Cannot start task %s: %s", task.task_id, exc)
            return

        # Write task spec artifact
        if self._rt._artifacts and task.spec:
            self._rt._artifacts.write_task_spec(
                task.task_id, task.title,
                task.spec, task.spec_approach or "", task.spec_expected_output or "",
            )

        # Build curated context
        context_section = ""
        if self._rt._curator:
            ctx = self._rt._curator.curate(task)
            context_section = self._rt._curator.render_prompt_section(ctx)

        # Build agent prompt
        prompt = (
            f"You are {agent_id}. Your task:\n\n"
            f"## {task.title}\n{task.description}\n"
            f"\n{context_section}\n"
            f"\n## Team Communication\n"
            f"You have MCP tools: read_board, post_to_board, check_messages, "
            f"send_message, report_progress.\n"
            f"IMPORTANT:\n"
            f"- Call read_board at the START and every few steps — the human may post directions\n"
            f"- Call check_messages periodically — teammates or the human may message you\n"
            f"- Post findings to the board as you discover them (not just at the end)\n"
            f"- If the human gives a directive on the board, acknowledge it and adjust\n"
        )

        # Build command
        cmd = [
            "claude", "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", "15",
            "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
            "--disallowedTools", "Agent,TodoWrite,ToolSearch",
        ]

        if self._rt._project_dir and self._rt._project_dir.exists():
            cmd.extend(["--add-dir", str(self._rt._project_dir)])

        mcp_config = json.dumps({
            "mcpServers": {
                "agentos-comms": {
                    "command": sys.executable,
                    "args": [
                        "-m", "agentos.comms.mcp_server",
                        "--workspace", str(workspace),
                        "--agent-id", agent_id,
                    ],
                    "env": {"AGENTOS_AGENT_ID": agent_id},
                }
            }
        })
        cmd.extend(["--mcp-config", mcp_config, "-p", prompt])

        # Snapshot files before execution (for detecting new files)
        files_before = set()
        for f in workspace.rglob("*"):
            if f.is_file() and ".agentos" not in str(f):
                files_before.add(str(f))

        # Launch non-blocking
        proc = subprocess.Popen(
            cmd, cwd=str(workspace),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        info = AgentProcessState(
            agent_id=agent_id, task_id=task.task_id,
            pid=proc.pid, launched_at=_utc_now_iso(),
        )
        self._active[agent_id] = info
        self._procs[agent_id] = proc
        # Store metadata for later
        info._files_before = files_before  # type: ignore[attr-defined]
        info._launch_mono = time.monotonic()  # type: ignore[attr-defined]

        # Monitor stdout in background thread (for progress display)
        t = threading.Thread(
            target=self._monitor_stdout, args=(agent_id, proc),
            daemon=True,
        )
        t.start()
        self._stdout_threads[agent_id] = t

        # Drain stderr in background
        threading.Thread(
            target=lambda: [None for _ in proc.stderr],
            daemon=True,
        ).start()

        # Update board
        self._rt.board.update_agent_status(AgentStatus(
            agent_id=agent_id, agent_name=agent_id,
            state="running", current_task=task.title,
        ))

        self._emit_event("agent_spawned", {
            "agent": agent_id, "task": task.title, "pid": proc.pid,
        })

    def _check_completed_agents(self) -> list[AgentProcessState]:
        """Poll all active processes. Return those that finished."""
        completed = []
        for agent_id, proc in list(self._procs.items()):
            ret = proc.poll()
            if ret is not None:
                info = self._active.pop(agent_id, None)
                self._procs.pop(agent_id, None)
                self._stdout_threads.pop(agent_id, None)
                if info:
                    info.status = "completed" if ret == 0 else "failed"
                    completed.append(info)
        return completed

    def _on_agent_completed(self, info: AgentProcessState) -> None:
        """Handle a completed agent — parse output, verify, route."""
        workspace = self._rt._workspace_dir
        task_id = info.task_id

        # Detect new files
        files_before = getattr(info, "_files_before", set())
        new_files = []
        if workspace:
            for f in workspace.rglob("*"):
                if f.is_file() and ".agentos" not in str(f) and str(f) not in files_before:
                    if "backlog" not in str(f):
                        new_files.append(str(Path(f).relative_to(workspace)))

        # Parse manifest if exists
        output = {"summary": "Task completed.", "status": "succeeded", "files_produced": new_files}
        if workspace:
            manifest_path = workspace / "manifest.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    manifest_path.unlink()
                    output = {
                        "summary": manifest.get("summary", "Task completed."),
                        "status": "succeeded",
                        "findings": manifest.get("findings", []),
                        "files_produced": manifest.get("files_produced", new_files),
                    }
                except json.JSONDecodeError:
                    pass

        if new_files:
            output["summary"] += f" Files: {', '.join(new_files[:5])}"

        # Mark completed and verify
        try:
            self._rt.backlog.mark_completed(task_id, output)
            verification = self._rt._verifier.verify(
                self._rt.backlog.get_task(task_id), output,
            )
            # Auto-accept (coordinator can still review later)
            self._rt.backlog.start_review(task_id, "auto-review")
            self._rt.backlog.accept_review(task_id, "accepted")
        except ValueError as exc:
            logger.warning("Post-completion error for %s: %s", task_id, exc)

        # Write artifact
        if self._rt._artifacts:
            self._rt._artifacts.write_task_output(
                task_id, info.agent_id,
                output.get("summary", ""),
                [str(f) for f in output.get("findings", [])],
            )

        # Update board
        self._rt.board.update_agent_status(AgentStatus(
            agent_id=info.agent_id, agent_name=info.agent_id, state="idle",
        ))
        self._rt.board.post(BoardPost(
            section=BoardSection.POST,
            author_type="agent", author_id=info.agent_id,
            content=f"Completed: {self._rt.backlog.get_task(task_id).title}",
            speech_act=SpeechAct.INFORM,
        ))

        self._emit_event("agent_completed", {
            "agent": info.agent_id,
            "task": self._rt.backlog.get_task(task_id).title,
            "files": new_files,
        })

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def _route_message(self, sender_id: str, msg: dict) -> None:
        """Route an outbox message to the right destination."""
        target = msg.get("to", "")
        content = msg.get("content", "")
        if not content:
            return

        if target == "board":
            section = msg.get("section", "post")
            self._rt.board.post(BoardPost(
                section=BoardSection(section),
                author_type="agent", author_id=sender_id,
                content=content, speech_act=SpeechAct(msg.get("speech_act", "inform")),
            ))
            self._emit_event("board_post", {"author": sender_id, "content": content[:80]})

        elif target == "human":
            write_human_inbox(self._rt._workspace_dir, [{
                "from": sender_id, "content": content,
                "speech_act": msg.get("speech_act", "inform"),
                "timestamp": msg.get("timestamp", _utc_now_iso()),
            }])
            self._emit_event("message_to_human", {"from": sender_id, "content": content[:80]})

        else:
            # Message to another agent — write to their inbox
            write_agent_inbox(self._rt._workspace_dir, target, [{
                "from": sender_id, "content": content,
                "speech_act": msg.get("speech_act", "inform"),
                "timestamp": msg.get("timestamp", _utc_now_iso()),
            }])
            self._emit_event("message_routed", {"from": sender_id, "to": target})

    # ------------------------------------------------------------------
    # Human command processing
    # ------------------------------------------------------------------

    def _process_human_command(self, cmd: HumanCommand) -> None:
        """Process a command from the human. The human is always heard."""
        action = cmd.action if isinstance(cmd, HumanCommand) else cmd.get("action", "")
        payload = cmd.payload if isinstance(cmd, HumanCommand) else cmd.get("payload", {})

        self._emit_event("human_command", {"action": action})

        if action == "post_to_board":
            self._rt.board.post(BoardPost(
                section=BoardSection(payload.get("section", "post")),
                author_type="human", author_id="human",
                content=payload.get("content", ""),
                speech_act=SpeechAct(payload.get("speech_act", "directive")),
            ))

        elif action == "send_message":
            to = payload.get("to", "")
            content = payload.get("content", "")
            if to and content:
                write_agent_inbox(self._rt._workspace_dir, to, [{
                    "from": "human", "content": content,
                    "speech_act": "directive",
                    "timestamp": _utc_now_iso(),
                }])

        elif action == "claim_task":
            task_id = payload.get("task_id", "")
            participant = payload.get("participant", "human")
            try:
                self._rt.claim_task(task_id, participant)
                self._rt.board.post(BoardPost(
                    section=BoardSection.STATUS,
                    author_type="human", author_id="human",
                    content=f"Claimed task: {self._rt.backlog.get_task(task_id).title}",
                    speech_act=SpeechAct.INFORM,
                ))
            except ValueError as exc:
                logger.warning("Human claim failed: %s", exc)

        elif action == "create_task":
            task = BacklogTask(
                title=payload.get("title", "Untitled"),
                description=payload.get("description", ""),
                created_by="human",
                suggested_for=payload.get("suggested_for"),
                priority=payload.get("priority", "normal"),
            )
            self._rt.add_task(task)

        elif action == "complete_task":
            task_id = payload.get("task_id", "")
            summary = payload.get("summary", "Completed by human")
            try:
                self._rt.complete_task(task_id, {"summary": summary})
            except ValueError as exc:
                logger.warning("Human complete failed: %s", exc)

        elif action == "set_priority":
            task_id = payload.get("task_id", "")
            priority = payload.get("priority", "normal")
            try:
                task = self._rt.backlog.get_task(task_id)
                task.priority = priority
                self._rt.backlog.recompute_priorities()
            except ValueError:
                pass

        elif action == "spawn_agent":
            # Dynamic agent spawning — coordinator's move, but human can too
            task_id = payload.get("task_id", "")
            agent_name = payload.get("agent_name", "")
            if task_id and agent_name:
                task = self._rt.backlog.get_task(task_id)
                self._spawn_agent(agent_name, task)

        elif action == "kill_agent":
            agent_id = payload.get("agent_id", "")
            if agent_id in self._procs:
                self._procs[agent_id].kill()
                self._emit_event("agent_killed", {"agent": agent_id})

        elif action == "reply_discussion":
            thread_id = payload.get("thread_id", "")
            content = payload.get("content", "")
            if thread_id and content:
                self._rt.discussions.add_message(
                    thread_id, "human", content, sender_type="human",
                )

        elif action == "pause":
            self._rt.pause()

        elif action == "resume":
            self._rt.resume()

        elif action == "complete":
            self._rt.complete()

        elif action == "replan":
            self._invoke_coordinator_sync("replan")

    # ------------------------------------------------------------------
    # Agent spawning
    # ------------------------------------------------------------------

    def _spawn_ready_agents(self) -> None:
        """Find ready tasks and launch agents for them."""
        slots = self._config.max_concurrent - len(self._active)
        if slots <= 0:
            return

        ready = self._rt.backlog.get_ready_tasks()
        for task in ready[:slots]:
            # Skip tasks already assigned to a running agent
            if task.assigned_to and task.assigned_to in self._active:
                continue
            # Skip tasks claimed by the human
            if task.assigned_to and any(
                p.type == "human" and p.name == task.assigned_to
                for p in self._rt.config.team
            ):
                continue

            agent_id = self._pick_agent(task)
            if agent_id and agent_id not in self._active:
                self._spawn_agent(agent_id, task)

    def _pick_agent(self, task: BacklogTask) -> str | None:
        """Pick the best available agent for a task.

        Prefers the suggested agent, but falls back to any idle agent
        if the suggested one is busy. Never assigns to human participants.
        """
        # Prefer suggested agent if available
        if task.suggested_for and task.suggested_for not in self._active:
            return task.suggested_for

        # Fall back to any idle agent
        for p in self._rt.config.team:
            if p.type == "agent" and p.name not in self._active:
                return p.name
        return None

    # ------------------------------------------------------------------
    # Stall detection
    # ------------------------------------------------------------------

    def _check_stalls(self) -> None:
        """Check for agents that have been running too long."""
        now = time.monotonic()
        for agent_id, info in list(self._active.items()):
            # Check heartbeat via status file
            status = read_agent_status(self._rt._workspace_dir, agent_id)
            if status and status.get("timestamp"):
                info.last_heartbeat = status["timestamp"]
                info.last_activity = status.get("activity", "")

            # Check timeout based on actual launch time
            proc = self._procs.get(agent_id)
            if proc and proc.poll() is None:
                launch_mono = getattr(info, "_launch_mono", now)
                elapsed = now - launch_mono
                if elapsed > self._config.agent_timeout:
                    logger.warning("Agent %s timed out after %.0fs — killing", agent_id, elapsed)
                    proc.kill()
                    info.status = "killed"
                    self._emit_event("agent_killed", {
                        "agent": agent_id,
                        "reason": f"timeout ({elapsed:.0f}s)",
                    })

    # ------------------------------------------------------------------
    # Coordinator (on-demand)
    # ------------------------------------------------------------------

    async def _invoke_coordinator(self, reason: str, **context) -> None:
        """Invoke the coordinator for a planning decision (non-blocking)."""
        # Cooldown check
        now = time.monotonic()
        if now - self._last_coordinator_time < self._config.coordinator_cooldown:
            return
        self._last_coordinator_time = now

        if reason == "decompose":
            # Run in thread so it doesn't block the event loop
            loop = asyncio.get_event_loop()
            tasks = await loop.run_in_executor(None, self._run_decomposition_sync)
            if tasks:
                self._rt._completion.set_initial_task_count(len(tasks))
                self._emit_event("plan_created", {"task_count": len(tasks)})
                if self._rt._artifacts:
                    self._rt._artifacts.write_project(
                        goal=self._rt.config.goal,
                        description=self._rt.config.description,
                        criteria=self._rt.config.acceptance_criteria,
                    )
                    self._rt._artifacts.write_plan(
                        plan_summary=f"{len(tasks)} tasks created",
                        tasks=[t.model_dump(mode="json") for t in tasks],
                    )

    def _run_decomposition_sync(self):
        """Synchronous coordinator decomposition (runs in thread pool)."""
        from agentos.workspace.coordinator_runner import run_decomposition
        return run_decomposition(
            config=self._rt.config,
            workspace=self._rt._workspace_dir,
            board=self._rt.board,
            bus=self._rt.bus,
            backlog=self._rt.backlog,
            workflow_id=self._rt._workflow_id,
            project_dir=self._rt._project_dir,
            status_fn=self._on_status,
        )

    def _invoke_coordinator_sync(self, reason: str) -> None:
        """Synchronous coordinator invocation (for human-triggered replan)."""
        # Schedule it — will run on next tick cycle
        self._pending_coordinator_reason = reason

    # ------------------------------------------------------------------
    # Shared state writing
    # ------------------------------------------------------------------

    def _write_shared_state(self) -> None:
        """Write all shared state files for concurrent access."""
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        # Board
        board_state = self._rt.board.get_state()
        board_data = board_state.model_dump(mode="json")
        board_data["_compact"] = self._rt.board.render_compact(max_tokens=400)
        write_board_file(workspace, board_data)
        self._rt.board.save_to_file(workspace / ".agentos" / "board.json")

        # Artifacts
        if self._rt._artifacts:
            self._rt._artifacts.update_state(
                tasks=[t.model_dump(mode="json") for t in self._rt.backlog.get_all_tasks()],
                team_status=[s.model_dump(mode="json") for s in board_state.team_status],
            )

        # Persist backlog (already auto-persists, but force here)
        self._rt._persist()

    # ------------------------------------------------------------------
    # Stdout monitoring (background thread per agent)
    # ------------------------------------------------------------------

    def _monitor_stdout(self, agent_id: str, proc: subprocess.Popen) -> None:
        """Read agent stdout in background, emit events for tool calls."""
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        desc = self._describe_tool_call(name, inp)
                        if desc:
                            self._emit_event("agent_activity", {
                                "agent": agent_id, "activity": desc,
                            })

    @staticmethod
    def _describe_tool_call(name: str, inp: dict) -> str:
        """Human-readable tool call description."""
        def _short(p: str) -> str:
            parts = p.replace("\\", "/").split("/")
            return "/".join(parts[-2:]) if len(parts) > 2 else p

        if name == "Read":
            return f"📖 Reading {_short(inp.get('file_path', inp.get('path', '?')))}"
        if name == "Write":
            return f"✏️  Writing {_short(inp.get('file_path', inp.get('path', '?')))}"
        if name == "Edit":
            return f"🔧 Editing {_short(inp.get('file_path', '?'))}"
        if name == "Glob":
            return f"🔍 Finding: {inp.get('pattern', '?')}"
        if name == "Grep":
            return f"🔎 Searching: {inp.get('pattern', '?')[:40]}"
        if name == "Bash":
            cmd = inp.get("command", "?")
            return f"⚡ {cmd[:70]}"
        # MCP tools come prefixed with mcp__agentos-comms__
        clean = name.replace("mcp__agentos-comms__", "").replace("mcp__agentos_comms__", "")
        if clean == "read_board":
            return "📋 Reading board"
        if clean == "post_to_board":
            content = inp.get("content", "")
            return f"📋 Posting: {content[:50]}" if content else "📋 Posting to board"
        if clean == "check_messages":
            return "💬 Checking messages"
        if clean == "send_message":
            return f"💬 Messaging {inp.get('to', '?')}"
        if clean == "report_progress":
            summary = inp.get("summary", "")
            return f"📊 {summary[:50]}" if summary else "📊 Reporting progress"
        if clean in ("read_board", "post_to_board", "check_messages", "send_message", "report_progress"):
            return f"📋 {clean}"
        if name:
            return f"🔧 {name}"
        return ""

    # ------------------------------------------------------------------
    # Events + status
    # ------------------------------------------------------------------

    def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit an event to the event stream and callback."""
        event = {"type": event_type, "ts": _utc_now_iso(), **data}
        if self._rt._workspace_dir:
            append_event(self._rt._workspace_dir, event)
        if self._on_event:
            self._on_event(event)

    def _status(self, message: str, verb: str = "Working") -> None:
        """Emit a status update for the UI."""
        if self._on_status:
            self._on_status(message, verb)
