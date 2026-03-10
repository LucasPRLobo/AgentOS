"""Event-sourced task state machine."""

from __future__ import annotations

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskStatus

VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.SKIPPED},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.WAITING},
    TaskStatus.WAITING: {TaskStatus.RUNNING},
    TaskStatus.SUCCEEDED: {TaskStatus.PENDING},  # allows retry (revision loops)
    TaskStatus.FAILED: {TaskStatus.PENDING},      # allows retry (revision loops)
    TaskStatus.SKIPPED: set(),                     # terminal
}


class TaskStateMachine:
    """Manages task state transitions via the event log.

    All state is derived from TASK_STATE_CHANGED events — nothing is
    stored in memory beyond the references to the event log, sequence
    counter, and workflow ID.
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

    def transition(
        self,
        task_id: str,
        from_state: TaskStatus,
        to_state: TaskStatus,
        agent_id: str | None = None,
    ) -> None:
        """Record a task state transition.

        Raises ValueError if the transition is not allowed.
        """
        allowed = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed:
            raise ValueError(
                f"Invalid transition: {from_state} -> {to_state}"
            )

        event = Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": task_id,
                "from_state": str(from_state),
                "to_state": str(to_state),
                "agent_id": agent_id,
            },
        )
        self._event_log.append(event)

    def get_state(self, task_id: str) -> TaskStatus:
        """Derive the current state of a task from its events."""
        events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.TASK_STATE_CHANGED,
        )
        last_state: TaskStatus = TaskStatus.PENDING
        for event in events:
            if event.payload.get("task_id") == task_id:
                last_state = TaskStatus(event.payload["to_state"])
        return last_state
