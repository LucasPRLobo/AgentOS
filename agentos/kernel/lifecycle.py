"""Agent lifecycle manager — spawn, stop, restart with curated briefing."""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, Field

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType


# ---------------------------------------------------------------------------
# Lifecycle policy
# ---------------------------------------------------------------------------

class RestartReason(StrEnum):
    """Why an agent was restarted."""

    TOKEN_THRESHOLD = "token_threshold"
    TURN_COUNT = "turn_count"
    TIME_LIMIT = "time_limit"
    MANUAL = "manual"
    ERROR = "error"


class TerminationReason(StrEnum):
    """Why an agent was terminated."""

    COMPLETED = "completed"
    BUDGET = "budget"
    ERROR = "error"
    MANUAL = "manual"
    POLICY = "policy"  # Lifecycle policy triggered


class LifecyclePolicy(BaseModel):
    """Configurable lifecycle limits — triggers restart or termination."""

    max_tokens: int | None = Field(
        default=None,
        description="Restart agent after consuming this many tokens",
    )
    max_turns: int | None = Field(
        default=None,
        description="Restart agent after this many turns/tool calls",
    )
    max_time_seconds: float | None = Field(
        default=None,
        description="Restart agent after this much wall-clock time",
    )
    max_restarts: int = Field(
        default=3,
        description="Maximum number of restarts before hard failure",
    )
    briefing_max_tokens: int = Field(
        default=2000,
        description="Max tokens for curated briefing on restart",
    )


# ---------------------------------------------------------------------------
# Agent state tracking
# ---------------------------------------------------------------------------

