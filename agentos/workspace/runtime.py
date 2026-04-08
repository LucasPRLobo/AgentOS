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
        project_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._workspace_dir = workspace_dir
        self._project_dir = project_dir  # Actual codebase root for --add-dir
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

        # Collaborative components
        from agentos.comms.discussions import DiscussionManager
        from agentos.workspace.artifacts import ProjectArtifacts
        from agentos.workspace.context_curator import ContextCurator
        from agentos.workspace.verifier import TaskVerifier

        self._discussions = DiscussionManager(
            event_log, seq, workflow_id, self._bus, self._board,
        )
        self._artifacts = ProjectArtifacts(workspace_dir) if workspace_dir else None
        self._curator = ContextCurator(config, self._backlog, self._discussions, self._artifacts)
        self._verifier = TaskVerifier()

        # Hooks
        self._hooks = WorkspaceHookManager()
        register_default_hooks(self._hooks)

        # State
        self._state = WorkspaceState(config=config)

        # Coordinator (created on start if enabled)
        self._coordinator = None

        # Callback for human input (set by CLI/dashboard)
        self._human_input_fn: Callable | None = None
        # Callback for status messages (set by CLI/dashboard)
        self._status_fn: Callable | None = None

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

    @property
    def discussions(self):
        return self._discussions

    @property
    def artifacts(self):
        return self._artifacts

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

    def set_human_input(self, fn: Callable) -> None:
        """Set a callback for getting human input during discussions.

        *fn*: callable(prompt: str, options: list[str] | None) → str
        Used by CLI/dashboard to collect human responses.
        If not set, discussions auto-resolve after posting to board.
        """
        self._human_input_fn = fn

    def set_status_callback(self, fn: Callable) -> None:
        """Set a callback for status updates: fn(message: str, verb: str).

        *verb* is an action word like "Planning", "Executing", "Reviewing".
        Used by CLI to show what the system is doing.
        """
        self._status_fn = fn

    def _status(self, message: str, verb: str = "Working") -> None:
        """Emit a status update to the UI."""
        if self._status_fn:
            self._status_fn(message, verb)
        logger.info("[%s] %s", verb, message)

    async def run_concurrent(
        self,
        supervisor_config: Any = None,
        on_event: Callable | None = None,
        resume_from_checkpoint: bool = False,
    ) -> dict:
        """Run workspace with concurrent agent execution (the real vision).

        Agents run simultaneously. The human participates via commands.json.
        The supervisor polls every 2-3 seconds, routing messages and spawning
        agents as needed.

        When *resume_from_checkpoint* is True, the supervisor will skip the
        initial coordinator decomposition and restore agent session state from
        the previously saved checkpoint.
        """
        from agentos.workspace.schemas import SupervisorConfig
        from agentos.workspace.supervisor import WorkspaceSupervisor

        config = supervisor_config or SupervisorConfig()
        supervisor = WorkspaceSupervisor(self, config)

        if self._status_fn:
            supervisor.set_status_callback(self._status_fn)
        if on_event:
            supervisor.set_event_callback(on_event)

        return await supervisor.run(resume_from_checkpoint=resume_from_checkpoint)

    async def run(
        self,
        coordinator_llm: Callable | None = None,
        max_cycles: int = 50,
        use_coordinator_agent: bool = True,
        interactive: bool = False,
    ) -> dict:
        """Discussion-driven workspace execution.

        The flow is:
        1. Kickoff discussion (if no tasks exist)
        2. Loop: check discussions → find ready tasks → execute → verify → repeat
        3. Open discussions pause execution until resolved
        4. Completion check after each cycle

        When *interactive* is True, discussions block and wait for
        human_input_fn. When False, discussions are posted to the board
        and execution continues with non-dependent work.

        Returns a dict with completion result and summary.
        """
        # Phase 1: Decompose (with or without kickoff discussion)
        if (
            self._config.coordinator.enabled
            and self._config.coordinator.auto_decompose
            and not self._backlog.get_all_tasks()
        ):
            # Open kickoff discussion if interactive
            if interactive and self._human_input_fn:
                self._status("Opening kickoff discussion...", "Discussing")
                await self._kickoff_discussion()

            # Create tasks (via coordinator agent or manual)
            self._status("Coordinator is decomposing the goal into tasks...", "Planning")
            tasks = await self._run_coordinator_decomposition(
                coordinator_llm, use_coordinator_agent,
            )
            if tasks:
                self._completion.set_initial_task_count(len(tasks))
                # Write initial artifacts
                if self._artifacts:
                    self._artifacts.write_project(
                        goal=self._config.goal,
                        description=self._config.description,
                        criteria=self._config.acceptance_criteria,
                    )
                    self._artifacts.write_plan(
                        plan_summary=f"{len(tasks)} tasks created",
                        tasks=[t.model_dump(mode="json") for t in tasks],
                    )

        # Phase 2: Main execution loop
        for cycle in range(max_cycles):
            if self._state.status != WorkspaceStatus.ACTIVE:
                break

            # Check for open discussions — they may block in interactive mode
            if interactive and self._discussions.has_open_discussions():
                await self._handle_open_discussions()

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

            # Find ready tasks (OPEN status, dependencies met)
            ready = self._backlog.get_ready_tasks()
            if not ready:
                # Check for PROPOSED tasks needing spec
                proposed = [
                    t for t in self._backlog.get_all_tasks()
                    if t.status == BacklogTaskStatus.PROPOSED
                ]
                if proposed and interactive:
                    await self._spec_discussion(proposed[0])
                    continue

                # Check if we're stuck
                active = [
                    t for t in self._backlog.get_all_tasks()
                    if t.status in (
                        BacklogTaskStatus.CLAIMED, BacklogTaskStatus.IN_PROGRESS,
                        BacklogTaskStatus.COMPLETED, BacklogTaskStatus.IN_REVIEW,
                        BacklogTaskStatus.SPECIFYING,
                    )
                ]
                if not active:
                    blocked = self._backlog.get_blocked_tasks()
                    if blocked:
                        self._board.add_system_alert(
                            f"{len(blocked)} task(s) blocked."
                        )
                    break
                break

            # Execute ready tasks
            for task in ready:
                if self._state.status != WorkspaceStatus.ACTIVE:
                    break

                agent_id = self._pick_agent(task)
                if agent_id is None:
                    continue

                self._status(f"Executing: {task.title} (agent: {agent_id})", "Executing")
                await self._execute_task_with_review(task, agent_id, interactive)

            # Update artifacts
            if self._artifacts:
                self._artifacts.update_state(
                    tasks=[t.model_dump(mode="json") for t in self._backlog.get_all_tasks()],
                    team_status=[s.model_dump(mode="json") for s in self._board.get_state().team_status],
                )

            # Persist
            self._persist()

        return {
            "complete": self._state.status == WorkspaceStatus.COMPLETED,
            "reason": "max_cycles" if self._state.status == WorkspaceStatus.ACTIVE else self._state.status,
            "cycles": cycle + 1 if 'cycle' in dir() else 0,
        }

    # ------------------------------------------------------------------
    # Discussion-driven helpers
    # ------------------------------------------------------------------

    async def _kickoff_discussion(self) -> None:
        """Open a kickoff discussion with the human."""
        from agentos.workspace.facilitator_prompts import build_kickoff_prompt

        prompt = build_kickoff_prompt(self._config)
        # For now, use the prompt as the opening message directly
        # In production, the coordinator LLM would generate the message
        opening = (
            f"I've read your goal: \"{self._config.goal.strip()[:150]}\"\n\n"
            f"Before I plan, a few questions:\n"
            f"1. What's most important — speed, depth, or cost efficiency?\n"
            f"2. Any specific focus areas or constraints?\n"
            f"3. Who is the intended audience for the output?\n\n"
            f"I'm initially thinking we could use the team to tackle this in parallel. "
            f"What do you think?"
        )

        thread_id = self._discussions.open(
            discussion_type="kickoff",
            title="Project kickoff",
            opening_message=opening,
            options=["Prioritize depth", "Prioritize speed", "Balanced approach"],
        )

        # Get human response if interactive
        if self._human_input_fn:
            response = self._human_input_fn(
                opening + "\n\nYour response: ",
                ["Prioritize depth", "Prioritize speed", "Balanced approach"],
            )
            if response:
                self._discussions.add_message(
                    thread_id, "human", response, sender_type="human",
                )
                self._discussions.resolve(
                    thread_id, f"Human directed: {response}",
                )

    async def _spec_discussion(self, task: BacklogTask) -> None:
        """Open a spec discussion for a proposed task."""
        opening = (
            f"I'd like to discuss the approach for: **{task.title}**\n\n"
            f"{task.description}\n\n"
            f"Suggested for: {task.suggested_for or 'unassigned'}\n\n"
            f"Does this scope look right? Any adjustments?"
        )

        thread_id = self._discussions.open(
            discussion_type="task_spec",
            title=f"Spec: {task.title}",
            opening_message=opening,
            related_task_id=task.task_id,
        )
        self._backlog.start_specifying(task.task_id, thread_id)

        if self._human_input_fn:
            response = self._human_input_fn(opening + "\n\nYour response: ", None)
            if response:
                self._discussions.add_message(
                    thread_id, "human", response, sender_type="human",
                )
                self._discussions.resolve(thread_id, f"Spec agreed: {response}")
                self._backlog.finalize_spec(
                    task.task_id,
                    spec=task.description,
                    approach=response,
                    expected_output=task.spec_expected_output or "",
                )

    async def _execute_task_with_review(
        self, task: BacklogTask, agent_id: str, interactive: bool,
    ) -> None:
        """Execute a task with optional review discussion."""
        try:
            self.claim_task(task.task_id, agent_id)
            self._backlog.start_task(task.task_id)

            # Write task spec as artifact
            if self._artifacts and task.spec:
                self._artifacts.write_task_spec(
                    task.task_id, task.title,
                    task.spec, task.spec_approach or "", task.spec_expected_output or "",
                )

            # Build curated context and execute
            output = await self._execute_fn(agent_id, task, self._workspace_dir)

            self._route_outbox()

            # Mark as completed (awaiting review)
            self._backlog.mark_completed(task.task_id, output)

            # Verify output
            self._status(f"Verifying output for: {task.title}", "Verifying")
            verification = self._verifier.verify(task, output)

            if verification.recommendation == "auto_accept" and not interactive:
                # Clean pass, non-interactive — skip review, go straight to done
                self._backlog.start_review(task.task_id, "auto-review")
                self._backlog.accept_review(task.task_id, "auto_accepted")
                logger.info("Task %s auto-accepted", task.title)
            elif interactive and self._human_input_fn:
                # Open review discussion with the human
                await self._review_discussion(task, output, verification)
            else:
                # Non-interactive, needs review — accept with note
                self._backlog.start_review(task.task_id, "auto-review")
                self._backlog.accept_review(task.task_id, "accepted")

            # Write output artifact
            if self._artifacts:
                self._artifacts.write_task_output(
                    task.task_id, task.title,
                    (output or {}).get("summary", ""),
                    [(f.get("finding", str(f)) if isinstance(f, dict) else str(f))
                     for f in (output or {}).get("findings", [])],
                )

            # Update summaries
            self._summary_mgr.update_agent_summary(agent_id, output or {}, task.title)
            output_chars = len(json.dumps(output)) if output else 0
            self._completion.record_task_output(output_chars)

            self._hooks.fire(WorkspaceEvent.TASK_COMPLETED, {
                "task_id": task.task_id, "title": task.title, "agent_id": agent_id,
            })

        except Exception as exc:
            logger.error("Task %s failed: %s", task.task_id, exc, exc_info=True)
            try:
                self._backlog.cancel_task(task.task_id, str(exc))
            except ValueError:
                pass
            self._hooks.fire(WorkspaceEvent.TASK_FAILED, {
                "task_id": task.task_id, "title": task.title, "error": str(exc),
            })

    async def _review_discussion(
        self, task: BacklogTask, output: dict | None,
        verification,
    ) -> None:
        """Open a review discussion after task completion."""
        review_ctx = self._verifier.prepare_review_context(task, output, verification)
        summary = review_ctx["output_summary"]
        issues = review_ctx["verification_issues"]

        # Build rich review with file previews
        opening = f"**{task.title}** is complete.\n\n"
        opening += f"Summary: {summary}\n"

        # Show produced files
        files = (output or {}).get("files_produced", [])
        if files:
            opening += f"\nFiles produced:\n"
            for f in files[:5]:
                opening += f"  📄 {f}\n"
                # Preview small files
                if self._workspace_dir:
                    fpath = self._workspace_dir / f
                    if fpath.exists() and fpath.stat().st_size < 3000:
                        content = fpath.read_text()
                        preview = content[:300].replace('\n', '\n    ')
                        opening += f"    {preview}{'...' if len(content) > 300 else ''}\n\n"

        # Show findings
        findings = (output or {}).get("findings", [])
        if findings:
            opening += f"\nKey findings:\n"
            for f in findings[:5]:
                text = f.get("finding", str(f)) if isinstance(f, dict) else str(f)
                opening += f"  • {text[:100]}\n"

        # Show tool activity summary
        tool_calls = (output or {}).get("tool_calls", [])
        if tool_calls:
            opening += f"\nAgent activity ({len(tool_calls)} steps):\n"
            for tc in tool_calls[-5:]:
                opening += f"  → {tc}\n"

        if issues:
            opening += f"\n⚠ Issues found:\n" + "\n".join(f"  - {i}" for i in issues)

        opening += (
            f"\n\nShould we:\n"
            f"a) Accept and move on\n"
            f"b) Ask for revision\n"
            f"c) Go deeper on this topic"
        )

        thread_id = self._discussions.open(
            discussion_type="review",
            title=f"Review: {task.title}",
            opening_message=opening,
            related_task_id=task.task_id,
            options=["Accept", "Revise", "Go deeper"],
        )
        self._backlog.start_review(task.task_id, thread_id)

        if self._human_input_fn:
            response = self._human_input_fn(opening + "\n\nYour response: ", ["Accept", "Revise", "Go deeper"])
            if response:
                self._discussions.add_message(thread_id, "human", response, sender_type="human")

                if "accept" in response.lower() or response.strip().lower() == "a":
                    self._discussions.resolve(thread_id, "Accepted")
                    self._backlog.accept_review(task.task_id, "accepted")
                elif "revise" in response.lower() or response.strip().lower() == "b":
                    self._discussions.resolve(thread_id, f"Revision requested: {response}")
                    self._backlog.request_revision(task.task_id, response)
                else:
                    self._discussions.resolve(thread_id, f"Human feedback: {response}")
                    self._backlog.accept_review(task.task_id, "accepted_with_feedback")

    async def _handle_open_discussions(self) -> None:
        """Handle open discussions by prompting for human input."""
        if not self._human_input_fn:
            return

        for thread in self._discussions.get_open():
            last_msg = thread.messages[-1] if thread.messages else None
            if last_msg and last_msg.get("sender_type") == "human":
                continue  # Waiting for coordinator, not human

            prompt = f"[Discussion: {thread.title}]\n"
            prompt += thread.opening_message
            if len(thread.messages) > 1:
                prompt += "\n\nConversation so far:\n"
                for msg in thread.messages[1:]:
                    prompt += f"  {msg['sender_id']}: {msg['content']}\n"
            prompt += "\nYour response: "

            response = self._human_input_fn(prompt, thread.options)
            if response:
                self._discussions.add_message(
                    thread.thread_id, "human", response, sender_type="human",
                )
                # Auto-resolve simple discussions
                if thread.discussion_type in ("check_in",):
                    self._discussions.resolve(
                        thread.thread_id, f"Human response: {response}",
                    )

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

    async def _run_coordinator_decomposition(
        self,
        coordinator_llm: Callable | None,
        use_coordinator_agent: bool,
    ) -> list[BacklogTask]:
        """Run the coordinator to decompose the goal into tasks."""
        # Option 1: Claude Code instance as coordinator (preferred)
        if use_coordinator_agent and self._workspace_dir is not None:
            from agentos.workspace.coordinator_runner import run_decomposition

            tasks = run_decomposition(
                config=self._config,
                workspace=self._workspace_dir,
                board=self._board,
                bus=self._bus,
                backlog=self._backlog,
                workflow_id=self._workflow_id,
                project_dir=self._project_dir,
                status_fn=self._status_fn,
            )
            if tasks:
                logger.info("Coordinator (Claude Code) created %d tasks", len(tasks))
                return tasks
            logger.warning("Coordinator produced no tasks — falling back")

        # Option 2: Raw LLM call (fallback)
        if coordinator_llm is not None:
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
            logger.info("Coordinator (API) created %d tasks", len(tasks))
            return tasks

        logger.info("No coordinator configured — tasks must be added manually")
        return []

    async def _default_execute(
        self,
        agent_id: str,
        task: BacklogTask,
        workspace: Path | None,
    ) -> dict:
        """Default agent execution: launch Claude Code with streaming progress."""
        if workspace is None:
            return {"summary": "No workspace directory configured.", "status": "failed"}

        from agentos.adapters.tier2_shared import write_board_state

        # Write comms state
        pending = self._bus.receive(agent_id)
        write_comms_state(workspace, self._board, pending, agent_id, self._workflow_id)
        write_board_state(workspace, self._board)

        # Snapshot workspace files before execution
        files_before = set()
        for f in workspace.rglob("*"):
            if f.is_file() and ".agentos" not in str(f) and "_coordinator" not in str(f):
                files_before.add(str(f))

        # Build prompt with curated context
        context_section = ""
        if self._curator:
            ctx = self._curator.curate(task)
            context_section = self._curator.render_prompt_section(ctx)

        comms_instructions = (
            "\n\n## Team Communication\n"
            "You have MCP tools: read_board, post_to_board, check_messages, send_message.\n"
            "Call read_board at the START. Post findings to the board when done.\n"
        )
        prompt = (
            f"You are {agent_id}. Your task:\n\n"
            f"## {task.title}\n{task.description}\n"
            f"\n{context_section}\n"
            f"{comms_instructions}"
        )

        # Build command — use stream-json for live progress
        cmd = [
            "claude", "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", "15",
            "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
            "--disallowedTools", "Agent,TodoWrite,ToolSearch",
        ]

        # Give agent access to the actual project codebase
        if self._project_dir and self._project_dir.exists():
            cmd.extend(["--add-dir", str(self._project_dir)])

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

        # Stream execution with live progress
        import threading

        result_json = "{}"
        tool_calls: list[str] = []

        try:
            proc = subprocess.Popen(
                cmd, cwd=str(workspace),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )

            def _read_stream():
                nonlocal result_json
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "result":
                        result_json = line
                    elif event.get("type") == "assistant":
                        for block in event.get("message", {}).get("content", []):
                            if block.get("type") == "tool_use":
                                name = block.get("name", "")
                                inp = block.get("input", {})
                                # Show what the agent is doing
                                desc = self._describe_tool_call(name, inp)
                                if desc:
                                    tool_calls.append(desc)
                                    self._status(desc, agent_id)

            def _drain_stderr():
                for _ in proc.stderr:
                    pass

            t_out = threading.Thread(target=_read_stream, daemon=True)
            t_err = threading.Thread(target=_drain_stderr, daemon=True)
            t_out.start()
            t_err.start()

            proc.wait(timeout=600)
            t_out.join(timeout=2)
            t_err.join(timeout=2)

        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return {"summary": "Agent timed out after 600s.", "status": "failed"}
        except FileNotFoundError:
            return {"summary": "claude CLI not found.", "status": "failed"}

        # Detect new/modified files
        files_after = set()
        for f in workspace.rglob("*"):
            if f.is_file() and ".agentos" not in str(f) and "_coordinator" not in str(f):
                files_after.add(str(f))
        new_files = [
            str(Path(f).relative_to(workspace))
            for f in (files_after - files_before)
            if "backlog" not in f
        ]

        # Parse manifest if produced
        manifest_path = workspace / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                manifest_path.unlink()
                return {
                    "summary": manifest.get("summary", "Task completed."),
                    "status": "succeeded",
                    "findings": manifest.get("findings", []),
                    "open_questions": manifest.get("open_questions", []),
                    "files_produced": manifest.get("files_produced", new_files),
                    "tool_calls": tool_calls,
                }
            except json.JSONDecodeError:
                pass

        # No manifest — build output from what we observed
        summary = "Task completed."
        if new_files:
            summary += f" Produced: {', '.join(new_files[:5])}"
        if tool_calls:
            summary += f" ({len(tool_calls)} tool calls)"

        return {
            "summary": summary,
            "status": "succeeded",
            "files_produced": new_files,
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _describe_tool_call(name: str, inp: dict) -> str:
        """Human-readable description of a tool call.

        Inspired by Claude Code's getActivityDescription() pattern.
        Shows enough context for the human to understand what's happening.
        """
        def _short_path(p: str) -> str:
            """Shorten long paths to just filename or last 2 segments."""
            parts = p.replace("\\", "/").split("/")
            if len(parts) <= 2:
                return p
            return "/".join(parts[-2:])

        if name == "Read":
            path = inp.get("file_path", inp.get("path", "?"))
            return f"📖 Reading {_short_path(path)}"
        if name == "Write":
            path = inp.get("file_path", inp.get("path", "?"))
            return f"✏️  Writing {_short_path(path)}"
        if name == "Edit":
            path = inp.get("file_path", "?")
            return f"🔧 Editing {_short_path(path)}"
        if name == "Glob":
            pattern = inp.get("pattern", "?")
            return f"🔍 Finding files: {pattern}"
        if name == "Grep":
            pattern = inp.get("pattern", "?")
            path = inp.get("path", "")
            where = f" in {_short_path(path)}" if path else ""
            return f"🔎 Searching for '{pattern[:40]}'{where}"
        if name == "Bash":
            cmd = inp.get("command", "?")
            # Truncate long commands but show enough to be useful
            if len(cmd) > 80:
                cmd = cmd[:77] + "..."
            return f"⚡ {cmd}"
        if name == "read_board":
            return "📋 Reading workspace board"
        if name == "post_to_board":
            content = inp.get("content", "")
            return f"📋 Posting to board: {content[:50]}"
        if name == "check_messages":
            return "💬 Checking messages"
        if name == "send_message":
            to = inp.get("to", "?")
            return f"💬 Messaging {to}"
        if name == "NotebookEdit":
            return f"📓 Editing notebook"
        if name:
            # Generic fallback with input hint
            hint = ""
            for key in ("file_path", "path", "pattern", "command", "query"):
                if key in inp:
                    val = str(inp[key])[:40]
                    hint = f": {val}"
                    break
            return f"🔧 {name}{hint}"
        return ""

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
