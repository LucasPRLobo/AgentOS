"""Session orchestrator — manages multi-agent session lifecycle."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from agentos.core.errors import TaskExecutionError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.lm.agent_config import AgentConfig
from agentos.lm.agent_runner import AgentRunner
from agentos.lm.provider import BaseLMProvider
from agentos.runtime.dag import DAGExecutor, DAGWorkflow
from agentos.runtime.domain_registry import DomainRegistry
from agentos.runtime.event_log import EventLog, SQLiteEventLog
from agentos.runtime.role_template import RoleTemplate
from agentos.runtime.task import TaskNode
from agentos.runtime.workspace import Workspace, WorkspaceConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import BaseEvent, EventType, SessionFinished, SessionStarted
from agentos.schemas.session import AgentSlotConfig, SessionConfig
from agentos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SessionState(StrEnum):
    """Lifecycle states for a multi-agent session."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class _SessionRecord:
    """Internal bookkeeping for a session."""

    __slots__ = (
        "config",
        "state",
        "event_log",
        "run_id",
        "created_at",
        "thread",
        "stop_event",
        "error",
    )

    def __init__(self, config: SessionConfig, event_log: EventLog, run_id: RunId) -> None:
        self.config = config
        self.state = SessionState.CREATED
        self.event_log = event_log
        self.run_id = run_id
        self.created_at = datetime.now(UTC).isoformat()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.error: str | None = None


