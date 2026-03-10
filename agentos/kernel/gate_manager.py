"""Gate manager — approval and input gate lifecycle via event log."""

from __future__ import annotations

import uuid

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.gate import GateResolution, GateState, GateType


class GateError(Exception):
    """Raised for gate constraint violations."""


class GateManager:
    """Manages gate lifecycle through the event log.

    Gates pause workflow execution at defined points, requiring human
    approval or input before downstream tasks can proceed.

    All state is event-sourced: create_gate emits GATE_WAITING,
    resolve_gate emits GATE_RESOLVED. Current state is derived by
    replaying these events.
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

    def create_gate(
        self,
        task_id: str,
        gate_type: GateType,
        prompt: str = "",
    ) -> str:
        """Create a new pending gate and emit GATE_WAITING.

        Returns the generated gate_id.
        """
        gate_id = f"gate-{uuid.uuid4().hex[:8]}"

        self._event_log.append(Event(
            event_type=EventType.GATE_WAITING,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "gate_id": gate_id,
                "task_id": task_id,
                "gate_type": str(gate_type),
                "prompt": prompt,
            },
        ))

        return gate_id

    def resolve_gate(
        self,
        gate_id: str,
        resolution: GateResolution,
        reviewer: str = "system",
        feedback: str | None = None,
    ) -> GateState:
        """Resolve a pending gate and emit GATE_RESOLVED.

        Raises GateError if the gate doesn't exist or is already resolved.
        Returns the updated GateState.
        """
        gate = self.get_gate(gate_id)
        if gate is None:
            raise GateError(f"Gate not found: {gate_id!r}")
        if not gate.pending:
            raise GateError(f"Gate already resolved: {gate_id!r}")

        self._event_log.append(Event(
            event_type=EventType.GATE_RESOLVED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "gate_id": gate_id,
                "task_id": gate.task_id,
                "resolution": str(resolution),
                "reviewer": reviewer,
                "feedback": feedback,
            },
        ))

        return GateState(
            gate_id=gate_id,
            task_id=gate.task_id,
            gate_type=gate.gate_type,
            prompt=gate.prompt,
            pending=False,
            resolution=resolution,
            feedback=feedback,
            reviewer=reviewer,
        )

    def get_gate(self, gate_id: str) -> GateState | None:
        """Derive the current state of a gate from events.

        Returns None if the gate_id is not found.
        """
        waiting_events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.GATE_WAITING,
        )

        # Find the creation event
        created = None
        for event in waiting_events:
            if event.payload.get("gate_id") == gate_id:
                created = event
                break

        if created is None:
            return None

        state = GateState(
            gate_id=gate_id,
            task_id=created.payload["task_id"],
            gate_type=GateType(created.payload["gate_type"]),
            prompt=created.payload.get("prompt", ""),
            pending=True,
        )

        # Check for resolution
        resolved_events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.GATE_RESOLVED,
        )
        for event in resolved_events:
            if event.payload.get("gate_id") == gate_id:
                state.pending = False
                state.resolution = GateResolution(event.payload["resolution"])
                state.reviewer = event.payload.get("reviewer")
                state.feedback = event.payload.get("feedback")
                break

        return state

    def list_pending(self) -> list[GateState]:
        """Return all pending (unresolved) gates for this workflow."""
        waiting_events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.GATE_WAITING,
        )

        resolved_ids: set[str] = set()
        resolved_events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.GATE_RESOLVED,
        )
        for event in resolved_events:
            gid = event.payload.get("gate_id")
            if gid:
                resolved_ids.add(gid)

        pending: list[GateState] = []
        for event in waiting_events:
            gate_id = event.payload.get("gate_id", "")
            if gate_id not in resolved_ids:
                pending.append(GateState(
                    gate_id=gate_id,
                    task_id=event.payload["task_id"],
                    gate_type=GateType(event.payload["gate_type"]),
                    prompt=event.payload.get("prompt", ""),
                    pending=True,
                ))

        return pending

    def list_all(self) -> list[GateState]:
        """Return all gates (pending and resolved) for this workflow."""
        waiting_events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.GATE_WAITING,
        )

        gates: list[GateState] = []
        for event in waiting_events:
            gate_id = event.payload.get("gate_id", "")
            gate = self.get_gate(gate_id)
            if gate is not None:
                gates.append(gate)

        return gates
