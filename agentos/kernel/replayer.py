"""WorkflowReplayer — deterministic read-only state reconstruction from events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agentos.kernel.event_log import EventLog
from agentos.schemas.budget import BudgetUsage
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskOutput, TaskStatus


# ---------------------------------------------------------------------------
# Snapshot dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TaskSnapshot:
    """Reconstructed state of a single task."""

    name: str
    state: TaskStatus = TaskStatus.PENDING
    agent_id: str = ""
    transitions: list[tuple[str, str, datetime]] = field(default_factory=list)
    output: TaskOutput | None = None


@dataclass
class AgentSnapshot:
    """Reconstructed state of a single agent."""

    agent_id: str
    agent_name: str = ""
    adapter_tier: int = 1
    spawned_at: datetime | None = None
    terminated_at: datetime | None = None
    termination_reason: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class GateSnapshot:
    """Reconstructed state of a gate."""

    gate_id: str
    task_id: str = ""
    gate_type: str = ""
    resolution: str = ""  # "approved" | "rejected" | "edited" | ""
    resolved_by: str = ""


@dataclass
class BudgetSnapshot:
    """Reconstructed budget usage per agent."""

    agent_id: str
    usage: BudgetUsage = field(default_factory=BudgetUsage)
    exceeded: bool = False
    exceeded_resource: str = ""


@dataclass
class WorkflowSnapshot:
    """Complete reconstructed state of a workflow execution."""

    workflow_id: str
    workflow_name: str = ""
    status: str = ""  # "succeeded" | "failed" | "paused" | "running"
    task_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None

    tasks: dict[str, TaskSnapshot] = field(default_factory=dict)
    agents: dict[str, AgentSnapshot] = field(default_factory=dict)
    gates: dict[str, GateSnapshot] = field(default_factory=dict)
    budgets: dict[str, BudgetSnapshot] = field(default_factory=dict)

    events: list[Event] = field(default_factory=list)
    event_count: int = 0

    errors: list[dict] = field(default_factory=list)

    @property
    def succeeded_tasks(self) -> list[str]:
        return [n for n, t in self.tasks.items() if t.state == TaskStatus.SUCCEEDED]

    @property
    def failed_tasks(self) -> list[str]:
        return [n for n, t in self.tasks.items() if t.state == TaskStatus.FAILED]

    @property
    def waiting_tasks(self) -> list[str]:
        return [n for n, t in self.tasks.items() if t.state == TaskStatus.WAITING]

    @property
    def running_tasks(self) -> list[str]:
        return [n for n, t in self.tasks.items() if t.state == TaskStatus.RUNNING]

    @property
    def pending_tasks(self) -> list[str]:
        return [n for n, t in self.tasks.items() if t.state == TaskStatus.PENDING]

    @property
    def total_cost(self) -> float:
        return sum(b.usage.cost_usd for b in self.budgets.values())

    @property
    def total_tokens(self) -> int:
        return sum(b.usage.tokens_used for b in self.budgets.values())


# ---------------------------------------------------------------------------
# Replayer
# ---------------------------------------------------------------------------

class WorkflowReplayer:
    """Reconstructs full workflow state from the event log.

    Pure read-only — never emits events. Processes each event type
    to build a WorkflowSnapshot containing task states, agent records,
    gate resolutions, budget usage, and the full event timeline.
    """

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def replay(self, workflow_id: str) -> WorkflowSnapshot:
        """Replay all events for a workflow and return a snapshot."""
        events = self._event_log.replay(workflow_id)
        snapshot = WorkflowSnapshot(
            workflow_id=workflow_id,
            events=events,
            event_count=len(events),
        )

        for event in events:
            self._process_event(event, snapshot)

        # If no completion event, infer status
        if not snapshot.status:
            if snapshot.waiting_tasks:
                snapshot.status = "paused"
            elif snapshot.running_tasks:
                snapshot.status = "running"
            elif snapshot.failed_tasks:
                snapshot.status = "failed"
            elif snapshot.succeeded_tasks:
                snapshot.status = "succeeded"

        return snapshot

    def _process_event(self, event: Event, snap: WorkflowSnapshot) -> None:
        """Dispatch event to the appropriate handler."""
        handlers = {
            EventType.WORKFLOW_STARTED: self._on_workflow_started,
            EventType.WORKFLOW_COMPLETED: self._on_workflow_completed,
            EventType.TASK_STATE_CHANGED: self._on_task_state_changed,
            EventType.TASK_OUTPUT_PRODUCED: self._on_task_output_produced,
            EventType.AGENT_SPAWNED: self._on_agent_spawned,
            EventType.AGENT_TERMINATED: self._on_agent_terminated,
            EventType.GATE_WAITING: self._on_gate_waiting,
            EventType.GATE_RESOLVED: self._on_gate_resolved,
            EventType.BUDGET_CONSUMED: self._on_budget_consumed,
            EventType.BUDGET_EXCEEDED: self._on_budget_exceeded,
            EventType.CAPABILITY_GRANTED: self._on_noop,
            EventType.CAPABILITY_DENIED: self._on_noop,
            EventType.FILE_CREATED: self._on_noop,
            EventType.FILE_MODIFIED: self._on_noop,
            EventType.ERROR_OCCURRED: self._on_error,
        }
        handler = handlers.get(event.event_type, self._on_noop)
        handler(event, snap)

    # -- Handlers ------------------------------------------------------------

    @staticmethod
    def _on_workflow_started(event: Event, snap: WorkflowSnapshot) -> None:
        snap.workflow_name = event.payload.get("workflow_name", "")
        snap.task_count = event.payload.get("task_count", 0)
        snap.started_at = event.timestamp

    @staticmethod
    def _on_workflow_completed(event: Event, snap: WorkflowSnapshot) -> None:
        snap.status = event.payload.get("status", "")
        snap.completed_at = event.timestamp

    @staticmethod
    def _on_task_state_changed(event: Event, snap: WorkflowSnapshot) -> None:
        task_name = event.payload.get("task_id", "")
        to_state = event.payload.get("to_state", "")
        from_state = event.payload.get("from_state", "")
        agent_id = event.payload.get("agent_id", "")

        if task_name not in snap.tasks:
            snap.tasks[task_name] = TaskSnapshot(name=task_name)

        task = snap.tasks[task_name]
        if to_state:
            task.state = TaskStatus(to_state)
        if agent_id:
            task.agent_id = agent_id
        task.transitions.append((from_state, to_state, event.timestamp))

    @staticmethod
    def _on_task_output_produced(event: Event, snap: WorkflowSnapshot) -> None:
        task_id = event.payload.get("task_id", "")
        output_data = event.payload.get("output")

        if task_id not in snap.tasks:
            snap.tasks[task_id] = TaskSnapshot(name=task_id)

        if output_data:
            snap.tasks[task_id].output = TaskOutput.model_validate(output_data)

    @staticmethod
    def _on_agent_spawned(event: Event, snap: WorkflowSnapshot) -> None:
        agent_id = event.payload.get("agent_id", "")
        snap.agents[agent_id] = AgentSnapshot(
            agent_id=agent_id,
            agent_name=event.payload.get("agent_name", ""),
            adapter_tier=event.payload.get("adapter_tier", 1),
            spawned_at=event.timestamp,
        )

    @staticmethod
    def _on_agent_terminated(event: Event, snap: WorkflowSnapshot) -> None:
        agent_id = event.payload.get("agent_id", "")
        if agent_id in snap.agents:
            agent = snap.agents[agent_id]
            agent.terminated_at = event.timestamp
            agent.termination_reason = event.payload.get("reason", "")
            agent.metrics = event.payload.get("metrics", {})

    @staticmethod
    def _on_gate_waiting(event: Event, snap: WorkflowSnapshot) -> None:
        gate_id = event.payload.get("gate_id", "")
        snap.gates[gate_id] = GateSnapshot(
            gate_id=gate_id,
            task_id=event.payload.get("task_id", ""),
            gate_type=event.payload.get("gate_type", ""),
        )

    @staticmethod
    def _on_gate_resolved(event: Event, snap: WorkflowSnapshot) -> None:
        gate_id = event.payload.get("gate_id", "")
        if gate_id in snap.gates:
            gate = snap.gates[gate_id]
            gate.resolution = event.payload.get("resolution", "")
            gate.resolved_by = event.payload.get("reviewer", "")

    @staticmethod
    def _on_budget_consumed(event: Event, snap: WorkflowSnapshot) -> None:
        agent_id = event.payload.get("agent_id", "")
        cumulative = event.payload.get("cumulative", {})

        if agent_id not in snap.budgets:
            snap.budgets[agent_id] = BudgetSnapshot(agent_id=agent_id)

        budget = snap.budgets[agent_id]
        budget.usage = BudgetUsage(
            tokens_used=cumulative.get("tokens_used", 0),
            api_calls_made=cumulative.get("api_calls_made", 0),
            time_elapsed_seconds=cumulative.get("time_elapsed_seconds", 0.0),
            cost_usd=cumulative.get("cost_usd", 0.0),
        )

    @staticmethod
    def _on_budget_exceeded(event: Event, snap: WorkflowSnapshot) -> None:
        agent_id = event.payload.get("agent_id", "")
        if agent_id not in snap.budgets:
            snap.budgets[agent_id] = BudgetSnapshot(agent_id=agent_id)
        budget = snap.budgets[agent_id]
        budget.exceeded = True
        budget.exceeded_resource = event.payload.get("resource", "")

    @staticmethod
    def _on_error(event: Event, snap: WorkflowSnapshot) -> None:
        snap.errors.append(event.payload)

    @staticmethod
    def _on_noop(event: Event, snap: WorkflowSnapshot) -> None:
        pass