class SessionOrchestrator:
    """Manages multi-agent sessions backed by DAG execution.

    Each session is a DAG of agents. The orchestrator handles:
    - Session creation and validation
    - Building agent DAGs from workflow + role configs
    - Background execution in threads
    - Lifecycle management (start, stop, query)
    - Event log access for monitoring
    """

    def __init__(
        self,
        domain_registry: DomainRegistry,
        *,
        lm_provider_factory: LMProviderFactory | None = None,
    ) -> None:
        self._registry = domain_registry
        self._sessions: dict[str, _SessionRecord] = {}
        self._lock = threading.Lock()
        # Factory: model_name → BaseLMProvider instance
        self._lm_provider_factory = lm_provider_factory

    def create_session(self, config: SessionConfig) -> str:
        """Validate config and prepare a new session. Returns session_id."""
        # Validate domain pack exists
        if not self._registry.has_pack(config.domain_pack):
            raise ValueError(f"Unknown domain pack: '{config.domain_pack}'")

        pack = self._registry.get_pack(config.domain_pack)

        # Validate workflow exists
        workflow_names = {w.name for w in pack.workflows}
        if config.workflow not in workflow_names:
            raise ValueError(
                f"Unknown workflow '{config.workflow}' in pack '{config.domain_pack}'. "
                f"Available: {sorted(workflow_names)}"
            )

        # Validate agent roles exist
        role_names = {r.name for r in pack.role_templates}
        for slot in config.agents:
            if slot.role not in role_names:
                raise ValueError(
                    f"Unknown role '{slot.role}' in pack '{config.domain_pack}'. "
                    f"Available: {sorted(role_names)}"
                )

        # Create event log and workspace directory
        Path(config.workspace_root).mkdir(parents=True, exist_ok=True)
        event_log = SQLiteEventLog(
            str(Path(config.workspace_root) / "events.db")
        )
        run_id = generate_run_id()

        record = _SessionRecord(config, event_log, run_id)

        with self._lock:
            self._sessions[config.session_id] = record

        return config.session_id

    def start_session(
        self,
        session_id: str,
        *,
        lm_provider: BaseLMProvider | None = None,
    ) -> None:
        """Begin session execution in a background thread."""
        record = self._get_record(session_id)

        if record.state != SessionState.CREATED:
            raise RuntimeError(
                f"Session '{session_id}' is in state {record.state}, expected CREATED"
            )

        record.state = SessionState.RUNNING
        factory = self._lm_provider_factory

        def _run() -> None:
            try:
                self._execute_session(record, lm_provider, factory)
            except Exception as exc:
                logger.exception("Session %s failed: %s", session_id, exc)
                record.error = str(exc)
                record.state = SessionState.FAILED
                self._emit_session_finished(record, "FAILED")

        record.thread = threading.Thread(target=_run, daemon=True)
        record.thread.start()

    def stop_session(self, session_id: str) -> None:
        """Request graceful stop of a running session."""
        record = self._get_record(session_id)
        if record.state == SessionState.RUNNING:
            record.stop_event.set()
            record.state = SessionState.STOPPED
            self._emit_session_finished(record, "STOPPED")

    def get_session_state(self, session_id: str) -> SessionState:
        """Return the current state of a session."""
        return self._get_record(session_id).state

    def get_session_events(
        self, session_id: str, *, after_seq: int = 0
    ) -> list[BaseEvent]:
        """Return events for the session, optionally after a sequence number."""
        record = self._get_record(session_id)
        all_events = record.event_log.replay(record.run_id)
        if after_seq > 0:
            return [e for e in all_events if e.seq >= after_seq]
        return all_events

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return summary of all sessions."""
        with self._lock:
            results = []
            for sid, record in self._sessions.items():
                results.append({
                    "session_id": sid,
                    "state": record.state.value,
                    "domain_pack": record.config.domain_pack,
                    "workflow": record.config.workflow,
                    "created_at": record.created_at,
                    "agent_count": sum(s.count for s in record.config.agents),
                })
            return results

    def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Return detailed info for a session."""
        record = self._get_record(session_id)
        events = record.event_log.replay(record.run_id)
        return {
            "session_id": session_id,
            "state": record.state.value,
            "domain_pack": record.config.domain_pack,
            "workflow": record.config.workflow,
            "created_at": record.created_at,
            "agents": [s.model_dump() for s in record.config.agents],
            "event_count": len(events),
            "error": record.error,
        }

    # ── Private ──────────────────────────────────────────────────────

    def _get_record(self, session_id: str) -> _SessionRecord:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session '{session_id}' not found")
            return self._sessions[session_id]

    def _execute_session(
        self,
        record: _SessionRecord,
        lm_provider: BaseLMProvider | None,
        lm_provider_factory: LMProviderFactory | None = None,
    ) -> None:
        """Build and execute the agent DAG for a session."""
        config = record.config
        event_log = record.event_log
        run_id = record.run_id

        # Emit SessionStarted
        seq = 0
        event_log.append(
            SessionStarted(
                run_id=run_id,
                seq=seq,
                payload={
                    "session_id": config.session_id,
                    "domain_pack": config.domain_pack,
                    "workflow": config.workflow,
                    "agent_count": sum(s.count for s in config.agents),
                },
            )
        )

        pack = self._registry.get_pack(config.domain_pack)
        role_map = {r.name: r for r in pack.role_templates}
        workspace = Workspace(
            WorkspaceConfig(root=config.workspace_root, allowed_patterns=["**"])
        )

        # Build one TaskNode per agent slot
        tasks: list[TaskNode] = []
        prev_task: TaskNode | None = None

        for slot in config.agents:
            role = role_map[slot.role]
            # Resolve provider: factory(model) > explicit provider > error
            agent_provider = None
            if lm_provider_factory is not None:
                agent_provider = lm_provider_factory(slot.model)
            elif lm_provider is not None:
                agent_provider = lm_provider
            task = self._build_agent_task(
                slot=slot,
                role=role,
                pack=pack,
                event_log=event_log,
                workspace=workspace,
                lm_provider=agent_provider,
                stop_event=record.stop_event,
                depends_on=[prev_task] if prev_task is not None else [],
            )
            tasks.append(task)
            prev_task = task

        dag = DAGWorkflow(name=f"session-{config.session_id}", tasks=tasks)
        executor = DAGExecutor(event_log, max_parallel=config.max_parallel)

        # DAG gets its own run_id to avoid seq collisions with session events
        dag_run_id = generate_run_id()
        try:
            executor.run(dag, run_id=dag_run_id)
            record.state = SessionState.SUCCEEDED
            self._emit_session_finished(record, "SUCCEEDED")
        except TaskExecutionError as exc:
            record.error = str(exc)
            record.state = SessionState.FAILED
            self._emit_session_finished(record, "FAILED")

    # Standard JSON format instructions prepended to every agent's system prompt
    _ACTION_FORMAT = (
        "You are an AI agent with access to tools. "
        "You MUST respond with ONLY a single JSON object (no extra text).\n"
        "For tool calls:\n"
        '{"action": "tool_call", "tool": "<tool_name>", "input": {<tool_input>}, "reasoning": "why"}\n'
        "When you are finished:\n"
        '{"action": "finish", "result": "<your final output>", "reasoning": "why"}\n\n'
    )

    def _build_agent_task(
        self,
        *,
        slot: AgentSlotConfig,
        role: RoleTemplate,
        pack: Any,
        event_log: EventLog,
        workspace: Workspace,
        lm_provider: BaseLMProvider | None,
        stop_event: threading.Event,
        depends_on: list[TaskNode],
    ) -> TaskNode:
        """Create a TaskNode that runs an AgentRunner for the given role."""
        role_prompt = slot.system_prompt_override or role.system_prompt
        system_prompt = self._ACTION_FORMAT + role_prompt
        budget_spec = slot.budget_override or role.budget_profile

        def _run() -> tuple[RunId, str | None]:
            if stop_event.is_set():
                return generate_run_id(), None

            # Build tool registry for this agent
            registry = ToolRegistry()
            tool_map = {t.name: t for t in pack.tools}

            for tool_name in role.tool_names:
                if tool_name in tool_map:
                    entry = tool_map[tool_name]
                    try:
                        try:
                            tool = self._registry.load_tool(entry, workspace=workspace)
                        except TypeError:
                            # Tool doesn't need workspace arg
                            tool = self._registry.load_tool(entry)
                        registry.register(tool)
                    except (ImportError, ModuleNotFoundError) as exc:
                        logger.warning(
                            "Skipping tool '%s' for agent '%s': %s",
                            tool_name, slot.role, exc,
                        )

            rid = generate_run_id()
            bm = BudgetManager(budget_spec, event_log, rid)

            if lm_provider is None:
                raise RuntimeError(
                    f"No LM provider available for agent '{slot.role}'. "
                    "Pass lm_provider to start_session()."
                )

            runner = AgentRunner(
                event_log,
                lm_provider,
                registry,
                budget_manager=bm,
            )
            return runner.run(
                slot.system_prompt_override or role.description,
                run_id=rid,
                config=AgentConfig(
                    system_prompt=system_prompt,
                    max_steps=role.max_steps,
                    max_consecutive_errors=3,
                    include_tool_schemas=True,
                ),
            )

        return TaskNode(
            name=f"{role.display_name} ({slot.model})",
            callable=_run,
            depends_on=depends_on,
        )

    def _emit_session_finished(self, record: _SessionRecord, outcome: str) -> None:
        """Emit a SessionFinished event. Safe to call multiple times (idempotent)."""
        events = record.event_log.replay(record.run_id)
        # Check if SessionFinished already emitted
        for e in events:
            if e.event_type == EventType.SESSION_FINISHED:
                return
        next_seq = max((e.seq for e in events), default=-1) + 1
        try:
            record.event_log.append(
                SessionFinished(
                    run_id=record.run_id,
                    seq=next_seq,
                    payload={
                        "session_id": record.config.session_id,
                        "outcome": outcome,
                        "error": record.error,
                    },
                )
            )
        except Exception:
            # Ignore PK collisions from concurrent emit attempts
            pass


# Type alias for LM provider factory: model_name → BaseLMProvider
LMProviderFactory = Any  # Callable[[str], BaseLMProvider]
