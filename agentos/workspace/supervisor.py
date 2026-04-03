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


class PersistentAgent:
    """Tracks a persistent agent with resumable Claude Code session.

    Agents are never killed after a task. They go IDLE and can be
    woken up for messages or new tasks via `claude --continue`.
    """

    def __init__(self, agent_id: str, workspace_id: str):
        self.agent_id = agent_id
        self.session_name = f"agentos-{workspace_id}-{agent_id}"
        self.state: str = "idle"           # idle, working, responding
        self.current_task_id: str | None = None
        self.current_proc: subprocess.Popen | None = None
        self.session_started: bool = False  # Has the first turn happened?
        self.pending_messages: list[dict] = []  # DMs queued while busy
        self.launch_time: float | None = None
        self.last_activity: str = ""

    @property
    def is_busy(self) -> bool:
        return self.state in ("working", "responding")


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
        self._active: dict[str, AgentProcessState] = {}  # backward compat
        self._procs: dict[str, subprocess.Popen] = {}
        self._stdout_threads: dict[str, threading.Thread] = {}
        self._tick_count = 0
        self._last_coordinator_time = 0.0
        self._pending_human_messages: list[str] = []

        # Persistent agents — never killed, only go idle
        self._agents: dict[str, PersistentAgent] = {}
        wf_id = runtime._workflow_id if hasattr(runtime, '_workflow_id') else "ws"
        for p in runtime.config.team:
            if p.type == "agent":
                self._agents[p.name] = PersistentAgent(p.name, wf_id)

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

        # 2b. Coordinator responses to human messages
        self._process_coordinator_responses()

        # 2c. Wake idle agents that have pending DMs
        self._wake_agents_for_messages()

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

    def _build_agent_cmd(
        self, agent_id: str, prompt: str,
        max_turns: int = 15,
        model: str | None = None,
    ) -> list[str]:
        """Build the claude CLI command for an agent invocation."""
        workspace = self._rt._workspace_dir
        agent = self._agents.get(agent_id)

        cmd = [
            "claude", "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(max_turns),
            "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
            "--disallowedTools", "Agent,TodoWrite,ToolSearch",
            "--name", agent.session_name if agent else f"agentos-{agent_id}",
        ]

        if model:
            cmd.extend(["--model", model])

        # Use --continue for subsequent turns (persistent session)
        if agent and agent.session_started:
            cmd.append("--continue")

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
        return cmd

    def _spawn_agent(self, agent_id: str, task: BacklogTask) -> None:
        """Wake an agent for a task. Uses --continue for subsequent turns."""
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        agent = self._agents.get(agent_id)
        if not agent:
            return
        if agent.is_busy:
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

        # Build prompt — first turn includes role setup, subsequent turns are shorter
        if not agent.session_started:
            prompt = (
                f"You are {agent_id}, a team member in an AgentOS workspace.\n"
                f"You are part of a team working on: {self._rt.config.goal.strip()[:200]}\n\n"
                f"## Team Communication\n"
                f"You have MCP tools: read_board, post_to_board, check_messages, "
                f"send_message, report_progress.\n"
                f"IMPORTANT:\n"
                f"- Call read_board at the START and every few steps\n"
                f"- Call check_messages FREQUENTLY — the human may message you\n"
                f"- When you receive a message from the human, you MUST reply using send_message\n"
                f"- Post findings to the board as you discover them\n\n"
                f"## Your Task\n"
                f"### {task.title}\n{task.description}\n"
                f"\n{context_section}"
            )
        else:
            prompt = (
                f"New task assigned to you:\n\n"
                f"### {task.title}\n{task.description}\n"
                f"\n{context_section}\n\n"
                f"Remember to check_messages and read_board before starting."
            )

        cmd = self._build_agent_cmd(agent_id, prompt)

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
        info._files_before = files_before  # type: ignore[attr-defined]
        info._launch_mono = time.monotonic()  # type: ignore[attr-defined]

        # Update persistent agent state
        agent.state = "working"
        agent.current_task_id = task.task_id
        agent.current_proc = proc
        agent.session_started = True
        agent.launch_time = time.monotonic()

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
        is_dm_response = task_id == "dm-response"

        # Set persistent agent to IDLE first
        agent = self._agents.get(info.agent_id)
        if agent:
            agent.state = "idle"
            agent.current_task_id = None
            agent.current_proc = None

        # DM responses don't have a task to complete
        if is_dm_response:
            self._rt.board.update_agent_status(AgentStatus(
                agent_id=info.agent_id, agent_name=info.agent_id, state="idle",
            ))
            self._emit_event("agent_completed", {
                "agent": info.agent_id, "task": "responded to messages", "files": [],
            })
            return

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
        task_title = "unknown"
        try:
            task_title = self._rt.backlog.get_task(task_id).title
        except ValueError:
            pass

        self._rt.board.update_agent_status(AgentStatus(
            agent_id=info.agent_id, agent_name=info.agent_id, state="idle",
        ))
        self._rt.board.post(BoardPost(
            section=BoardSection.POST,
            author_type="agent", author_id=info.agent_id,
            content=f"Completed: {task_title}",
            speech_act=SpeechAct.INFORM,
        ))

        self._emit_event("agent_completed", {
            "agent": info.agent_id,
            "task": task_title,
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
            content = payload.get("content", "")
            self._rt.board.post(BoardPost(
                section=BoardSection(payload.get("section", "post")),
                author_type="human", author_id="human",
                content=content,
                speech_act=SpeechAct(payload.get("speech_act", "directive")),
            ))
            # Trigger coordinator response to the human's message
            if content:
                self._schedule_coordinator_response(content)

        elif action == "send_message":
            to = payload.get("to", "")
            content = payload.get("content", "")
            if to and content:
                msg = {
                    "from": "human", "content": content,
                    "speech_act": "directive",
                    "timestamp": _utc_now_iso(),
                }
                # Write to inbox file (for check_messages MCP tool)
                write_agent_inbox(self._rt._workspace_dir, to, [msg])
                # Also queue for persistent agent wake-up
                agent = self._agents.get(to)
                if agent:
                    agent.pending_messages.append(msg)

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
    # Wake idle agents for pending messages
    # ------------------------------------------------------------------

    def _wake_agents_for_messages(self) -> None:
        """Wake agents that have pending DMs — idle agents get woken,
        busy agents get interrupted and resumed with the message."""
        for agent_id, agent in self._agents.items():
            if not agent.pending_messages:
                continue

            if agent.state == "idle":
                self._wake_for_messages(agent)
            elif agent.state == "working" and agent.current_proc:
                self._interrupt_for_messages(agent)

    def _wake_for_messages(self, agent: PersistentAgent) -> None:
        """Resume an idle agent's session to handle DMs."""
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        messages = list(agent.pending_messages)
        agent.pending_messages.clear()

        # Build prompt with the messages
        msg_text = "\n".join(
            f"From {m.get('from', '?')}: {m.get('content', '')}"
            for m in messages
        )
        prompt = (
            f"You have messages from the team. Read and respond to each one "
            f"using send_message.\n\n{msg_text}\n\n"
            f"After responding, call read_board to see if there's anything else to do."
        )

        # DM responses: fewer turns, lighter model
        cmd = self._build_agent_cmd(agent.agent_id, prompt, max_turns=3, model="sonnet")

        # Snapshot files
        files_before = set()
        for f in workspace.rglob("*"):
            if f.is_file() and ".agentos" not in str(f):
                files_before.add(str(f))

        proc = subprocess.Popen(
            cmd, cwd=str(workspace),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        info = AgentProcessState(
            agent_id=agent.agent_id, task_id="dm-response",
            pid=proc.pid, launched_at=_utc_now_iso(),
        )
        self._active[agent.agent_id] = info
        self._procs[agent.agent_id] = proc
        info._files_before = files_before  # type: ignore[attr-defined]
        info._launch_mono = time.monotonic()  # type: ignore[attr-defined]

        agent.state = "responding"
        agent.current_proc = proc

        # Monitor stdout
        t = threading.Thread(
            target=self._monitor_stdout, args=(agent.agent_id, proc),
            daemon=True,
        )
        t.start()
        self._stdout_threads[agent.agent_id] = t

        threading.Thread(
            target=lambda: [None for _ in proc.stderr],
            daemon=True,
        ).start()

        self._rt.board.update_agent_status(AgentStatus(
            agent_id=agent.agent_id, agent_name=agent.agent_id,
            state="running", current_task="responding to messages",
        ))

        self._emit_event("agent_spawned", {
            "agent": agent.agent_id, "task": "responding to messages",
        })

    def _interrupt_for_messages(self, agent: PersistentAgent) -> None:
        """Interrupt a working agent to handle DMs, then resume their task.

        1. Kill the current process (work-in-progress is saved in session)
        2. Resume with --continue: "You have messages. Respond, then continue your task."
        3. Agent responds to DMs and picks up where it left off.
        """
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        # Kill current process
        if agent.current_proc and agent.current_proc.poll() is None:
            agent.current_proc.terminate()
            try:
                agent.current_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent.current_proc.kill()
                agent.current_proc.wait()

        # Clean up tracking
        self._active.pop(agent.agent_id, None)
        self._procs.pop(agent.agent_id, None)
        self._stdout_threads.pop(agent.agent_id, None)

        # Build messages text
        messages = list(agent.pending_messages)
        agent.pending_messages.clear()

        msg_text = "\n".join(
            f"From {m.get('from', '?')}: {m.get('content', '')}"
            for m in messages
        )

        # Get current task info for resume context
        task_title = ""
        if agent.current_task_id:
            try:
                task = self._rt.backlog.get_task(agent.current_task_id)
                task_title = task.title
            except ValueError:
                pass

        prompt = (
            f"IMPORTANT: You have urgent messages from the team. "
            f"Stop what you're doing and respond to them FIRST using send_message.\n\n"
            f"## Messages\n{msg_text}\n\n"
            f"After responding, continue working on your current task"
            + (f": {task_title}" if task_title else "") + ".\n"
            f"Call read_board to check for any other updates."
        )

        # Interrupt: respond then resume — more turns needed since it continues the task
        cmd = self._build_agent_cmd(agent.agent_id, prompt, max_turns=10)

        # Snapshot files
        files_before = set()
        for f in workspace.rglob("*"):
            if f.is_file() and ".agentos" not in str(f):
                files_before.add(str(f))

        proc = subprocess.Popen(
            cmd, cwd=str(workspace),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        info = AgentProcessState(
            agent_id=agent.agent_id,
            task_id=agent.current_task_id or "dm-response",
            pid=proc.pid, launched_at=_utc_now_iso(),
        )
        self._active[agent.agent_id] = info
        self._procs[agent.agent_id] = proc
        info._files_before = files_before  # type: ignore[attr-defined]
        info._launch_mono = time.monotonic()  # type: ignore[attr-defined]

        agent.state = "working"  # Still working, just handling DMs first
        agent.current_proc = proc

        # Monitor stdout
        t = threading.Thread(
            target=self._monitor_stdout, args=(agent.agent_id, proc),
            daemon=True,
        )
        t.start()
        self._stdout_threads[agent.agent_id] = t

        threading.Thread(
            target=lambda: [None for _ in proc.stderr],
            daemon=True,
        ).start()

        self._emit_event("agent_activity", {
            "agent": agent.agent_id,
            "activity": "📨 Interrupted — responding to messages",
        })

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
        self._pending_coordinator_reason = reason

    # ------------------------------------------------------------------
    # Coordinator conversation (responds to human messages)
    # ------------------------------------------------------------------

    def _schedule_coordinator_response(self, human_message: str) -> None:
        """Queue a human message for coordinator response on next tick."""
        self._pending_human_messages.append(human_message)

    def _process_coordinator_responses(self) -> None:
        """If there are pending human messages, invoke coordinator to respond."""
        if not self._pending_human_messages:
            return

        # Batch all pending messages
        messages = list(self._pending_human_messages)
        self._pending_human_messages.clear()

        # Cooldown check
        now = time.monotonic()
        if now - self._last_coordinator_time < self._config.coordinator_cooldown:
            return
        self._last_coordinator_time = now

        # Run in background thread to not block the tick
        threading.Thread(
            target=self._run_coordinator_response,
            args=(messages,),
            daemon=True,
        ).start()

    def _run_coordinator_response(self, human_messages: list[str]) -> None:
        """Invoke a short coordinator session to respond to the human."""
        workspace = self._rt._workspace_dir
        if workspace is None:
            return

        # Build context
        board_compact = self._rt.board.render_compact(max_tokens=300)
        tasks = self._rt.backlog.get_all_tasks()
        task_summary = "\n".join(
            f"- [{t.status}] {t.title}" + (f" → {t.assigned_to}" if t.assigned_to else "")
            for t in tasks
        )
        active_agents = ", ".join(self._active.keys()) if self._active else "none"
        human_text = "\n".join(f"Human: {m}" for m in human_messages)

        prompt = (
            f"You are the workspace coordinator. The human lead just sent a message. "
            f"Respond conversationally — acknowledge what they said, answer any questions, "
            f"and explain what the team is doing.\n\n"
            f"## Human's Message\n{human_text}\n\n"
            f"## Current State\n"
            f"Active agents: {active_agents}\n"
            f"Tasks:\n{task_summary}\n\n"
            f"## Board\n{board_compact}\n\n"
            f"## Instructions\n"
            f"Respond in 2-4 sentences. Be conversational, not formal. "
            f"If the human asked a question, answer it. "
            f"If they gave a directive, acknowledge it and explain how you'll act on it. "
            f"If they're just chatting, respond naturally.\n\n"
            f"Respond with ONLY your message text — no JSON, no markdown headers, just your reply."
        )

        try:
            cmd = [
                "claude", "--print",
                "--output-format", "text",
                "--max-turns", "1",
                "--model", "sonnet",
                "-p", prompt,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                cwd=str(workspace),
            )
            response = result.stdout.strip()
            if response:
                # Post coordinator response to board
                self._rt.board.post(BoardPost(
                    section=BoardSection.POST,
                    author_type="agent", author_id="coordinator",
                    content=response,
                    speech_act=SpeechAct.INFORM,
                ))
                self._emit_event("board_post", {
                    "author": "coordinator", "content": response,
                })
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("Coordinator response failed: %s", exc)

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
        """Read agent stdout in background, emit events for tool calls and usage."""
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

            elif event.get("type") == "result":
                # Capture token usage from the result event
                usage = event.get("usage", event.get("result", {}).get("usage", {}))
                if usage:
                    self._emit_event("agent_usage", {
                        "agent": agent_id,
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_input_tokens", 0),
                        "cache_write": usage.get("cache_creation_input_tokens", 0),
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