class AgentState(StrEnum):
    """Current lifecycle state of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class AgentRecord(BaseModel):
    """Runtime tracking for a single agent instance."""

    agent_id: str
    agent_name: str = ""
    adapter_tier: int = 1
    state: AgentState = AgentState.IDLE
    tokens_consumed: int = 0
    turns_completed: int = 0
    restart_count: int = 0
    start_time: float | None = None  # time.monotonic() epoch
    cumulative_findings: list[str] = Field(default_factory=list)
    last_summary: str = ""
    error_history: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Curated briefing
# ---------------------------------------------------------------------------

class CuratedBriefing(BaseModel):
    """Briefing document passed to a restarted agent."""

    agent_id: str
    restart_number: int
    reason: RestartReason
    prior_summary: str = Field(
        default="", description="Summary of work completed before restart"
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Important findings to carry forward",
    )
    instructions: str = Field(
        default="",
        description="What the agent should focus on next",
    )


# ---------------------------------------------------------------------------
# Lifecycle manager
# ---------------------------------------------------------------------------

class LifecycleError(Exception):
    """Raised when a lifecycle operation fails."""


class AgentLifecycleManager:
    """Manages agent spawn, stop, and restart with event emission.

    Tracks per-agent state (tokens, turns, time), enforces lifecycle
    policies, generates curated briefings for restarts, and emits
    AGENT_SPAWNED / AGENT_TERMINATED events.
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        default_policy: LifecyclePolicy | None = None,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._default_policy = default_policy or LifecyclePolicy()
        self._agents: dict[str, AgentRecord] = {}
        self._policies: dict[str, LifecyclePolicy] = {}

    # -- Public API ----------------------------------------------------------

    def spawn(
        self,
        agent_id: str,
        agent_name: str = "",
        adapter_tier: int = 1,
        policy: LifecyclePolicy | None = None,
    ) -> AgentRecord:
        """Spawn a new agent. Emits AGENT_SPAWNED event.

        Raises LifecycleError if the agent is already running.
        """
        existing = self._agents.get(agent_id)
        if existing and existing.state == AgentState.RUNNING:
            raise LifecycleError(
                f"Agent '{agent_id}' is already running. "
                f"Stop it before spawning again."
            )

        record = AgentRecord(
            agent_id=agent_id,
            agent_name=agent_name or agent_id,
            adapter_tier=adapter_tier,
            state=AgentState.RUNNING,
            start_time=time.monotonic(),
        )
        self._agents[agent_id] = record

        if policy is not None:
            self._policies[agent_id] = policy

        self._event_log.append(Event(
            event_type=EventType.AGENT_SPAWNED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "agent_name": record.agent_name,
                "adapter_tier": adapter_tier,
                "restart_count": record.restart_count,
            },
        ))

        return record

    def stop(
        self,
        agent_id: str,
        reason: TerminationReason = TerminationReason.COMPLETED,
        metrics: dict | None = None,
    ) -> AgentRecord:
        """Stop an agent. Emits AGENT_TERMINATED event.

        Raises LifecycleError if agent doesn't exist or isn't running.
        """
        record = self._get_running(agent_id)
        record.state = AgentState.STOPPED

        self._event_log.append(Event(
            event_type=EventType.AGENT_TERMINATED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "reason": str(reason),
                "metrics": metrics or {
                    "tokens": record.tokens_consumed,
                    "turns": record.turns_completed,
                },
            },
        ))

        return record

    def restart(
        self,
        agent_id: str,
        reason: RestartReason = RestartReason.MANUAL,
        instructions: str = "",
    ) -> tuple[AgentRecord, CuratedBriefing]:
        """Restart an agent with a curated briefing.

        Stops the current instance, generates a briefing from accumulated
        state, then spawns a fresh instance. Returns the new record and
        the briefing.

        Raises LifecycleError if max_restarts is exceeded.
        """
        record = self._get_running(agent_id)
        policy = self._policy_for(agent_id)

        if record.restart_count >= policy.max_restarts:
            # Hard fail — too many restarts
            record.state = AgentState.FAILED
            self._event_log.append(Event(
                event_type=EventType.AGENT_TERMINATED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "agent_id": agent_id,
                    "reason": "max_restarts_exceeded",
                    "restart_count": record.restart_count,
                    "max_restarts": policy.max_restarts,
                },
            ))
            raise LifecycleError(
                f"Agent '{agent_id}' exceeded max restarts "
                f"({policy.max_restarts}). Terminating."
            )

        # Generate briefing before stopping
        briefing = self._build_briefing(record, reason, instructions)

        # Stop the old instance
        self.stop(agent_id, reason=TerminationReason.POLICY)

        # Spawn fresh instance, preserving restart count and findings
        new_record = self.spawn(
            agent_id=agent_id,
            agent_name=record.agent_name,
            adapter_tier=record.adapter_tier,
        )
        new_record.restart_count = record.restart_count + 1
        new_record.cumulative_findings = record.cumulative_findings.copy()

        return new_record, briefing

    def record_turn(
        self,
        agent_id: str,
        tokens: int = 0,
        summary: str = "",
        findings: list[str] | None = None,
    ) -> RestartReason | None:
        """Record a completed turn. Returns restart reason if policy triggered."""
        record = self._get_running(agent_id)
        record.tokens_consumed += tokens
        record.turns_completed += 1

        if summary:
            record.last_summary = summary
        if findings:
            record.cumulative_findings.extend(findings)

        return self._check_policy(agent_id)

    def record_error(self, agent_id: str, error_msg: str) -> None:
        """Record an error that occurred during agent execution."""
        record = self._agents.get(agent_id)
        if record is None:
            return
        record.error_history.append(error_msg)

    def get_record(self, agent_id: str) -> AgentRecord | None:
        """Get the current record for an agent, or None."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentRecord]:
        """Return all tracked agent records."""
        return list(self._agents.values())

    def running_agents(self) -> list[AgentRecord]:
        """Return currently running agents."""
        return [r for r in self._agents.values() if r.state == AgentState.RUNNING]

    # -- Internal ------------------------------------------------------------

    def _get_running(self, agent_id: str) -> AgentRecord:
        """Get a running agent record, or raise."""
        record = self._agents.get(agent_id)
        if record is None:
            raise LifecycleError(f"Agent '{agent_id}' not found.")
        if record.state != AgentState.RUNNING:
            raise LifecycleError(
                f"Agent '{agent_id}' is not running (state={record.state})."
            )
        return record

    def _policy_for(self, agent_id: str) -> LifecyclePolicy:
        """Return the policy for an agent, falling back to default."""
        return self._policies.get(agent_id, self._default_policy)

    def _check_policy(self, agent_id: str) -> RestartReason | None:
        """Check if any lifecycle policy threshold is crossed.

        Returns the restart reason if a threshold is exceeded, None otherwise.
        """
        record = self._agents[agent_id]
        policy = self._policy_for(agent_id)

        if policy.max_tokens is not None and record.tokens_consumed >= policy.max_tokens:
            return RestartReason.TOKEN_THRESHOLD

        if policy.max_turns is not None and record.turns_completed >= policy.max_turns:
            return RestartReason.TURN_COUNT

        if policy.max_time_seconds is not None and record.start_time is not None:
            elapsed = time.monotonic() - record.start_time
            if elapsed >= policy.max_time_seconds:
                return RestartReason.TIME_LIMIT

        return None

    def _build_briefing(
        self,
        record: AgentRecord,
        reason: RestartReason,
        instructions: str,
    ) -> CuratedBriefing:
        """Build a curated briefing for an agent restart.

        Includes prior summary, key findings (capped to policy limit),
        and caller-specified instructions.
        """
        policy = self._policy_for(record.agent_id)

        # Trim findings to fit within briefing token budget.
        # Rough estimate: 1 finding ~ 20 tokens. Reserve 200 for metadata.
        max_findings = max(1, (policy.briefing_max_tokens - 200) // 20)
        # Keep the most recent findings (likely most relevant)
        trimmed_findings = record.cumulative_findings[-max_findings:]

        return CuratedBriefing(
            agent_id=record.agent_id,
            restart_number=record.restart_count + 1,
            reason=reason,
            prior_summary=record.last_summary,
            key_findings=trimmed_findings,
            instructions=instructions,
        )
