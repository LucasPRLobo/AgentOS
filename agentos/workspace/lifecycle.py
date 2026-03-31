"""Agent lifecycle manager — dormant/active/suspended state tracking.

Manages agent states within a workspace, enforces the 35-minute rule,
and tracks activation durations.
"""

from __future__ import annotations

import logging
import threading
import time

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType

logger = logging.getLogger(__name__)

# Performance degradation threshold (seconds).
_35_MIN_SECONDS = 35 * 60


class AgentState:
    DORMANT = "dormant"
    ACTIVATING = "activating"
    ACTIVE = "active"
    COMPLETING = "completing"
    SUSPENDED = "suspended"


class AgentLifecycleManager:
    """Manages agent states within a workspace."""

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._states: dict[str, str] = {}  # agent_id → state
        self._activation_start: dict[str, float] = {}  # agent_id → monotonic time
        self._task_map: dict[str, str] = {}  # agent_id → task_id
        self._warned_35: set[str] = set()  # agents already warned
        self._lock = threading.Lock()

    def activate(self, agent_id: str, task_id: str) -> None:
        """Transition agent to ACTIVE state."""
        with self._lock:
            self._states[agent_id] = AgentState.ACTIVE
            self._activation_start[agent_id] = time.monotonic()
            self._task_map[agent_id] = task_id
            self._warned_35.discard(agent_id)

        self._emit("agent.lifecycle_changed", {
            "agent_id": agent_id, "new_state": AgentState.ACTIVE,
            "task_id": task_id,
        })

    def deactivate(self, agent_id: str) -> None:
        """Transition agent to DORMANT state."""
        with self._lock:
            self._states[agent_id] = AgentState.DORMANT
            self._activation_start.pop(agent_id, None)
            self._task_map.pop(agent_id, None)

        self._emit("agent.lifecycle_changed", {
            "agent_id": agent_id, "new_state": AgentState.DORMANT,
        })

    def suspend(self, agent_id: str, reason: str = "") -> None:
        """Transition agent to SUSPENDED state."""
        with self._lock:
            self._states[agent_id] = AgentState.SUSPENDED

        self._emit("agent.lifecycle_changed", {
            "agent_id": agent_id, "new_state": AgentState.SUSPENDED,
            "reason": reason,
        })

    def resume_agent(self, agent_id: str) -> None:
        """Transition from SUSPENDED back to ACTIVE."""
        with self._lock:
            if self._states.get(agent_id) != AgentState.SUSPENDED:
                return
            self._states[agent_id] = AgentState.ACTIVE
            self._activation_start[agent_id] = time.monotonic()

        self._emit("agent.lifecycle_changed", {
            "agent_id": agent_id, "new_state": AgentState.ACTIVE,
        })

    def get_state(self, agent_id: str) -> str:
        with self._lock:
            return self._states.get(agent_id, AgentState.DORMANT)

    def get_active_agents(self) -> list[str]:
        with self._lock:
            return [aid for aid, s in self._states.items() if s == AgentState.ACTIVE]

    def get_dormant_agents(self) -> list[str]:
        with self._lock:
            return [aid for aid, s in self._states.items() if s == AgentState.DORMANT]

    def get_activation_duration(self, agent_id: str) -> float:
        """Seconds since activation. Returns 0 if not active."""
        with self._lock:
            start = self._activation_start.get(agent_id)
            if start is None:
                return 0.0
            return time.monotonic() - start

    def check_duration(self, agent_id: str) -> bool:
        """Check if agent exceeds 35-minute threshold. Returns True if exceeded."""
        duration = self.get_activation_duration(agent_id)
        if duration > _35_MIN_SECONDS:
            with self._lock:
                if agent_id not in self._warned_35:
                    self._warned_35.add(agent_id)
                    self._emit("agent.duration_warning", {
                        "agent_id": agent_id,
                        "duration_seconds": round(duration, 1),
                        "threshold_seconds": _35_MIN_SECONDS,
                    })
            return True
        return False

    def check_all_durations(self) -> list[str]:
        """Check all active agents for 35-minute threshold. Returns warned agent IDs."""
        warned = []
        with self._lock:
            active = [aid for aid, s in self._states.items() if s == AgentState.ACTIVE]
        for aid in active:
            if self.check_duration(aid):
                warned.append(aid)
        return warned

    def _emit(self, event_type_str: str, payload: dict) -> None:
        # Use a generic event type since lifecycle events aren't in the enum
        self._event_log.append(Event(
            event_type=EventType.AGENT_SPAWNED if "ACTIVE" in payload.get("new_state", "") else EventType.AGENT_TERMINATED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload=payload,
        ))
