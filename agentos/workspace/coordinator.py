"""CoordinatorAgent — AI-driven workspace coordination.

Uses a frontier model to decompose goals, manage the backlog,
handle failures, propose team changes, and assess completion.
Implements the two-ledger pattern (Task Ledger + Progress Ledger).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agentos.comms.board_manager import BoardManager
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import BoardPost, BoardSection, DirectMessage, SpeechAct
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.coordinator_prompts import (
    build_completion_assessment_prompt,
    build_decomposition_prompt,
    build_failure_recovery_prompt,
    build_replan_prompt,
)
from agentos.workspace.schemas import (
    BacklogTask,
    CoordinatorConfig,
    WorkspaceConfig,
    WorkspaceContextSummary,
)

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """AI coordinator for workspace planning and management."""

    def __init__(
        self,
        config: CoordinatorConfig,
        workspace_config: WorkspaceConfig,
        backlog: BacklogManager,
        board: BoardManager,
        bus: MessageBus,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        llm_call: Any = None,
    ) -> None:
        self._config = config
        self._workspace_config = workspace_config
        self._backlog = backlog
        self._board = board
        self._bus = bus
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        # llm_call: async callable(system, prompt) -> str  (injected for testability)
        self._llm_call = llm_call

        # Two-ledger state
        self._workspace_summary = WorkspaceContextSummary(
            goal=workspace_config.goal,
            intent=workspace_config.goal,
        )
        self._stall_count = 0
        self._last_done_count = 0
        self._failure_attempts: dict[str, int] = {}

    @property
    def workspace_summary(self) -> WorkspaceContextSummary:
        return self._workspace_summary

    # ------------------------------------------------------------------
    # Goal decomposition
    # ------------------------------------------------------------------

    async def decompose_goal(self) -> list[BacklogTask]:
        """Decompose the workspace goal into backlog tasks."""
        prompt = build_decomposition_prompt(self._workspace_config)
        response = await self._call_llm(
            "You are a project coordinator. Respond only with valid JSON.",
            prompt,
        )

        parsed = self._parse_json(response)
        if parsed is None:
            logger.warning("Coordinator failed to produce valid decomposition JSON")
            return []

        tasks_data = parsed.get("tasks", [])
        plan_summary = parsed.get("plan_summary", "")

        # Build title→id map for dependency resolution
        title_to_id: dict[str, str] = {}
        tasks: list[BacklogTask] = []

        for td in tasks_data:
            task = BacklogTask(
                title=td.get("title", "Untitled"),
                description=td.get("description", ""),
                created_by="coordinator",
                suggested_for=td.get("suggested_for"),
                required_role=td.get("required_role"),
                acceptance_criteria=td.get("acceptance_criteria", []),
                estimated_minutes=td.get("estimated_minutes"),
                priority=td.get("priority", "normal"),
                model_tier=td.get("model_tier"),
            )
            title_to_id[task.title] = task.task_id
            tasks.append(task)

        # Resolve title-based dependencies to IDs
        for i, td in enumerate(tasks_data):
            dep_titles = td.get("depends_on_titles", [])
            tasks[i].depends_on = [
                title_to_id[t] for t in dep_titles if t in title_to_id
            ]

        # Register tasks in backlog
        for task in tasks:
            self._backlog.create_task(task)

        self._backlog.recompute_priorities()

        # Update workspace summary
        self._workspace_summary.current_plan = [t.title for t in tasks]
        self._workspace_summary.current_status = plan_summary
        self._workspace_summary.tasks_remaining = len(tasks)

        # Post plan to board
        task_list = "\n".join(f"  • {t.title} → {t.suggested_for or 'unassigned'}" for t in tasks)
        self._board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="agent",
            author_id="coordinator",
            content=f"Plan: {plan_summary}\n\nTasks:\n{task_list}",
            speech_act=SpeechAct.INFORM,
        ))

        return tasks

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def handle_task_completed(self, task_id: str) -> None:
        """Handle a task completion — check progress, unblock, assess."""
        task = self._backlog.get_task(task_id)
        self._backlog.reset_stall(task_id)

        # Update summary
        self._workspace_summary.tasks_completed += 1
        self._workspace_summary.tasks_remaining = max(
            0, self._workspace_summary.tasks_remaining - 1
        )
        if task.output and task.output.get("summary"):
            self._workspace_summary.key_artifacts.append(
                f"{task.title}: {task.output['summary'][:100]}"
            )

        await self._check_progress()

    async def handle_task_failed(self, task_id: str, error: str) -> None:
        """Handle a task failure — follow escalation ladder."""
        attempt = self._failure_attempts.get(task_id, 0) + 1
        self._failure_attempts[task_id] = attempt

        available = [p.name for p in self._workspace_config.team if p.type == "agent"]

        prompt = build_failure_recovery_prompt(
            task_title=self._backlog.get_task(task_id).title,
            error=error,
            attempt_number=attempt,
            available_agents=available,
        )
        response = await self._call_llm(
            "You are a project coordinator handling a failure. Respond with JSON.",
            prompt,
        )

        parsed = self._parse_json(response)
        action = parsed.get("action", "escalate") if parsed else "escalate"
        reason = parsed.get("reason", "Failed to determine recovery action") if parsed else ""

        self._board.post(BoardPost(
            section=BoardSection.ALERT,
            author_type="agent",
            author_id="coordinator",
            content=f"Task failed: {self._backlog.get_task(task_id).title}. "
                    f"Action: {action}. Reason: {reason}",
            speech_act=SpeechAct.ALERT,
        ))

    async def handle_message(self, message: DirectMessage) -> None:
        """Handle a message directed at the coordinator."""
        # Post acknowledgment to board
        self._board.post(BoardPost(
            section=BoardSection.POST,
            author_type="agent",
            author_id="coordinator",
            content=f"Received from {message.sender_id}: {message.content[:200]}",
            speech_act=SpeechAct.INFORM,
        ))

    # ------------------------------------------------------------------
    # Progress tracking (two-ledger pattern)
    # ------------------------------------------------------------------

    async def _check_progress(self) -> None:
        """Check if progress is being made. Replan if stalled."""
        tasks = self._backlog.get_all_tasks()
        done_count = sum(1 for t in tasks if t.status == "done")

        if done_count > self._last_done_count:
            self._stall_count = 0
            self._last_done_count = done_count
        else:
            self._stall_count += 1

        if self._stall_count >= 2:
            logger.info("Progress stalled for 2+ cycles — triggering replan")
            await self.replan()
            self._stall_count = 0

    async def replan(self) -> None:
        """Rewrite both ledgers and adjust the plan."""
        tasks = self._backlog.get_all_tasks()
        completed = [t.title for t in tasks if t.status == "done"]
        failed = [t.title for t in tasks if t.status == "cancelled"]

        prompt = build_replan_prompt(
            self._workspace_summary,
            completed, failed,
            self._board.render_compact(max_tokens=400),
        )
        response = await self._call_llm(
            "You are a project coordinator replanning. Respond with JSON.",
            prompt,
        )

        parsed = self._parse_json(response)
        if parsed is None:
            return

        assessment = parsed.get("assessment", "")
        updated_plan = parsed.get("updated_plan", [])

        self._workspace_summary.current_plan = updated_plan
        self._workspace_summary.current_status = assessment[:200]

        # Create new tasks if any
        for td in parsed.get("new_tasks", []):
            task = BacklogTask(
                title=td.get("title", "Untitled"),
                description=td.get("description", ""),
                created_by="coordinator-replan",
                suggested_for=td.get("suggested_for"),
                priority=td.get("priority", "normal"),
            )
            self._backlog.create_task(task)
            self._workspace_summary.tasks_remaining += 1

        self._board.post(BoardPost(
            section=BoardSection.ANNOUNCEMENT,
            author_type="agent",
            author_id="coordinator",
            content=f"Replanned: {assessment[:300]}",
            speech_act=SpeechAct.INFORM,
        ))

    # ------------------------------------------------------------------
    # Completion assessment
    # ------------------------------------------------------------------

    async def assess_completion(self) -> dict:
        """Evaluate whether the workspace goal is met."""
        artifacts = [
            a for a in self._workspace_summary.key_artifacts
        ]
        prompt = build_completion_assessment_prompt(
            self._workspace_config,
            self._workspace_summary,
            artifacts,
            self._board.render_compact(max_tokens=400),
        )
        response = await self._call_llm(
            "You are a project coordinator assessing completion. Respond with JSON.",
            prompt,
        )
        return self._parse_json(response) or {
            "overall_complete": False,
            "recommendation": "needs human review",
        }

    # ------------------------------------------------------------------
    # Team management
    # ------------------------------------------------------------------

    async def propose_team_change(self, reason: str) -> None:
        """Post a team change proposal to the board."""
        self._board.post(BoardPost(
            section=BoardSection.QUESTION,
            author_type="agent",
            author_id="coordinator",
            content=f"Team change proposal: {reason}",
            speech_act=SpeechAct.PROPOSE,
        ))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_llm(self, system: str, prompt: str) -> str:
        """Call the LLM. Uses injected callable or returns empty for tests."""
        if self._llm_call is not None:
            return await self._llm_call(system, prompt)
        return "{}"

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Extract JSON from LLM response (handles markdown fences)."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            return None
