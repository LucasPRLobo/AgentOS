"""WorkspaceRuntime — the main runtime loop for collaborative workspaces.

Manages the workspace lifecycle: board, backlog, workers, coordinator,
and the communication layer. Replaces the static DAG executor for
workspace-mode projects.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentos.comms.board_manager import BoardManager
from agentos.comms.board_hooks import BoardEventHooks
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    SpeechAct,
)
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.schemas import (
    BacklogTask,
    WorkspaceConfig,
    WorkspaceState,
    WorkspaceStatus,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)


class WorkspaceRuntime:
    """Manages a collaborative workspace."""

    def __init__(
        self,
        config: WorkspaceConfig,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        workspace_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._workspace_dir = workspace_dir

        # Core components
        self._board = BoardManager(event_log, seq, workflow_id)
        self._bus = MessageBus(event_log, seq, workflow_id)
        self._backlog = BacklogManager(event_log, seq, workflow_id)
        self._board_hooks = BoardEventHooks(
            self._board,
            total_budget_usd=config.budget.max_cost_usd,
            total_budget_tokens=config.budget.max_tokens,
        )

        # State
        self._state = WorkspaceState(config=config, workflow_id=workflow_id)

        # Coordinator (wired in Phase 3B)
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
