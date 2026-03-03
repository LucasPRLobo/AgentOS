"""Budget manager — 5-dimension tracking with hard enforcement."""

from __future__ import annotations

from collections import defaultdict

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage
from agentos.schemas.events import Event, EventType


class BudgetExceededError(Exception):
    """Raised when a hard budget limit is exceeded."""

    def __init__(self, agent_id: str, resource: str, limit: float, attempted: float) -> None:
        self.agent_id = agent_id
        self.resource = resource
        self.limit = limit
        self.attempted = attempted
        super().__init__(
            f"Budget exceeded for {agent_id}: {resource} "
            f"(limit={limit}, attempted={attempted})"
        )


class BudgetManager:
    """Tracks resource usage and enforces hard limits.

    State is event-sourced: emits BUDGET_CONSUMED and BUDGET_EXCEEDED events.
    Uses shared SeqCounter for event ordering.
    """

    def __init__(
        self,
        workflow_spec: BudgetSpec,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        agent_specs: dict[str, BudgetSpec] | None = None,
    ) -> None:
        self._workflow_spec = workflow_spec
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._agent_specs: dict[str, BudgetSpec] = agent_specs or {}
        self._usage: dict[str, BudgetUsage] = defaultdict(BudgetUsage)

    def apply(self, agent_id: str, delta: BudgetDelta) -> None:
        """Apply usage delta, emit event, then check limits."""
        usage = self._usage[agent_id]
        usage.tokens_used += delta.tokens
        usage.api_calls_made += delta.api_calls
        usage.time_elapsed_seconds += delta.time_seconds
        usage.cost_usd += delta.cost_usd

        self._event_log.append(Event(
            event_type=EventType.BUDGET_CONSUMED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "delta": delta.model_dump(),
                "cumulative": usage.model_dump(),
            },
        ))

        self.check(agent_id)

    def check(self, agent_id: str) -> None:
        """Check agent-level and workflow-level limits.

        Raises BudgetExceededError and emits BUDGET_EXCEEDED event if any
        limit is breached.
        """
        usage = self._usage[agent_id]

        # Agent-level limits
        agent_spec = self._agent_specs.get(agent_id)
        if agent_spec is not None:
            self._check_spec(agent_id, agent_spec, usage)

        # Workflow-level limits
        total = self.total_usage
        self._check_spec(agent_id, self._workflow_spec, total)

    def _check_spec(self, agent_id: str, spec: BudgetSpec, usage: BudgetUsage) -> None:
        checks = [
            ("tokens", spec.max_tokens, usage.tokens_used),
            ("api_calls", spec.max_api_calls, usage.api_calls_made),
            ("time_seconds", spec.max_time_seconds, usage.time_elapsed_seconds),
            ("cost_usd", spec.max_cost_usd, usage.cost_usd),
        ]
        for resource, limit, current in checks:
            if limit is not None and current > limit:
                self._event_log.append(Event(
                    event_type=EventType.BUDGET_EXCEEDED,
                    workflow_id=self._workflow_id,
                    seq=self._seq.next(),
                    payload={
                        "agent_id": agent_id,
                        "resource": resource,
                        "limit": limit,
                        "attempted": current,
                    },
                ))
                raise BudgetExceededError(agent_id, resource, limit, current)

    def usage_for(self, agent_id: str) -> BudgetUsage:
        """Return accumulated usage for a specific agent."""
        return self._usage[agent_id]

    @property
    def total_usage(self) -> BudgetUsage:
        """Return workflow-level accumulated usage across all agents."""
        total = BudgetUsage()
        for usage in self._usage.values():
            total.tokens_used += usage.tokens_used
            total.api_calls_made += usage.api_calls_made
            total.time_elapsed_seconds += usage.time_elapsed_seconds
            total.cost_usd += usage.cost_usd
        return total
