"""WorkspaceRuntime — the main runtime loop for collaborative workspaces.

Manages the workspace lifecycle: board, backlog, workers, coordinator,
and the communication layer. Replaces the static DAG executor for
workspace-mode projects.

Fully autonomous mode via ``run()``: coordinator decomposes goals,
workers activate on ready tasks, outbox is routed automatically,
persistence and completion checks happen after every task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from agentos.comms.board_manager import BoardManager
from agentos.comms.board_hooks import BoardEventHooks
from agentos.comms.comms_state import write_comms_state
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    DirectMessage,
    SpeechAct,
)
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.completion import CompletionDetector
from agentos.workspace.context_summary import ContextSummaryManager
from agentos.workspace.cost_tracker import CostTracker
from agentos.workspace.hooks import (
    WorkspaceEvent,
    WorkspaceHookManager,
    register_default_hooks,
)
from agentos.workspace.schemas import (
    BacklogTask,
    BacklogTaskStatus,
    WorkspaceConfig,
    WorkspaceParticipant,
    WorkspaceState,
    WorkspaceStatus,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)


class WorkspaceRuntime:
    """Manages a collaborative workspace.

    Use ``start()`` to initialize, then either:
    - Manual mode: ``add_task()``, ``claim_task()``, ``complete_task()`` via CLI
    - Autonomous mode: ``await run()`` — coordinator decomposes, workers auto-activate
    """

    def __init__(
        self,
        config: WorkspaceConfig,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        workspace_dir: Path | None = None,
        execute_fn: Callable | None = None,
    ) -> None:
        self._config = config
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._workspace_dir = workspace_dir
        # Pluggable agent execution: async fn(agent_id, task, workspace) → dict
        self._execute_fn = execute_fn or self._default_execute

        # Core components
        self._board = BoardManager(event_log, seq, workflow_id)
        self._bus = MessageBus(event_log, seq, workflow_id)
        self._backlog = BacklogManager(
            event_log, seq, workflow_id,
            persist_dir=workspace_dir,
        )
        self._board_hooks = BoardEventHooks(
            self._board,
            total_budget_usd=config.budget.max_cost_usd,
            total_budget_tokens=config.budget.max_tokens,
        )

        # Context and cost
        self._summary_mgr = ContextSummaryManager(workspace_dir)
        self._cost_tracker = CostTracker(config.budget)
        self._completion = CompletionDetector(config, self._backlog)

        # Hooks
        self._hooks = WorkspaceHookManager()
        register_default_hooks(self._hooks)

        # State
        self._state = WorkspaceState(config=config)

        # Coordinator (created on start if enabled)
        self._coordinator = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def board(self) -> BoardManager:
        return self._board

    @property
    def bus(self) -> MessageBus:
        return self._bus

    @property
    def backlog(self) -> BacklogManager:
        return self._backlog

    @property
    def config(self) -> WorkspaceConfig:
        return self._config

    @property
    def state(self) -> WorkspaceState:
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Initialize the workspace: create board, post announcement, register team."""
        self._state.status = WorkspaceStatus.ACTIVE
        self._state.last_active = _utc_now_iso()

        # Post goal as pinned announcement
        self._board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="system",
            author_id="system",
            content=f"Project: {self._config.goal}",
            speech_act=SpeechAct.DIRECTIVE,
            pinned=True,
        ))

        # Register team on board
        for participant in self._config.team:
            state = "idle"
            if participant.type == "human":
                state = "idle"
            self._board.update_agent_status(AgentStatus(
                agent_id=participant.name,
                agent_name=participant.name,
                role=participant.specialization or ", ".join(str(r) for r in participant.roles),
                state=state,
            ))

        self._emit(EventType.WORKSPACE_CREATED, {
            "workspace_id": self._state.workspace_id,
            "name": self._config.name,
            "goal": self._config.goal,
            "team_size": len(self._config.team),
            "team_mode": self._config.team_mode,
        })

    def pause(self) -> None:
        """Pause the workspace."""
        self._state.status = WorkspaceStatus.PAUSED
        self._board.add_system_alert("Workspace paused.")
        self._emit(EventType.WORKSPACE_PAUSED, {
            "workspace_id": self._state.workspace_id,
        })

    def resume(self) -> None:
        """Resume from paused state."""
        self._state.status = WorkspaceStatus.ACTIVE
        self._state.last_active = _utc_now_iso()
        self._board.add_system_alert("Workspace resumed.")

    def complete(self) -> None:
        """Mark workspace as completed."""
        self._state.status = WorkspaceStatus.COMPLETED
        self._board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="system",
            author_id="system",
            content="Workspace completed.",
            speech_act=SpeechAct.INFORM,
            pinned=True,
        ))
        self._emit(EventType.WORKSPACE_COMPLETED, {
            "workspace_id": self._state.workspace_id,
        })

    # ------------------------------------------------------------------
    # Autonomous run loop
    # ------------------------------------------------------------------

    async def run(
        self,
        coordinator_llm: Callable | None = None,
        max_cycles: int = 50,
    ) -> dict:
        """Run the workspace autonomously until completion or budget exhaustion.

        1. Coordinator decomposes goal into tasks (if enabled)
        2. Loop: find ready tasks → activate workers → collect output → repeat
        3. Check completion after each task
        4. Persist state after each cycle

        *coordinator_llm*: async callable(system, prompt) → str for coordinator.
        If None, tasks must be added manually before calling run().

        Returns a dict with completion result and summary.
        """
        # Decompose goal if coordinator is enabled and backlog is empty
        if (
            self._config.coordinator.enabled
            and self._config.coordinator.auto_decompose
            and not self._backlog.get_all_tasks()
            and coordinator_llm is not None
        ):
            from agentos.workspace.coordinator import CoordinatorAgent

            self._coordinator = CoordinatorAgent(
                config=self._config.coordinator,
                workspace_config=self._config,
                backlog=self._backlog,
                board=self._board,
                bus=self._bus,
                event_log=self._event_log,
                seq=self._seq,
                workflow_id=self._workflow_id,
                llm_call=coordinator_llm,
            )
            tasks = await self._coordinator.decompose_goal()
            self._completion.set_initial_task_count(len(tasks))
            logger.info("Coordinator decomposed goal into %d tasks", len(tasks))

        # Main loop
        for cycle in range(max_cycles):
            if self._state.status != WorkspaceStatus.ACTIVE:
                break

            # Check completion
            result = self._completion.check()
            if result.complete:
                logger.info("Workspace complete: %s", result.reason)
                self._board.post(BoardPost(
                    section=BoardSection.ANNOUNCEMENT,
                    author_type="system", author_id="system",
                    content=f"Completion: {result.recommendation}",
                    speech_act=SpeechAct.INFORM, pinned=True,
                ))
                self.complete()
                return {"complete": True, "reason": result.reason, "cycles": cycle}

            # Find ready tasks (open, dependencies met)
            ready = self._backlog.get_ready_tasks()
            if not ready:
                # Nothing to do — check if we're stuck or just waiting
                in_progress = [
                    t for t in self._backlog.get_all_tasks()
                    if t.status in (BacklogTaskStatus.CLAIMED, BacklogTaskStatus.IN_PROGRESS,
                                     BacklogTaskStatus.IN_REVIEW)
                ]
                if not in_progress:
                    # No ready tasks, nothing in progress — all done or all blocked
                    blocked = self._backlog.get_blocked_tasks()
                    if blocked:
                        logger.warning("All remaining tasks are blocked")
                        self._board.add_system_alert(
                            f"{len(blocked)} task(s) blocked with no way to unblock."
                        )
                    break
                # Tasks in progress — wait for them (in a real runtime this would be async)
                break

            # Execute ready tasks
            for task in ready:
                if self._state.status != WorkspaceStatus.ACTIVE:
                    break

                # Find best agent for this task
                agent_id = self._pick_agent(task)
                if agent_id is None:
                    continue  # No agent available, skip

                # Claim and execute
                try:
                    self.claim_task(task.task_id, agent_id)
                    self._backlog.start_task(task.task_id)

                    output = await self._execute_fn(
                        agent_id, task, self._workspace_dir,
                    )

                    # Route outbox messages
                    self._route_outbox()

                    # Complete the task
                    self.complete_task(task.task_id, output)

                    # Update context summary
                    self._summary_mgr.update_agent_summary(
                        agent_id, output or {}, task.title,
                    )

                    # Track output size for diminishing returns
                    output_chars = len(json.dumps(output)) if output else 0
                    self._completion.record_task_output(output_chars)

                    # Fire hooks
                    self._hooks.fire(WorkspaceEvent.TASK_COMPLETED, {
                        "task_id": task.task_id,
                        "title": task.title,
                        "agent_id": agent_id,
                    })

                except Exception as exc:
                    logger.error("Task %s failed: %s", task.task_id, exc, exc_info=True)
                    self._backlog.cancel_task(task.task_id, str(exc))
                    self._hooks.fire(WorkspaceEvent.TASK_FAILED, {
                        "task_id": task.task_id,
                        "title": task.title,
                        "error": str(exc),
                    })

            # Persist after each cycle
            self._persist()

        return {
            "complete": self._state.status == WorkspaceStatus.COMPLETED,
            "reason": "max_cycles" if self._state.status == WorkspaceStatus.ACTIVE else self._state.status,
            "cycles": cycle + 1 if 'cycle' in dir() else 0,
        }

    def _pick_agent(self, task: BacklogTask) -> str | None:
        """Pick the best agent for a task based on suggestion and availability."""
        # Use coordinator's suggestion if available
        if task.suggested_for:
            participant = next(
                (p for p in self._config.team
                 if p.name == task.suggested_for and p.type == "agent"),
                None,
            )
            if participant:
                return participant.name

        # Find first available agent worker
        for p in self._config.team:
            if p.type == "agent" and "worker" in [str(r) for r in p.roles]:
                # Check if agent is not already busy
                assigned = self._backlog.get_tasks_for(p.name)
                active = [t for t in assigned if t.status in (
                    BacklogTaskStatus.CLAIMED, BacklogTaskStatus.IN_PROGRESS,
                )]
                if not active:
                    return p.name
        return None

    def _route_outbox(self) -> None:
        """Read outbox from workspace and route messages through comms."""
        if self._workspace_dir is None:
            return

        from agentos.adapters.tier2_shared import read_outbox

        outbox_msgs = read_outbox(self._workspace_dir)
        for msg_data in outbox_msgs:
            target = msg_data.get("to", "")
            content = msg_data.get("content", "")
            if not content:
                continue
            sender = msg_data.get("sender_id", "agent")

            if target == "board":
                self._board.post(BoardPost(
                    section=BoardSection(msg_data.get("section", "post")),
                    author_type="agent", author_id=sender,
                    content=content, speech_act=SpeechAct.INFORM,
                ))
            else:
                self._bus.send(DirectMessage(
                    sender_type="agent", sender_id=sender,
                    recipient_type="human" if target == "human" else "agent",
                    recipient_id=target, content=content,
                    speech_act=SpeechAct(msg_data.get("speech_act", "inform")),
                    workflow_id=self._workflow_id,
                ))

    def _persist(self) -> None:
        """Save workspace state to disk."""
        if self._workspace_dir is None:
            return
        from agentos.workspace.persistence import save_workspace

        save_workspace(
            self._workspace_dir,
            self._config,
            self._state,
            self._backlog.get_all_tasks(),
        )

    async def _default_execute(
        self,
        agent_id: str,
        task: BacklogTask,
        workspace: Path | None,
    ) -> dict:
        """Default agent execution: launch Claude Code with MCP comms."""
        if workspace is None:
            return {"summary": "No workspace directory configured.", "status": "failed"}

        from agentos.adapters.tier2_shared import write_board_state

        # Write comms state
        pending = self._bus.receive(agent_id)
        write_comms_state(workspace, self._board, pending, agent_id, self._workflow_id)
        write_board_state(workspace, self._board)

        # Build prompt
        comms_instructions = (
            "\n\n## Team Communication\n"
            "You have MCP tools: read_board, post_to_board, check_messages, send_message.\n"
            "Call read_board at the START. Post findings to the board when done.\n"
        )
        prompt = (
            f"You are {agent_id}. Your task:\n\n"
            f"## {task.title}\n{task.description}\n"
            f"{comms_instructions}"
        )

        # Build command
        cmd = [
            "claude", "--print",
            "--output-format", "json",
            "--max-turns", "8",
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
        cmd.extend(["--mcp-config", mcp_config, "-p", prompt])

        logger.info("Launching %s for task: %s", agent_id, task.title)

        try:
            result = subprocess.run(
                cmd, cwd=str(workspace),
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0 and result.stderr:
                logger.warning("Agent stderr: %s", result.stderr[:300])
        except subprocess.TimeoutExpired:
            return {"summary": "Agent timed out after 180s.", "status": "failed"}
        except FileNotFoundError:
            return {"summary": "claude CLI not found.", "status": "failed"}

        # Parse manifest if produced
        manifest_path = workspace / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                manifest_path.unlink()  # Clean for next agent
                return {
                    "summary": manifest.get("summary", "Task completed."),
                    "status": "succeeded",
                    "findings": manifest.get("findings", []),
                    "open_questions": manifest.get("open_questions", []),
                    "files_produced": manifest.get("files_produced", []),
                }
            except json.JSONDecodeError:
                pass

        return {"summary": "Task completed (no manifest).", "status": "succeeded"}

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def add_task(self, task: BacklogTask) -> str:
        """Add a task to the backlog and post to board."""
        task_id = self._backlog.create_task(task)

        # Post to board backlog section
        self._board.post(BoardPost(
            section=BoardSection.POST,
            author_type="system" if task.created_by == "system" else "agent",
            author_id=task.created_by or "system",
            content=f"New task: {task.title}" + (
                f" (suggested for {task.suggested_for})" if task.suggested_for else ""
            ),
            speech_act=SpeechAct.INFORM,
        ))
        return task_id

    def claim_task(self, task_id: str, participant_id: str) -> None:
        """Claim a task for a participant."""
        self._backlog.claim_task(task_id, participant_id)
        self._board.update_agent_status(AgentStatus(
            agent_id=participant_id,
            agent_name=participant_id,
            state="running",
            current_task=task_id,
        ))

    def complete_task(self, task_id: str, output: dict | None = None) -> None:
        """Mark a task as done and update the board."""
        self._backlog.complete_task(task_id, output)
        task = self._backlog.get_task(task_id)

        self._board.update_agent_status(AgentStatus(
            agent_id=task.assigned_to or "",
            agent_name=task.assigned_to or "",
            state="idle",
        ))

        if output and output.get("summary"):
            self._board.post(BoardPost(
                section=BoardSection.POST,
                author_type="agent",
                author_id=task.assigned_to or "unknown",
                content=f"Completed: {task.title} — {output['summary'][:200]}",
                speech_act=SpeechAct.STATUS,
            ))

    def submit_for_review(self, task_id: str, output: dict) -> None:
        """Submit a task for review."""
        self._backlog.submit_for_review(task_id, output)

    def approve_task(self, task_id: str, reviewer_id: str) -> None:
        """Approve a reviewed task."""
        self._backlog.approve_task(task_id, reviewer_id)
        task = self._backlog.get_task(task_id)
        self._board.update_agent_status(AgentStatus(
            agent_id=task.assigned_to or "",
            agent_name=task.assigned_to or "",
            state="idle",
        ))

    # ------------------------------------------------------------------
    # Team management
    # ------------------------------------------------------------------

    def add_participant(self, participant) -> None:
        """Add a participant to the team (dynamic mode)."""
        from agentos.workspace.schemas import WorkspaceParticipant
        if not isinstance(participant, WorkspaceParticipant):
            raise TypeError("Expected WorkspaceParticipant")

        self._config.team.append(participant)
        self._board.update_agent_status(AgentStatus(
            agent_id=participant.name,
            agent_name=participant.name,
            role=participant.specialization,
            state="idle",
        ))
        self._emit(EventType.WORKSPACE_TEAM_CHANGED, {
            "action": "added",
            "participant": participant.name,
            "type": participant.type,
        })

    def remove_participant(self, name: str) -> None:
        """Remove a participant from the team."""
        self._config.team = [p for p in self._config.team if p.name != name]
        self._emit(EventType.WORKSPACE_TEAM_CHANGED, {
            "action": "removed",
            "participant": name,
        })

    def lock_team(self) -> None:
        """Lock the team — no more changes."""
        from agentos.workspace.schemas import TeamMode
        self._config.team_mode = TeamMode.LOCKED
        self._board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="system",
            author_id="system",
            content="Team structure locked. No further changes allowed.",
            speech_act=SpeechAct.INFORM,
            pinned=True,
        ))

    def unlock_team(self, mode: str = "suggest") -> None:
        """Unlock the team with a specific mode."""
        from agentos.workspace.schemas import TeamMode
        self._config.team_mode = TeamMode(mode)

    # ------------------------------------------------------------------
    # Event routing
    # ------------------------------------------------------------------

    def on_event(self, event: Event) -> None:
        """Route events to board hooks and coordinator."""
        self._board_hooks.on_event(event)
        self._state.last_active = _utc_now_iso()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_board_state(self):
        return self._board.get_state()

    def get_backlog_summary(self) -> dict:
        tasks = self._backlog.get_all_tasks()
        by_status: dict[str, int] = {}
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
        return {
            "total": len(tasks),
            "by_status": by_status,
            "open": by_status.get("open", 0),
            "in_progress": by_status.get("in_progress", 0) + by_status.get("claimed", 0),
            "done": by_status.get("done", 0),
            "blocked": by_status.get("blocked", 0),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, event_type: EventType, payload: dict) -> None:
        self._event_log.append(Event(
            event_type=event_type,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload=payload,
        ))
