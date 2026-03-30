"""Board auto-update hooks — board reacts to system events automatically.

Listens to events and updates the board without manual posting:
- Task state changes → team status updates
- Budget thresholds → alerts
- Gate events → questions / resolutions on the board
- Errors → alerts
- Protocol timeouts → alerts
"""

from __future__ import annotations

import logging

from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import AgentStatus, BoardPost, BoardSection, SpeechAct
from agentos.schemas.events import Event, EventType

logger = logging.getLogger(__name__)

# Budget thresholds that trigger board alerts (percentage consumed).
BUDGET_ALERT_THRESHOLDS = (0.60, 0.80, 0.95)


class BoardEventHooks:
    """Processes events and auto-updates the board.

    Called by the executor after emitting events, or used to tail
    the event log for catch-up processing.
    """

    def __init__(
        self,
        board_manager: BoardManager,
        total_budget_usd: float | None = None,
        total_budget_tokens: int | None = None,
    ) -> None:
        self._board = board_manager
        self._total_budget_usd = total_budget_usd
        self._total_budget_tokens = total_budget_tokens
        # Track which budget thresholds have already fired
        self._budget_alerts_fired: set[float] = set()
        # Track cumulative budget consumption
        self._consumed_usd: float = 0.0
        self._consumed_tokens: int = 0

    def on_event(self, event: Event) -> None:
        """Process a single event and update the board if appropriate."""
        handler = self._handlers.get(event.event_type)
        if handler is not None:
            handler(self, event)

    def process_events(self, events: list[Event]) -> int:
        """Process a batch of events.  Returns count of board updates made."""
        count = 0
        for event in events:
            before = self._board.get_state().version
            self.on_event(event)
            if self._board.get_state().version > before:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _handle_task_state_changed(self, event: Event) -> None:
        payload = event.payload
        task_id = payload.get("task_id", "")
        agent_id = payload.get("agent_id", "")
        new_state = payload.get("new_state", "")

        state_map = {
            "RUNNING": "running",
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
            "WAITING": "waiting",
            "PENDING": "pending",
        }
        board_state = state_map.get(new_state, "idle")

        self._board.update_agent_status(AgentStatus(
            agent_id=agent_id,
            agent_name=agent_id,  # Best we have from the event
            state=board_state,
            current_task=task_id if board_state == "running" else None,
        ))

        # Auto-post for completion and failure
        if new_state == "SUCCEEDED":
            summary = payload.get("summary", "")
            if summary:
                self._board.post(BoardPost(
                    section=BoardSection.POST,
                    author_type="system",
                    author_id="system",
                    content=f"[{agent_id}] Task completed: {summary[:200]}",
                    speech_act=SpeechAct.STATUS,
                ))

        elif new_state == "FAILED":
            error = payload.get("error", payload.get("summary", "unknown error"))
            self._board.add_system_alert(
                f"[{agent_id}] Task failed: {error[:200]}",
                expires_minutes=120,
            )

    def _handle_budget_consumed(self, event: Event) -> None:
        payload = event.payload
        self._consumed_usd += payload.get("cost_usd", 0.0)
        self._consumed_tokens += payload.get("tokens", 0)

        # Check USD thresholds
        if self._total_budget_usd and self._total_budget_usd > 0:
            ratio = self._consumed_usd / self._total_budget_usd
            for threshold in BUDGET_ALERT_THRESHOLDS:
                if ratio >= threshold and threshold not in self._budget_alerts_fired:
                    self._budget_alerts_fired.add(threshold)
                    pct = int(threshold * 100)
                    self._board.add_system_alert(
                        f"Budget at {pct}% (${self._consumed_usd:.2f} / ${self._total_budget_usd:.2f})",
                        expires_minutes=0,  # Never expires
                    )

        # Check token thresholds
        if self._total_budget_tokens and self._total_budget_tokens > 0:
            ratio = self._consumed_tokens / self._total_budget_tokens
            for threshold in BUDGET_ALERT_THRESHOLDS:
                key = threshold + 100  # Separate namespace from USD alerts
                if ratio >= threshold and key not in self._budget_alerts_fired:
                    self._budget_alerts_fired.add(key)
                    pct = int(threshold * 100)
                    self._board.add_system_alert(
                        f"Token budget at {pct}% ({self._consumed_tokens:,} / {self._total_budget_tokens:,})",
                        expires_minutes=0,
                    )

    def _handle_budget_exceeded(self, event: Event) -> None:
        payload = event.payload
        agent_id = payload.get("agent_id", "unknown")
        dimension = payload.get("dimension", "budget")
        self._board.post(BoardPost(
            section=BoardSection.ALERT,
            author_type="system",
            author_id="system",
            content=f"BUDGET EXCEEDED by {agent_id} ({dimension}). Execution halted.",
            speech_act=SpeechAct.ALERT,
            pinned=True,
        ))

    def _handle_gate_waiting(self, event: Event) -> None:
        payload = event.payload
        gate_id = payload.get("gate_id", "")
        gate_type = payload.get("gate_type", "approval")
        task_id = payload.get("task_id", "")
        self._board.post(BoardPost(
            section=BoardSection.QUESTION,
            author_type="system",
            author_id="system",
            content=f"Gate '{gate_id}' ({gate_type}) waiting for human input. Task: {task_id}",
            speech_act=SpeechAct.REQUEST,
        ))

    def _handle_gate_resolved(self, event: Event) -> None:
        payload = event.payload
        gate_id = payload.get("gate_id", "")
        action = payload.get("action", "")
        self._board.post(BoardPost(
            section=BoardSection.POST,
            author_type="system",
            author_id="system",
            content=f"Gate '{gate_id}' resolved: {action}",
            speech_act=SpeechAct.INFORM,
        ))

    def _handle_agent_spawned(self, event: Event) -> None:
        payload = event.payload
        agent_id = payload.get("agent_id", "")
        role = payload.get("role", "")
        self._board.update_agent_status(AgentStatus(
            agent_id=agent_id,
            agent_name=agent_id,
            role=role,
            state="pending",
        ))
        self._board.post(BoardPost(
            section=BoardSection.POST,
            author_type="system",
            author_id="system",
            content=f"New agent spawned: {agent_id}" + (f" (role: {role})" if role else ""),
            speech_act=SpeechAct.INFORM,
        ))

    def _handle_error(self, event: Event) -> None:
        payload = event.payload
        error = payload.get("error", payload.get("message", "Unknown error"))
        agent_id = payload.get("agent_id", "system")
        self._board.add_system_alert(
            f"Error [{agent_id}]: {error[:200]}",
            expires_minutes=60,
        )

    # Handler dispatch table
    _handlers: dict = {
        EventType.TASK_STATE_CHANGED: _handle_task_state_changed,
        EventType.BUDGET_CONSUMED: _handle_budget_consumed,
        EventType.BUDGET_EXCEEDED: _handle_budget_exceeded,
        EventType.GATE_WAITING: _handle_gate_waiting,
        EventType.GATE_RESOLVED: _handle_gate_resolved,
        EventType.AGENT_SPAWNED: _handle_agent_spawned,
        EventType.ERROR_OCCURRED: _handle_error,
    }
