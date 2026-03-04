# AgentOS — V2/V3 Development Plan

**Companion to:** PROJECT_OVERVIEW.md | V1_SCOPE.md | GTM_STRATEGY.md | DEVELOPMENT_PLAN.md
**Date:** March 2026
**Status:** Planning — V1.5 Complete (764 tests, 17 sprints, 10 example workflows)

---

## Purpose

The V1 Development Plan covered Sprints 1–17 (foundation through V1.5). This document continues from Sprint 18 through Sprint 39, covering all features deferred in V1_SCOPE.md, all "Future Discussion" items from PROJECT_OVERVIEW.md, and all commercial products from GTM_STRATEGY.md.

Sprint numbering continues without gaps. Each sprint is 2 weeks. The format matches the V1 plan: files to create/modify, Pydantic schemas with code, test specification tables, running test counts, and phase exit criteria.

---

## Architecture Decisions for V2+

These decisions apply across all phases in this document.

### 1. Backward Compatibility

All schema changes use optional fields with V1.5-compatible defaults. Existing workflows run without modification. The event `schema_version` bumps to `"0.2"` for new event types; the event envelope itself does not change.

### 2. Channels

Message channels are broker-mediated through a `ChannelRouter` — not peer-to-peer between agents. All messages are logged as `MESSAGE_SENT` / `MESSAGE_RECEIVED` events (stubs already exist in `EventType`). Channels are declared in workflow YAML and scoped to a single workflow execution.

### 3. Sandbox Levels

Three incremental tiers: `none` (V1 default — process-level only), `namespace` (Linux namespace isolation — PID, mount, network), `container` (Docker-based full isolation). Each level is opt-in per agent via `CapabilityPolicy.sandbox`.

### 4. Cross-Run Memory

Stored in a separate SQLite table (`memory_store`), not inside the event log. This avoids polluting the append-only event stream with mutable knowledge that decays over time. The event log records `memory.extracted` and `memory.injected` events for auditability.

### 5. Mutable DAG (V3)

`MutableDAG` wraps the tasks dict with `threading.Lock`. Runtime insertions emit `TASK_ADDED` and `TASK_WIRED` events. The replayer reconstructs dynamic tasks from these events. Static verification runs on the initial DAG; dynamic additions are validated at insertion time.

### 6. Authentication

JWT for dashboard sessions, API keys for programmatic access. Both are optional — local-first remains the default. Auth is layered on top of existing routes, not entangled with core logic.

### 7. Knowledge Graph

SQLite-backed with `entities` and `relationships` tables — no external dependencies (Neo4j, etc.). Provenance tracking links every fact to the workflow run and agent that produced it.

---

## Updated Repository Structure (V2+ additions)

```
agentos/
├── kernel/
│   ├── ...                          # (existing V1/V1.5 modules)
│   ├── channel_router.py            # Sprint 18: Message channel broker
│   ├── memory_store.py              # Sprint 24: Cross-run memory
│   └── mutable_dag.py               # Sprint 32: Runtime DAG mutation
├── adapters/
│   ├── ...                          # (existing)
│   └── manager_agent.py             # Sprint 29: LLM-powered message router
├── security/
│   ├── ...                          # (existing)
│   ├── sandbox.py                   # Sprint 19: Sandbox manager
│   ├── safety_score.py              # Sprint 20: Agent safety scoring
│   └── post_hoc_verifier.py         # Sprint 21: Tier 2/3 runtime verification
├── dashboard/
│   ├── ...                          # (existing)
│   ├── auth.py                      # Sprint 23: JWT + API key middleware
│   └── builder.py                   # Sprint 25: Workflow builder REST API
├── intelligence/
│   ├── __init__.py
│   ├── benchmark.py                 # Sprint 28: Benchmarking engine
│   ├── knowledge_graph.py           # Sprint 34: Knowledge graph store
│   ├── learning.py                  # Sprint 35: Workflow-level learning
│   ├── finetune.py                  # Sprint 37: Fine-tuning data pipeline
│   └── specialization.py            # Sprint 38: Cross-workflow specialization
├── marketplace/
│   ├── __init__.py
│   └── registry.py                  # Sprint 30: Template registry
├── schemas/
│   ├── ...                          # (existing)
│   ├── channel.py                   # Sprint 18: Channel schemas
│   ├── sandbox.py                   # Sprint 19: Sandbox schemas
│   ├── auth.py                      # Sprint 23: Auth schemas
│   ├── benchmark.py                 # Sprint 28: Benchmark schemas
│   ├── marketplace.py               # Sprint 30: Marketplace schemas
│   └── spawn.py                     # Sprint 33: Dynamic spawn schemas
└── ...
```

---

## New Event Types (V2+)

Added to `EventType` enum across sprints. All use the existing `Event` envelope with `schema_version: "0.2"`.

| Event Type | Sprint | Purpose |
|---|---|---|
| `channel.created` | 18 | Channel declared and ready |
| `channel.closed` | 18 | Channel closed at workflow end |
| `sandbox.created` | 19 | Sandbox provisioned for agent |
| `sandbox.destroyed` | 19 | Sandbox torn down |
| `sandbox.violation` | 19 | Agent attempted to escape sandbox |
| `safety.score_calculated` | 20 | Safety score computed for workflow |
| `policy.violation_detected` | 21 | Post-hoc policy violation found |
| `policy.reloaded` | 21 | Capability policy hot-reloaded |
| `auth.login` | 23 | User authenticated |
| `auth.logout` | 23 | User session ended |
| `memory.extracted` | 24 | Findings extracted to memory store |
| `memory.injected` | 24 | Prior knowledge injected into agent context |
| `benchmark.started` | 28 | Benchmark run initiated |
| `benchmark.completed` | 28 | Benchmark run finished with results |
| `task.added` | 32 | Task dynamically inserted into running DAG |
| `task.wired` | 32 | Dynamic task wired to existing dependencies |
| `agent.spawn_requested` | 33 | Agent requested new team member |
| `agent.spawn_approved` | 33 | Spawn request approved at gate |
| `knowledge.entity_added` | 34 | Entity added to knowledge graph |
| `knowledge.relationship_added` | 34 | Relationship added to knowledge graph |

---

## Phase 4: Communication & Security (Sprints 18–22)

**Exit criterion:** Channels work E2E, sandbox isolates misbehaving agent, safety score visible in dashboard, Tier 2 post-hoc enforcement catches policy violations.

### Sprint 18: Message Channels (Weeks 35–36)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/channel_router.py` | `ChannelRouter` — broker-mediated pub/sub within a workflow |
| `agentos/schemas/channel.py` | `ChannelConfig`, `ChannelMessage` |
| `tests/unit/test_channel_router.py` | Channel unit tests |
| `tests/integration/test_channel_workflow.py` | Channel-aware workflow integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/schemas/task.py` | Add `publishes_to: list[str]` and `subscribes_to: list[str]` to `TaskConfig` |
| `agentos/schemas/workflow.py` | Add `channels: dict[str, ChannelConfig]` to `WorkflowDefinition` |
| `agentos/schemas/events.py` | Implement `MESSAGE_SENT` / `MESSAGE_RECEIVED` payload specs; add `channel.created`, `channel.closed` |
| `agentos/kernel/dag_executor.py` | Channel-aware dispatch — deliver messages to subscribed tasks |

#### Channel schemas

```python
"""agentos/schemas/channel.py — Message channel configuration."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ChannelMode(StrEnum):
    BROADCAST = "broadcast"   # All subscribers receive every message
    QUEUE = "queue"           # Round-robin delivery to one subscriber


class ChannelConfig(BaseModel):
    """Configuration for a named message channel within a workflow."""
    name: str = Field(description="Unique channel name within the workflow")
    mode: ChannelMode = Field(default=ChannelMode.BROADCAST)
    max_buffer: int = Field(default=100, ge=1, description="Max undelivered messages")


class ChannelMessage(BaseModel):
    """A message sent through a channel."""
    channel: str = Field(description="Channel name")
    sender_task_id: str
    sender_agent_id: str
    content: dict = Field(default_factory=dict, description="Structured message payload")
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
```

#### Channel router

```python
"""agentos/kernel/channel_router.py — Broker-mediated message channels."""
from __future__ import annotations

import threading
from collections import defaultdict

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.channel import ChannelConfig, ChannelMessage, ChannelMode
from agentos.schemas.events import Event, EventType


class ChannelRouter:
    """Routes messages between tasks via named channels.

    All messages are logged as events for auditability.
    Channels are scoped to a single workflow execution.
    """

    def __init__(
        self,
        channels: dict[str, ChannelConfig],
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._channels = channels
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._buffers: dict[str, list[ChannelMessage]] = defaultdict(list)
        self._subscribers: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.Lock()

    def register_subscriber(self, channel: str, task_id: str) -> None:
        """Register a task as a subscriber to a channel."""
        with self._lock:
            if task_id not in self._subscribers[channel]:
                self._subscribers[channel].append(task_id)

    def publish(self, message: ChannelMessage) -> None:
        """Publish a message to a channel. Emits MESSAGE_SENT event."""
        with self._lock:
            config = self._channels.get(message.channel)
            if config is None:
                raise ValueError(f"Unknown channel: {message.channel}")
            if len(self._buffers[message.channel]) >= config.max_buffer:
                raise BufferError(f"Channel '{message.channel}' buffer full")
            self._buffers[message.channel].append(message)

        self._event_log.append(Event(
            event_type=EventType.MESSAGE_SENT,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            schema_version="0.2",
            payload={
                "channel": message.channel,
                "sender_task_id": message.sender_task_id,
                "sender_agent_id": message.sender_agent_id,
                "content": message.content,
            },
        ))

    def receive(self, channel: str, task_id: str) -> list[ChannelMessage]:
        """Receive pending messages for a task on a channel."""
        with self._lock:
            config = self._channels.get(channel)
            if config is None:
                raise ValueError(f"Unknown channel: {channel}")

            if config.mode == ChannelMode.BROADCAST:
                messages = list(self._buffers[channel])
            else:  # QUEUE — round-robin
                messages = []
                remaining = []
                for msg in self._buffers[channel]:
                    if not messages:
                        messages.append(msg)
                    else:
                        remaining.append(msg)
                self._buffers[channel] = remaining

        for msg in messages:
            self._event_log.append(Event(
                event_type=EventType.MESSAGE_RECEIVED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={
                    "channel": channel,
                    "receiver_task_id": task_id,
                    "sender_task_id": msg.sender_task_id,
                    "content": msg.content,
                },
            ))
        return messages
```

#### TaskConfig extension

```python
# Added to TaskConfig in agentos/schemas/task.py
class TaskConfig(BaseModel):
    # ... existing fields ...
    publishes_to: list[str] = Field(default_factory=list, description="Channels this task publishes to")
    subscribes_to: list[str] = Field(default_factory=list, description="Channels this task subscribes to")
```

#### Workflow YAML with channels

```yaml
# examples/channel_collaboration.yaml
name: channel_collaboration
channels:
  findings:
    mode: broadcast
    max_buffer: 50
agents:
  researcher:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Research agent that publishes findings"
  analyst:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Analysis agent that subscribes to findings"
tasks:
  research:
    agent: researcher
    description: "Research the topic and publish findings to channel"
    publishes_to: [findings]
  analyze:
    agent: analyst
    description: "Analyze findings received from channel"
    subscribes_to: [findings]
    depends_on: [research]
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_channel_creation` | ChannelRouter initializes with config, channels accessible |
| `test_publish_subscribe_broadcast` | All subscribers receive all messages in broadcast mode |
| `test_publish_subscribe_queue` | Messages delivered round-robin in queue mode |
| `test_buffer_overflow` | Publishing to full channel raises BufferError |
| `test_unknown_channel` | Publishing/receiving on undeclared channel raises ValueError |
| `test_message_event_logging` | MESSAGE_SENT and MESSAGE_RECEIVED events emitted correctly |
| `test_channel_workflow_integration` | DAG executor delivers channel messages between tasks |
| `test_channel_yaml_parsing` | Workflow YAML with channels section parses correctly |
| `test_channel_backward_compat` | V1.5 workflows without channels still work |
| `test_concurrent_publish` | 10 threads publishing simultaneously, no lost messages |

**Target:** ~30 new tests. Running total: ~794.

---

### Sprint 19: Sandbox Security (Weeks 37–38)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/security/sandbox.py` | `SandboxManager` — process, namespace, and container isolation |
| `agentos/schemas/sandbox.py` | `SandboxConfig`, `SandboxLevel` |
| `tests/unit/test_sandbox.py` | Sandbox unit tests |
| `tests/integration/test_sandbox_isolation.py` | Isolation integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/schemas/capability.py` | Add `sandbox: SandboxLevel` field to `CapabilityPolicy` |
| `agentos/security/enforcer.py` | Assert sandbox requirement before tool execution |
| `agentos/schemas/events.py` | Add `sandbox.created`, `sandbox.destroyed`, `sandbox.violation` |

#### Sandbox schemas

```python
"""agentos/schemas/sandbox.py — Sandbox isolation configuration."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SandboxLevel(StrEnum):
    NONE = "none"             # V1 default — process-level only
    NAMESPACE = "namespace"   # Linux namespace isolation (PID, mount, network)
    CONTAINER = "container"   # Docker-based full isolation


class SandboxConfig(BaseModel):
    """Sandbox configuration for an agent."""
    level: SandboxLevel = Field(default=SandboxLevel.NONE)
    network_enabled: bool = Field(default=True, description="Allow network access within sandbox")
    filesystem_readonly: bool = Field(default=False, description="Mount workspace as read-only")
    memory_limit_mb: int = Field(default=0, ge=0, description="Memory limit in MB (0 = unlimited)")
    cpu_limit: float = Field(default=0.0, ge=0.0, description="CPU cores limit (0 = unlimited)")
    allowed_paths: list[str] = Field(
        default_factory=list,
        description="Paths accessible within sandbox (workspace always included)",
    )
```

#### Sandbox manager

```python
"""agentos/security/sandbox.py — Process isolation manager."""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.sandbox import SandboxConfig, SandboxLevel


class SandboxManager:
    """Manages sandbox lifecycle for agent execution.

    Three isolation levels:
    - none: Direct subprocess (V1 behavior)
    - namespace: Linux unshare(2) — PID, mount, network namespaces
    - container: Docker run with resource limits
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
        self._active: dict[str, _SandboxHandle] = {}

    def create(self, agent_id: str, config: SandboxConfig, workspace: Path) -> _SandboxHandle:
        """Create a sandbox for an agent. Emits sandbox.created event."""
        if config.level == SandboxLevel.NONE:
            handle = _NoopSandbox(workspace)
        elif config.level == SandboxLevel.NAMESPACE:
            handle = _NamespaceSandbox(config, workspace)
        elif config.level == SandboxLevel.CONTAINER:
            handle = _ContainerSandbox(config, workspace)
        else:
            raise ValueError(f"Unknown sandbox level: {config.level}")

        self._active[agent_id] = handle
        self._event_log.append(Event(
            event_type=EventType("sandbox.created"),
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            schema_version="0.2",
            payload={
                "agent_id": agent_id,
                "level": config.level.value,
                "network_enabled": config.network_enabled,
            },
        ))
        return handle

    def destroy(self, agent_id: str) -> None:
        """Tear down an agent's sandbox. Emits sandbox.destroyed event."""
        handle = self._active.pop(agent_id, None)
        if handle is not None:
            handle.teardown()
            self._event_log.append(Event(
                event_type=EventType("sandbox.destroyed"),
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={"agent_id": agent_id},
            ))


class _SandboxHandle(ABC):
    @abstractmethod
    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess: ...

    @abstractmethod
    def teardown(self) -> None: ...


class _NoopSandbox(_SandboxHandle):
    """No isolation — direct subprocess (V1 behavior)."""
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=self._workspace, **kwargs)

    def teardown(self) -> None:
        pass


class _NamespaceSandbox(_SandboxHandle):
    """Linux namespace isolation via unshare(2)."""
    def __init__(self, config: SandboxConfig, workspace: Path) -> None:
        self._config = config
        self._workspace = workspace

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        unshare_flags = ["unshare", "--pid", "--mount", "--fork"]
        if not self._config.network_enabled:
            unshare_flags.append("--net")
        return subprocess.run(unshare_flags + cmd, cwd=self._workspace, **kwargs)

    def teardown(self) -> None:
        pass


class _ContainerSandbox(_SandboxHandle):
    """Docker-based full isolation."""
    def __init__(self, config: SandboxConfig, workspace: Path) -> None:
        self._config = config
        self._workspace = workspace
        self._container_id: str | None = None

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{self._workspace}:/workspace",
            "-w", "/workspace",
        ]
        if not self._config.network_enabled:
            docker_cmd.extend(["--network", "none"])
        if self._config.memory_limit_mb > 0:
            docker_cmd.extend(["--memory", f"{self._config.memory_limit_mb}m"])
        if self._config.cpu_limit > 0:
            docker_cmd.extend(["--cpus", str(self._config.cpu_limit)])
        if self._config.filesystem_readonly:
            docker_cmd.append("--read-only")
        docker_cmd.extend(["python:3.11-slim"] + cmd)
        return subprocess.run(docker_cmd, **kwargs)

    def teardown(self) -> None:
        if self._container_id:
            subprocess.run(["docker", "stop", self._container_id], capture_output=True)
```

#### CapabilityPolicy extension

```python
# Added to CapabilityPolicy in agentos/schemas/capability.py
from agentos.schemas.sandbox import SandboxLevel

class CapabilityPolicy(BaseModel):
    # ... existing fields ...
    sandbox: SandboxLevel = Field(
        default=SandboxLevel.NONE,
        description="Required sandbox isolation level for this agent",
    )
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_sandbox_none_passthrough` | SandboxLevel.NONE runs subprocess directly (V1 behavior) |
| `test_sandbox_creation_event` | sandbox.created event emitted with correct payload |
| `test_sandbox_destruction_event` | sandbox.destroyed event emitted on teardown |
| `test_namespace_pid_isolation` | Namespace sandbox gets its own PID namespace |
| `test_namespace_network_isolation` | Network disabled when `network_enabled=False` |
| `test_container_memory_limit` | Docker sandbox respects memory_limit_mb |
| `test_container_cpu_limit` | Docker sandbox respects cpu_limit |
| `test_container_readonly_fs` | Read-only filesystem prevents writes outside workspace |
| `test_container_network_none` | Network disabled in container when configured |
| `test_sandbox_policy_enforcement` | Enforcer checks sandbox level before tool execution |
| `test_sandbox_backward_compat` | Agents without sandbox config default to NONE |
| `test_sandbox_violation_event` | Escape attempt logged as sandbox.violation |

**Target:** ~35 new tests. Running total: ~829.

---

### Sprint 20: Agent Safety Score (Weeks 39–40)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/security/safety_score.py` | `SafetyScoreCalculator` — 6-dimension risk scoring |
| `tests/unit/test_safety_score.py` | Safety score unit tests |
| `tests/integration/test_safety_dashboard.py` | Dashboard integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/dashboard/serializers.py` | Include safety score in workflow snapshot |
| `agentos/schemas/events.py` | Add `safety.score_calculated` event type |

#### Safety score calculator

```python
"""agentos/security/safety_score.py — Agent safety scoring."""
from __future__ import annotations

from dataclasses import dataclass

from agentos.kernel.event_log import EventLog
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.sandbox import SandboxLevel
from agentos.schemas.workflow import WorkflowDefinition


@dataclass
class SafetyDimension:
    """A single scored dimension with weight."""
    name: str
    score: float  # 0.0 (unsafe) to 1.0 (safe)
    weight: float
    rationale: str


@dataclass
class SafetyReport:
    """Complete safety score for a workflow."""
    overall_score: float  # Weighted average, 0.0–1.0
    grade: str  # A/B/C/D/F
    dimensions: list[SafetyDimension]
    meets_minimum: bool
    minimum_threshold: float


class SafetyScoreCalculator:
    """Calculates 6-dimension safety score for a workflow.

    Dimensions:
    1. permissions_scope — How restricted are agent capabilities?
    2. isolation_level — What sandbox level is configured?
    3. budget_constraints — How tight are budget limits?
    4. human_oversight — How many gates per critical path?
    5. adversarial_coverage — What % of outputs have validation nodes?
    6. historical_reliability — Past success rate for this config
    """

    DEFAULT_MINIMUM = 0.5

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def calculate(
        self,
        workflow: WorkflowDefinition,
        policies: dict[str, CapabilityPolicy],
        minimum: float = DEFAULT_MINIMUM,
    ) -> SafetyReport:
        """Calculate safety score for a workflow configuration."""
        dimensions = [
            self._score_permissions(workflow, policies),
            self._score_isolation(policies),
            self._score_budget(workflow),
            self._score_oversight(workflow),
            self._score_adversarial(workflow),
            self._score_reliability(workflow),
        ]
        total_weight = sum(d.weight for d in dimensions)
        overall = sum(d.score * d.weight for d in dimensions) / total_weight if total_weight else 0.0

        return SafetyReport(
            overall_score=round(overall, 3),
            grade=self._to_grade(overall),
            dimensions=dimensions,
            meets_minimum=overall >= minimum,
            minimum_threshold=minimum,
        )

    def _score_permissions(
        self, workflow: WorkflowDefinition, policies: dict[str, CapabilityPolicy],
    ) -> SafetyDimension:
        """Score based on how restricted agent permissions are."""
        if not policies:
            return SafetyDimension("permissions_scope", 0.2, 1.0, "No policies defined")

        deny_default_count = sum(1 for p in policies.values() if p.deny_by_default)
        ratio = deny_default_count / len(policies)
        # Fewer grants = safer
        avg_grants = sum(len(p.grants) for p in policies.values()) / len(policies)
        grant_penalty = min(avg_grants / 20.0, 0.5)  # Cap penalty at 0.5
        score = max(0.0, ratio - grant_penalty)
        return SafetyDimension("permissions_scope", round(score, 3), 1.0,
                               f"{deny_default_count}/{len(policies)} agents deny-by-default")

    def _score_isolation(self, policies: dict[str, CapabilityPolicy]) -> SafetyDimension:
        """Score based on sandbox isolation levels."""
        level_scores = {SandboxLevel.NONE: 0.2, SandboxLevel.NAMESPACE: 0.6, SandboxLevel.CONTAINER: 1.0}
        if not policies:
            return SafetyDimension("isolation_level", 0.2, 1.0, "No policies — no isolation")
        avg = sum(level_scores.get(p.sandbox, 0.2) for p in policies.values()) / len(policies)
        return SafetyDimension("isolation_level", round(avg, 3), 1.0, "Averaged across agents")

    def _score_budget(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on budget constraint tightness."""
        budget = workflow.budget
        has_limits = sum([
            budget.max_tokens > 0 if hasattr(budget, 'max_tokens') else False,
            budget.max_cost_usd > 0 if hasattr(budget, 'max_cost_usd') else False,
            budget.max_time_seconds > 0 if hasattr(budget, 'max_time_seconds') else False,
        ])
        score = min(has_limits / 3.0, 1.0)
        return SafetyDimension("budget_constraints", round(score, 3), 0.8,
                               f"{has_limits}/3 budget dimensions configured")

    def _score_oversight(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on human oversight density."""
        total_tasks = len(workflow.tasks)
        gate_tasks = sum(1 for t in workflow.tasks.values() if t.type in ("approval_gate", "input_gate"))
        if total_tasks == 0:
            return SafetyDimension("human_oversight", 0.0, 1.0, "No tasks")
        ratio = gate_tasks / total_tasks
        score = min(ratio * 3.0, 1.0)  # 33%+ gates = full score
        return SafetyDimension("human_oversight", round(score, 3), 0.8,
                               f"{gate_tasks}/{total_tasks} tasks are gates")

    def _score_adversarial(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on adversarial validation coverage."""
        agent_tasks = [t for t in workflow.tasks.values() if t.type == "agent_task"]
        # Check for tasks that have a downstream validation node
        validated = 0
        for task in agent_tasks:
            for other in workflow.tasks.values():
                if other.type == "agent_task" and task.name in other.depends_on:
                    # Simple heuristic: downstream tasks with "validat" in description
                    if "validat" in other.description.lower():
                        validated += 1
                        break
        total = len(agent_tasks)
        score = validated / total if total else 0.0
        return SafetyDimension("adversarial_coverage", round(score, 3), 0.6,
                               f"{validated}/{total} agent tasks have validation")

    def _score_reliability(self, workflow: WorkflowDefinition) -> SafetyDimension:
        """Score based on historical success rate for this workflow."""
        # Query event log for past runs of this workflow name
        events = self._event_log.query(event_type=EventType("workflow.completed"))
        matching = [e for e in events if e.payload.get("workflow_name") == workflow.name]
        if not matching:
            return SafetyDimension("historical_reliability", 0.5, 0.5,
                                   "No historical data — neutral score")
        successes = sum(1 for e in matching if e.payload.get("status") == "succeeded")
        score = successes / len(matching)
        return SafetyDimension("historical_reliability", round(score, 3), 0.5,
                               f"{successes}/{len(matching)} past runs succeeded")

    @staticmethod
    def _to_grade(score: float) -> str:
        if score >= 0.9:
            return "A"
        elif score >= 0.8:
            return "B"
        elif score >= 0.6:
            return "C"
        elif score >= 0.4:
            return "D"
        else:
            return "F"
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_score_all_dimensions` | All 6 dimensions calculated and weighted correctly |
| `test_score_deny_by_default` | Agents with deny_by_default score higher on permissions |
| `test_score_sandbox_levels` | Container > namespace > none scoring |
| `test_score_budget_constraints` | More budget dimensions = higher score |
| `test_score_oversight_density` | More gates = higher oversight score |
| `test_score_adversarial_coverage` | Tasks with validators score higher |
| `test_score_historical_reliability` | Past success rate reflected in score |
| `test_score_no_history_neutral` | No historical data gives 0.5 (neutral) |
| `test_grade_mapping` | Score → A/B/C/D/F grade mapping correct |
| `test_minimum_threshold` | meets_minimum=False when below threshold |
| `test_dashboard_includes_score` | Workflow snapshot serialization includes safety score |
| `test_safety_event_emitted` | safety.score_calculated event logged |

**Target:** ~30 new tests. Running total: ~859.

---

### Sprint 21: Runtime Policy Verification for Tier 2/3 (Weeks 41–42)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/security/post_hoc_verifier.py` | `PostHocVerifier` — workspace diff auditing, violation detection |
| `tests/unit/test_post_hoc_verifier.py` | Post-hoc verification unit tests |
| `tests/integration/test_tier2_policy.py` | Tier 2 policy enforcement integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/schemas/events.py` | Add `policy.violation_detected`, `policy.reloaded` event types |
| `agentos/schemas/capability.py` | Add `reload_from(new_policy)` method to `CapabilityPolicy` |
| `agentos/adapters/tier2_claude_code.py` | Post-hoc verification after task execution |

#### Post-hoc verifier

```python
"""agentos/security/post_hoc_verifier.py — Runtime policy verification for Tier 2/3."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import Event, EventType


@dataclass
class PolicyViolation:
    """A detected policy violation."""
    agent_id: str
    violation_type: str  # "path" | "domain" | "tool" | "workspace_escape"
    detail: str
    severity: str  # "warning" | "error" | "critical"


@dataclass
class VerificationResult:
    """Result of post-hoc policy verification."""
    agent_id: str
    violations: list[PolicyViolation] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    files_allowed: list[str] = field(default_factory=list)
    files_unauthorized: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0


class PostHocVerifier:
    """Verifies Tier 2/3 agent compliance after task execution.

    Checks:
    1. Workspace diff — what files did the agent actually touch?
    2. Path compliance — are all touched files within allowed paths?
    3. No workspace escape — agent stayed within its assigned workspace
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

    def verify(
        self,
        agent_id: str,
        policy: CapabilityPolicy,
        workspace: Path,
        pre_snapshot: dict[str, float],  # path → mtime before execution
        post_snapshot: dict[str, float],  # path → mtime after execution
    ) -> VerificationResult:
        """Compare workspace state before/after agent execution."""
        result = VerificationResult(agent_id=agent_id)

        # Find all changed/created files
        for path, mtime in post_snapshot.items():
            if path not in pre_snapshot or pre_snapshot[path] != mtime:
                result.files_touched.append(path)
                if policy.has_path(path):
                    result.files_allowed.append(path)
                else:
                    result.files_unauthorized.append(path)
                    result.violations.append(PolicyViolation(
                        agent_id=agent_id,
                        violation_type="path",
                        detail=f"Unauthorized file access: {path}",
                        severity="error",
                    ))

        # Check for workspace escape
        workspace_str = str(workspace.resolve())
        for path in result.files_touched:
            if not path.startswith(workspace_str):
                result.violations.append(PolicyViolation(
                    agent_id=agent_id,
                    violation_type="workspace_escape",
                    detail=f"File outside workspace: {path}",
                    severity="critical",
                ))

        # Emit events for violations
        for violation in result.violations:
            self._event_log.append(Event(
                event_type=EventType("policy.violation_detected"),
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={
                    "agent_id": agent_id,
                    "violation_type": violation.violation_type,
                    "detail": violation.detail,
                    "severity": violation.severity,
                },
            ))

        return result
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_no_violations_pass` | Clean execution with no changes passes |
| `test_unauthorized_path_detected` | File outside allowed paths flagged as violation |
| `test_workspace_escape_critical` | File outside workspace flagged as critical |
| `test_allowed_path_accepted` | File within allowed paths not flagged |
| `test_violation_events_emitted` | policy.violation_detected events logged |
| `test_policy_reload` | CapabilityPolicy updated mid-run via reload_from() |
| `test_policy_reload_event` | policy.reloaded event emitted on hot-reload |
| `test_tier2_post_hoc_integration` | ClaudeCodeAdapter calls verifier after execution |
| `test_multiple_violations` | Multiple violations all detected and reported |
| `test_severity_classification` | Path violations = error, escape = critical |

**Target:** ~25 new tests. Running total: ~884.

---

### Sprint 22: Streaming Output & WebSocket Push (Weeks 43–44)

#### Files to modify

| File | Change |
|------|--------|
| `agentos/adapters/base.py` | Add `ProgressCallback` protocol to `AgentAdapter` ABC |
| `agentos/kernel/event_log.py` | Add `subscribe(callback)` listener interface to `EventLog` |
| `agentos/dashboard/websocket.py` | Replace polling with push from EventLog listener |
| `agentos/adapters/tier1.py` | Emit progress callbacks during tool-calling loop |
| `agentos/adapters/tier2_claude_code.py` | Emit progress callbacks during subprocess execution |

#### Files to create

| File | Purpose |
|------|---------|
| `tests/unit/test_event_log_subscribe.py` | EventLog listener tests |
| `tests/integration/test_streaming.py` | End-to-end streaming tests |

#### Progress callback protocol

```python
# Added to agentos/adapters/base.py
from typing import Protocol


class ProgressCallback(Protocol):
    """Protocol for adapter progress reporting."""
    def __call__(self, agent_id: str, progress: dict) -> None:
        """Report progress during task execution.

        progress dict keys:
        - type: "tokens" | "tool_call" | "partial_output" | "status"
        - detail: type-specific data
        """
        ...


class AgentAdapter(ABC):
    # ... existing methods ...

    @abstractmethod
    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
        progress_callback: ProgressCallback | None = None,
    ) -> TaskOutput:
        """Execute a task with optional progress reporting."""
```

#### EventLog listener interface

```python
# Added to EventLog ABC in agentos/kernel/event_log.py
from typing import Callable

class EventLog(ABC):
    # ... existing methods ...

    @abstractmethod
    def subscribe(self, callback: Callable[[Event], None]) -> str:
        """Subscribe to new events. Returns subscription ID."""

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""


class SQLiteEventLog(EventLog):
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        # ... existing init ...
        self._subscribers: dict[str, Callable[[Event], None]] = {}

    def append(self, event: Event) -> None:
        # ... existing append logic ...
        # After successful append, notify subscribers
        for callback in self._subscribers.values():
            callback(event)

    def subscribe(self, callback: Callable[[Event], None]) -> str:
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscribers.pop(subscription_id, None)
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_subscribe_receives_events` | Subscriber callback invoked on append |
| `test_unsubscribe_stops_events` | Unsubscribed callback no longer invoked |
| `test_multiple_subscribers` | Multiple subscribers all receive events |
| `test_subscriber_error_isolation` | One subscriber error doesn't block others |
| `test_progress_callback_tier1` | Tier 1 adapter calls progress callback during execution |
| `test_progress_callback_tier2` | Tier 2 adapter calls progress callback during execution |
| `test_websocket_push_delivery` | WebSocket sends event within 100ms of append (vs 500ms polling) |
| `test_websocket_reconnect` | Client reconnect receives missed events |
| `test_backward_compat_no_callback` | Adapters work when progress_callback=None |

**Target:** ~25 new tests. Running total: ~909.

**Phase 4 exit criteria:**
- [ ] Channels: tasks exchange messages via ChannelRouter, events logged
- [ ] Sandbox: namespace and container isolation prevent unauthorized access
- [ ] Safety score: calculated for workflows, visible in dashboard
- [ ] Post-hoc: Tier 2 file access violations detected after execution
- [ ] Streaming: WebSocket push replaces polling, <100ms latency
- [ ] ~909 tests passing (+145 from V1.5 baseline)

---

## Phase 5: Platform (Sprints 23–27)

**Exit criterion:** Two users log in and see only their workflows. Visual builder produces valid YAML. Agent in run #2 receives relevant findings from run #1.

### Sprint 23: Authentication & Multi-User (Weeks 45–46)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/dashboard/auth.py` | JWT + API key middleware for FastAPI |
| `agentos/schemas/auth.py` | `AuthConfig`, `User`, `APIKey`, `Role` |
| `tests/unit/test_auth.py` | Authentication unit tests |
| `tests/integration/test_multi_user.py` | Multi-user isolation integration tests |

#### Auth schemas

```python
"""agentos/schemas/auth.py — Authentication and authorization."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    ADMIN = "admin"       # Full access + user management
    OPERATOR = "operator"  # Run workflows, resolve gates
    VIEWER = "viewer"      # Read-only dashboard access


class User(BaseModel):
    """A registered user."""
    user_id: str
    username: str
    role: Role = Field(default=Role.OPERATOR)
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class APIKey(BaseModel):
    """An API key for programmatic access."""
    key_id: str
    user_id: str
    name: str = Field(description="Human-readable key name")
    prefix: str = Field(description="First 8 chars of key for identification")
    role: Role = Field(default=Role.OPERATOR)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    expires_at: datetime | None = None


class AuthConfig(BaseModel):
    """Authentication configuration."""
    enabled: bool = Field(default=False, description="Auth disabled by default (local-first)")
    jwt_secret: str = Field(default="", description="JWT signing secret (generate on first enable)")
    token_expiry_hours: int = Field(default=24)
    allow_anonymous: bool = Field(default=True, description="Allow unauthenticated local access")
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_auth_disabled_default` | No auth required when `enabled=False` |
| `test_jwt_login_flow` | Username/password → JWT token → authenticated request |
| `test_jwt_expiry` | Expired token rejected with 401 |
| `test_api_key_auth` | API key in header authenticates request |
| `test_api_key_expiry` | Expired API key rejected |
| `test_role_admin` | Admin can manage users and run workflows |
| `test_role_operator` | Operator can run workflows but not manage users |
| `test_role_viewer` | Viewer can only read dashboard data |
| `test_user_isolation` | User A cannot see User B's workflows |
| `test_user_scoped_events` | Event queries filtered by user |
| `test_api_key_crud` | Create, list, revoke API keys |
| `test_anonymous_local` | Anonymous access works when allow_anonymous=True |

**Target:** ~30 new tests. Running total: ~939.

---

### Sprint 24: Cross-Run Memory (Weeks 47–48)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/memory_store.py` | `MemoryStore` ABC + `SQLiteMemoryStore` |
| `tests/unit/test_memory_store.py` | Memory store unit tests |
| `tests/integration/test_cross_run_memory.py` | Cross-run injection integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/schemas/events.py` | Add `memory.extracted`, `memory.injected` event types |
| `agentos/adapters/base.py` | Add `predecessor_context` extension for memory injection |
| `agentos/kernel/dag_executor.py` | Query memory store before task dispatch |

#### Memory store

```python
"""agentos/kernel/memory_store.py — Cross-run persistent memory."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, UTC

from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    """A single memory extracted from a completed workflow."""
    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_name: str
    workflow_id: str
    task_id: str
    agent_id: str
    memory_type: str = Field(description="finding | decision | feedback | observation")
    content: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_days: int = Field(default=90, description="Time to live in days")
    decay_rate: float = Field(
        default=0.01, ge=0.0, le=1.0,
        description="Confidence decay per day (0 = no decay)",
    )


class MemoryStore(ABC):
    """Abstract persistent memory store for cross-run knowledge."""

    @abstractmethod
    def store(self, entry: MemoryEntry) -> None:
        """Store a memory entry."""

    @abstractmethod
    def query(
        self,
        workflow_name: str | None = None,
        tags: list[str] | None = None,
        min_confidence: float = 0.0,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """Query memories with optional filters. Returns by recency."""

    @abstractmethod
    def decay(self) -> int:
        """Apply confidence decay to all entries. Remove expired. Returns count removed."""

    @abstractmethod
    def extract_from_workflow(self, workflow_id: str, event_log) -> list[MemoryEntry]:
        """Auto-extract memories from a completed workflow's events."""


class SQLiteMemoryStore(MemoryStore):
    """SQLite-backed memory store. Separate from event log."""

    MEMORY_TABLE_DDL = """\
    CREATE TABLE IF NOT EXISTS memory_store (
        memory_id TEXT PRIMARY KEY,
        workflow_name TEXT NOT NULL,
        workflow_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        content TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        tags TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        ttl_days INTEGER NOT NULL DEFAULT 90,
        decay_rate REAL NOT NULL DEFAULT 0.01
    );
    CREATE INDEX IF NOT EXISTS idx_memory_workflow ON memory_store(workflow_name);
    CREATE INDEX IF NOT EXISTS idx_memory_confidence ON memory_store(confidence);
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self.MEMORY_TABLE_DDL)
        self._conn.commit()

    # ... store, query, decay, extract_from_workflow implementations
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_store_and_query` | Store entry, query by workflow_name returns it |
| `test_query_by_tags` | Tag filtering works correctly |
| `test_query_min_confidence` | Low-confidence entries filtered out |
| `test_confidence_decay` | decay() reduces confidence by decay_rate per day |
| `test_ttl_expiry` | Entries past TTL removed by decay() |
| `test_extract_findings` | Auto-extraction from workflow events captures key findings |
| `test_extract_gate_feedback` | Gate rejection feedback extracted as memories |
| `test_injection_into_context` | Memory entries injected into agent predecessor_context |
| `test_cross_run_integration` | Run #2 receives findings from run #1 |
| `test_relevance_filtering` | Only same-workflow-name memories injected |
| `test_memory_events` | memory.extracted and memory.injected events logged |
| `test_decay_removes_stale` | Old low-confidence entries cleaned up |

**Target:** ~30 new tests. Running total: ~969.

---

### Sprint 25: Visual Workflow Builder — Backend (Weeks 49–50)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/dashboard/builder.py` | REST API: workflow CRUD, validate, execute |
| `tests/unit/test_builder_api.py` | Builder API unit tests |
| `tests/integration/test_builder_workflow.py` | Builder → execute integration tests |

#### Builder REST API

```python
"""agentos/dashboard/builder.py — Visual workflow builder backend."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agentos.schemas.workflow import WorkflowDefinition
from agentos.validation.workflow_verifier import WorkflowVerifier


router = APIRouter(prefix="/api/builder", tags=["builder"])


class WorkflowTemplate(BaseModel):
    """Stored workflow template."""
    template_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    definition: WorkflowDefinition
    yaml_source: str = ""
    created_by: str = ""
    version: int = 1


class ValidationResponse(BaseModel):
    """Live validation result."""
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# POST /api/builder/templates       — Create template
# GET  /api/builder/templates        — List templates
# GET  /api/builder/templates/{id}   — Get template
# PUT  /api/builder/templates/{id}   — Update template
# DELETE /api/builder/templates/{id} — Delete template
# POST /api/builder/validate         — Live validation
# POST /api/builder/export-yaml      — Export WorkflowDefinition to YAML
# POST /api/builder/import-yaml      — Import YAML to WorkflowDefinition
# POST /api/builder/execute/{id}     — Execute a stored template
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_template_crud` | Create, read, update, delete workflow templates |
| `test_template_list` | List templates with pagination |
| `test_live_validation_valid` | Valid workflow returns `valid: true` |
| `test_live_validation_errors` | Invalid DAG returns errors list |
| `test_yaml_export` | WorkflowDefinition → YAML round-trip |
| `test_yaml_import` | YAML → WorkflowDefinition round-trip |
| `test_yaml_roundtrip_fidelity` | Export → import produces identical definition |
| `test_execute_template` | Stored template executes via API |
| `test_version_increment` | Template update increments version |
| `test_template_not_found` | GET non-existent template returns 404 |

**Target:** ~25 new tests. Running total: ~994.

---

### Sprint 26: Visual Workflow Builder — Frontend (Weeks 51–52)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/dashboard/frontend/src/pages/BuilderPage.tsx` | Builder page layout |
| `agentos/dashboard/frontend/src/components/builder/NodePalette.tsx` | Draggable node types |
| `agentos/dashboard/frontend/src/components/builder/Canvas.tsx` | DAG canvas with Dagre layout |
| `agentos/dashboard/frontend/src/components/builder/EdgeDrawer.tsx` | Edge drawing between nodes |
| `agentos/dashboard/frontend/src/components/builder/PropertyPanel.tsx` | Node/edge property editor |
| `agentos/dashboard/frontend/src/hooks/useBuilder.ts` | Builder state management |
| `agentos/dashboard/frontend/src/api/builder.ts` | Builder REST API client |
| `tests/e2e/test_builder_e2e.py` | Builder end-to-end tests |

#### Frontend components

```
BuilderPage
├── NodePalette         # Left sidebar: drag agent_task, approval_gate, input_gate, consultation
├── Canvas              # Center: Dagre-based interactive DAG
│   ├── BuilderNode     # Draggable, selectable node with type icon
│   └── EdgeDrawer      # SVG edge with click-to-create
├── PropertyPanel       # Right sidebar: edit selected node/edge properties
└── BuilderToolbar      # Top: Save, Validate, Export YAML, Import YAML, Execute
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_builder_page_renders` | BuilderPage loads with empty canvas |
| `test_drag_node_creation` | Dragging from palette creates node on canvas |
| `test_edge_drawing` | Click-drag between nodes creates edge |
| `test_property_editing` | Selecting node shows properties, edits apply |
| `test_live_validation_feedback` | Invalid DAG shows inline errors |
| `test_export_yaml` | Export button produces valid YAML |
| `test_import_yaml` | Import populates canvas from YAML file |
| `test_save_template` | Save button calls POST /api/builder/templates |
| `test_execute_from_builder` | Execute button triggers workflow run |
| `test_builder_to_dashboard_flow` | Build → execute → redirect to dashboard |

**Target:** ~25 new tests. Running total: ~1019.

---

### Sprint 27: Platform Integration & Agent Audit (Weeks 53–54)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/cli/audit.py` | `agentos audit` CLI command |
| `tests/e2e/test_multi_user_e2e.py` | Multi-user isolation E2E |
| `tests/e2e/test_cross_run_e2e.py` | Cross-run memory E2E |
| `tests/e2e/test_builder_execute_e2e.py` | Builder → execute → dashboard E2E |

#### Agent audit CLI

```
agentos audit scan <workspace>          # Scan for agent usage patterns
agentos audit report <workspace>        # Generate risk assessment report
agentos audit report --format json      # Machine-readable output
```

The audit tool scans for:
- Agent session artifacts (`.claude/`, `.codex/`, etc.)
- Uncontrolled credential exposure in agent conversations
- File access patterns outside expected workspace boundaries
- Unmonitored agent processes

Output: structured risk assessment report with severity levels and remediation recommendations.

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_two_users_isolated` | User A's workflows invisible to User B |
| `test_user_a_events_scoped` | User A's event queries return only their events |
| `test_cross_run_memory_injection` | Run #2 agent receives findings from run #1 |
| `test_cross_run_different_workflow` | Memories not injected into unrelated workflows |
| `test_builder_execute_dashboard` | Build workflow → execute → view in dashboard |
| `test_audit_scan` | Audit detects Claude Code session artifacts |
| `test_audit_report_json` | Audit produces valid JSON report |
| `test_audit_severity_levels` | Risk items classified by severity |
| `test_platform_e2e_full` | Auth → build → execute → monitor → memory E2E |

**Target:** ~25 new tests. Running total: ~1044.

**Phase 5 exit criteria:**
- [ ] Auth: two users log in, each sees only their workflows
- [ ] Memory: run #2 agent receives relevant findings from run #1
- [ ] Builder backend: template CRUD, validation, YAML round-trip
- [ ] Builder frontend: drag-and-drop canvas produces valid workflows
- [ ] Audit: `agentos audit` scans workspace and produces risk report
- [ ] ~1044 tests passing (+280 from V1.5 baseline)

---

## Phase 6: Intelligence (Sprints 28–31)

**Exit criterion:** Benchmark report compares 2+ backends. Manager agent routes correctly 90%+. Marketplace has 5+ templates with verified metrics.

### Sprint 28: Benchmarking Engine (Weeks 55–56)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/intelligence/__init__.py` | Intelligence package init |
| `agentos/intelligence/benchmark.py` | `BenchmarkRunner` — multi-backend comparison |
| `agentos/schemas/benchmark.py` | `BenchmarkConfig`, `BenchmarkResult`, `BenchmarkReport` |
| `agentos/cli/benchmark.py` | `agentos benchmark run/report` CLI commands |
| `tests/unit/test_benchmark.py` | Benchmarking unit tests |

#### Benchmark schemas

```python
"""agentos/schemas/benchmark.py — Benchmarking engine schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BenchmarkConfig(BaseModel):
    """Configuration for a benchmark run."""
    name: str
    task_description: str
    backends: list[str] = Field(description="Agent adapter names to compare")
    runs_per_backend: int = Field(default=3, ge=1)
    quality_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria for output quality evaluation",
    )
    timeout_seconds: int = Field(default=300)


class BenchmarkResult(BaseModel):
    """Result from a single benchmark run."""
    backend: str
    run_number: int
    success: bool
    execution_time_seconds: float
    tokens_consumed: int
    estimated_cost_usd: float
    output_quality_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Quality score (0–1) based on criteria evaluation",
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class BenchmarkReport(BaseModel):
    """Aggregated benchmark report across backends."""
    name: str
    task_description: str
    results: list[BenchmarkResult]
    summary: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Per-backend aggregated metrics (avg_time, avg_cost, avg_quality)",
    )
    winner: str = Field(default="", description="Backend with best quality/cost ratio")
    generated_at: datetime = Field(default_factory=lambda: datetime.now())
```

#### CLI commands

```
agentos benchmark run <config.yaml>     # Run benchmark
agentos benchmark report <benchmark-id> # View report
agentos benchmark list                  # List past benchmarks
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_benchmark_config_parse` | YAML config parsed to BenchmarkConfig |
| `test_multi_backend_execution` | Same task runs on 2+ backends |
| `test_result_aggregation` | Per-backend avg time, cost, quality calculated |
| `test_winner_selection` | Best quality/cost ratio backend selected |
| `test_benchmark_events` | benchmark.started and benchmark.completed events logged |
| `test_benchmark_report_json` | Report serializes to valid JSON |
| `test_cli_benchmark_run` | CLI command triggers benchmark execution |
| `test_cli_benchmark_report` | CLI command displays benchmark report |
| `test_timeout_enforcement` | Backend exceeding timeout marked as failed |
| `test_benchmark_history` | Past benchmarks queryable |

**Target:** ~25 new tests. Running total: ~1069.

---

### Sprint 29: Manager Agent (Weeks 57–58)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/adapters/manager_agent.py` | `ManagerAgent` — LLM-powered message router |
| `tests/unit/test_manager_agent.py` | Manager agent unit tests |
| `tests/integration/test_manager_routing.py` | Routing integration tests |

#### Manager agent

```python
"""agentos/adapters/manager_agent.py — LLM-powered message router."""
from __future__ import annotations

from dataclasses import dataclass, field

from agentos.kernel.channel_router import ChannelRouter
from agentos.schemas.channel import ChannelMessage


@dataclass
class RoutingRule:
    """A deterministic routing rule."""
    pattern: str  # Regex or keyword match on message content
    target_channel: str
    priority: int = 0


@dataclass
class RoutingDecision:
    """Result of routing a message."""
    target_channel: str
    confidence: float  # 0.0–1.0
    method: str  # "rule" | "llm" | "escalated"
    rationale: str = ""


class ManagerAgent:
    """Routes messages between channels using rules + LLM fallback.

    Routing priority:
    1. Deterministic rules (pattern matching)
    2. LLM-based routing (when no rule matches)
    3. Human escalation (when LLM confidence < threshold)
    """

    def __init__(
        self,
        channel_router: ChannelRouter,
        rules: list[RoutingRule] | None = None,
        escalation_threshold: float = 0.5,
    ) -> None:
        self._channel_router = channel_router
        self._rules = sorted(rules or [], key=lambda r: -r.priority)
        self._escalation_threshold = escalation_threshold

    def route(self, message: ChannelMessage) -> RoutingDecision:
        """Route a message to the appropriate channel."""
        # 1. Try deterministic rules
        for rule in self._rules:
            if self._matches_rule(rule, message):
                return RoutingDecision(
                    target_channel=rule.target_channel,
                    confidence=1.0,
                    method="rule",
                    rationale=f"Matched rule pattern: {rule.pattern}",
                )

        # 2. LLM-based routing
        decision = self._llm_route(message)
        if decision.confidence >= self._escalation_threshold:
            return decision

        # 3. Escalate to human
        return RoutingDecision(
            target_channel="human_review",
            confidence=decision.confidence,
            method="escalated",
            rationale=f"LLM confidence {decision.confidence} below threshold",
        )

    def _matches_rule(self, rule: RoutingRule, message: ChannelMessage) -> bool:
        """Check if a message matches a routing rule."""
        import re
        content_str = str(message.content)
        return bool(re.search(rule.pattern, content_str, re.IGNORECASE))

    def _llm_route(self, message: ChannelMessage) -> RoutingDecision:
        """Use LLM to determine routing when no rules match."""
        # Implementation uses Tier 1 adapter for a single classification call
        ...
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_rule_based_routing` | Message matching rule routed to correct channel |
| `test_rule_priority` | Higher-priority rule wins when multiple match |
| `test_llm_routing_fallback` | No-rule message routed by LLM |
| `test_escalation_low_confidence` | LLM confidence below threshold escalates to human |
| `test_escalation_threshold` | Configurable threshold respected |
| `test_routing_decision_fields` | RoutingDecision populated correctly |
| `test_manager_channel_integration` | Routed message delivered to target channel |
| `test_regex_pattern_matching` | Complex regex patterns match correctly |
| `test_no_rules_llm_only` | Manager with no rules falls through to LLM |
| `test_routing_event_logging` | Routing decisions logged as events |

**Target:** ~25 new tests. Running total: ~1094.

---

### Sprint 30: Agent Marketplace — Backend (Weeks 59–60)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/marketplace/__init__.py` | Marketplace package init |
| `agentos/marketplace/registry.py` | `TemplateRegistry` — template CRUD + metrics |
| `agentos/schemas/marketplace.py` | `MarketplaceTemplate`, `TemplateMetrics` |
| `tests/unit/test_marketplace.py` | Marketplace unit tests |

#### Marketplace schemas

```python
"""agentos/schemas/marketplace.py — Agent marketplace schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agentos.schemas.workflow import WorkflowDefinition


class TemplateMetrics(BaseModel):
    """Verified performance metrics for a marketplace template."""
    total_runs: int = 0
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_cost_usd: float = 0.0
    avg_duration_seconds: float = 0.0
    avg_approval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    last_updated: datetime = Field(default_factory=lambda: datetime.now())


class MarketplaceTemplate(BaseModel):
    """A workflow template listed in the marketplace."""
    template_id: str
    name: str
    description: str
    author: str
    tags: list[str] = Field(default_factory=list)
    definition: WorkflowDefinition
    metrics: TemplateMetrics = Field(default_factory=TemplateMetrics)
    published: bool = False
    downloads: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_template_publish` | Template published to marketplace |
| `test_template_search_by_tag` | Search by tags returns matching templates |
| `test_template_search_by_name` | Search by name returns matching templates |
| `test_metrics_calculation` | Metrics computed from actual workflow runs |
| `test_metrics_update` | Metrics update after new runs |
| `test_template_download` | Download increments counter, returns definition |
| `test_template_import_export` | Import/export with metadata preserved |
| `test_unpublished_not_searchable` | Unpublished templates not in search results |
| `test_metrics_accuracy` | Calculated metrics match event log data |
| `test_template_versioning` | Template updates preserve version history |

**Target:** ~25 new tests. Running total: ~1119.

---

### Sprint 31: Marketplace Frontend & Intelligence Polish (Weeks 61–62)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/dashboard/frontend/src/pages/MarketplacePage.tsx` | Marketplace browser UI |
| `agentos/dashboard/frontend/src/components/marketplace/TemplateBrowser.tsx` | Template list with search/filter |
| `agentos/dashboard/frontend/src/components/marketplace/MetricsCard.tsx` | Performance metrics display |
| `agentos/dashboard/frontend/src/components/marketplace/DeployButton.tsx` | One-click deploy to builder |
| `agentos/dashboard/frontend/src/pages/BenchmarkPage.tsx` | Benchmark results visualization |
| `tests/e2e/test_marketplace_e2e.py` | Marketplace E2E tests |
| `tests/e2e/test_intelligence_e2e.py` | Intelligence phase E2E tests |

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_marketplace_page_renders` | MarketplacePage loads with template list |
| `test_template_search_ui` | Search filters templates in real-time |
| `test_metrics_display` | Performance metrics visible per template |
| `test_one_click_deploy` | Deploy button creates workflow from template |
| `test_deploy_to_builder` | Deploy opens template in visual builder |
| `test_benchmark_visualization` | Benchmark results render as comparison chart |
| `test_intelligence_e2e` | Benchmark → report → marketplace metrics E2E |
| `test_marketplace_e2e` | Browse → deploy → execute → metrics update E2E |

**Target:** ~20 new tests. Running total: ~1139.

**Phase 6 exit criteria:**
- [ ] Benchmarks: report compares 2+ backends on same task
- [ ] Manager agent: rule-based routing 100%, LLM routing 90%+
- [ ] Marketplace: 5+ templates with verified metrics
- [ ] Frontend: marketplace browser, benchmark visualization
- [ ] ~1139 tests passing (+375 from V1.5 baseline)

---

## Phase 7: Adaptive Orchestration (Sprints 32–36)

**Exit criterion:** Workflow spawns new agent at runtime, output feeds downstream. Knowledge graph accumulates across runs. System recommends better configurations.

### Sprint 32: Mutable DAG (Weeks 63–64)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/mutable_dag.py` | `MutableDAG` — thread-safe runtime DAG mutation |
| `tests/unit/test_mutable_dag.py` | Mutable DAG unit tests |
| `tests/integration/test_dynamic_tasks.py` | Dynamic task integration tests |

#### Files to modify

| File | Change |
|------|--------|
| `agentos/schemas/events.py` | Add `task.added`, `task.wired` event types |
| `agentos/kernel/dag_executor.py` | Use `MutableDAG` wrapper, support runtime insertion |
| `agentos/kernel/replayer.py` | Reconstruct dynamic tasks from `task.added` events |

#### Mutable DAG

```python
"""agentos/kernel/mutable_dag.py — Thread-safe runtime DAG mutation."""
from __future__ import annotations

import threading

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskConfig


class MutableDAG:
    """Thread-safe wrapper around the task graph that supports runtime insertion.

    All mutations emit events so the replayer can reconstruct the final graph.
    Static verification runs on the initial DAG; dynamic additions are
    validated at insertion time (no cycles, valid dependencies).
    """

    def __init__(
        self,
        tasks: dict[str, TaskConfig],
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._tasks = dict(tasks)  # Defensive copy
        self._lock = threading.Lock()
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

    @property
    def tasks(self) -> dict[str, TaskConfig]:
        with self._lock:
            return dict(self._tasks)

    def add_task(self, task: TaskConfig) -> None:
        """Add a task at runtime. Validates no cycles, emits task.added event."""
        with self._lock:
            if task.name in self._tasks:
                raise ValueError(f"Task '{task.name}' already exists")

            # Validate dependencies exist
            for dep in task.depends_on:
                if dep not in self._tasks:
                    raise ValueError(f"Dependency '{dep}' does not exist")

            # Cycle detection with new task
            self._check_no_cycle(task)

            self._tasks[task.name] = task

        self._event_log.append(Event(
            event_type=EventType("task.added"),
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            schema_version="0.2",
            payload={
                "task_name": task.name,
                "task_config": task.model_dump(),
            },
        ))

    def wire(self, task_name: str, depends_on: str) -> None:
        """Add a dependency edge at runtime. Emits task.wired event."""
        with self._lock:
            if task_name not in self._tasks:
                raise ValueError(f"Task '{task_name}' does not exist")
            if depends_on not in self._tasks:
                raise ValueError(f"Dependency '{depends_on}' does not exist")

            task = self._tasks[task_name]
            if depends_on not in task.depends_on:
                task.depends_on.append(depends_on)
                self._check_no_cycle(task)

        self._event_log.append(Event(
            event_type=EventType("task.wired"),
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            schema_version="0.2",
            payload={
                "task_name": task_name,
                "depends_on": depends_on,
            },
        ))

    def _check_no_cycle(self, new_task: TaskConfig) -> None:
        """Verify adding this task doesn't create a cycle. Raises ValueError."""
        visited: set[str] = set()
        stack: set[str] = set()

        def dfs(name: str) -> None:
            if name in stack:
                raise ValueError(f"Cycle detected involving task '{name}'")
            if name in visited:
                return
            stack.add(name)
            task = self._tasks.get(name, new_task if name == new_task.name else None)
            if task:
                for dep in task.depends_on:
                    dfs(dep)
            stack.discard(name)
            visited.add(name)

        for task_name in self._tasks:
            dfs(task_name)
        if new_task.name not in visited:
            dfs(new_task.name)
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_add_task_runtime` | Task added during execution appears in graph |
| `test_add_duplicate_raises` | Adding task with existing name raises ValueError |
| `test_add_invalid_dependency` | Adding task with non-existent dependency raises ValueError |
| `test_cycle_detection` | Adding task that creates cycle raises ValueError |
| `test_wire_runtime` | New dependency edge added between existing tasks |
| `test_task_added_event` | task.added event emitted with full config |
| `test_task_wired_event` | task.wired event emitted with edge details |
| `test_concurrent_insertion` | 10 threads adding tasks, no race conditions |
| `test_replayer_dynamic_tasks` | Replayer reconstructs dynamic tasks from events |
| `test_executor_dynamic_dispatch` | Executor dispatches dynamically added tasks |
| `test_thread_safety` | Concurrent reads and writes maintain consistency |
| `test_snapshot_isolation` | tasks property returns copy, not mutable reference |

**Target:** ~30 new tests. Running total: ~1169.

---

### Sprint 33: Dynamic Team Composition (Weeks 65–66)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/team_composer.py` | `TeamComposer` — agent spawn request handling |
| `agentos/schemas/spawn.py` | `SpawnPolicy`, `SpawnRequest`, `AgentArchetype` |
| `tests/unit/test_team_composer.py` | Team composition unit tests |
| `tests/integration/test_dynamic_team.py` | Dynamic team integration tests |

#### Spawn schemas

```python
"""agentos/schemas/spawn.py — Dynamic team composition schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.agent import AgentConfig


class AgentArchetype(BaseModel):
    """Pre-defined agent template in the archetype catalog."""
    archetype_id: str
    name: str
    description: str
    config: AgentConfig
    required_capabilities: list[str] = Field(default_factory=list)


class SpawnRequest(BaseModel):
    """Structured request from an agent to spawn a new team member."""
    requesting_agent_id: str
    requesting_task_id: str
    reason: str = Field(description="Why a new agent is needed")
    archetype_id: str | None = Field(default=None, description="Preferred archetype")
    role_description: str = Field(default="", description="Free-text role description if no archetype")
    insert_before_task: str | None = Field(default=None, description="Task that should depend on new agent")


class SpawnPolicy(BaseModel):
    """Policy governing dynamic agent spawning."""
    allow_spawn: bool = Field(default=False, description="Whether dynamic spawning is enabled")
    require_gate: bool = Field(default=True, description="Require human approval for spawns")
    max_spawns_per_workflow: int = Field(default=3, ge=0)
    allowed_archetypes: list[str] = Field(
        default_factory=list,
        description="Archetype IDs that can be spawned (empty = any)",
    )
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_spawn_request_parsing` | SpawnRequest from agent output parsed correctly |
| `test_spawn_gate_approval` | Spawn request creates approval gate |
| `test_spawn_gate_rejection` | Rejected spawn does not create agent |
| `test_spawn_from_archetype` | Archetype template provisions correct agent config |
| `test_spawn_custom_role` | Custom role description creates agent without archetype |
| `test_spawn_limit_enforcement` | Max spawns per workflow enforced |
| `test_spawn_policy_disabled` | Spawn request rejected when allow_spawn=False |
| `test_dynamic_task_insertion` | Spawned agent's task inserted into running DAG |
| `test_spawn_events` | agent.spawn_requested and agent.spawn_approved events logged |
| `test_downstream_dependency` | insert_before_task creates correct dependency |
| `test_catalog_query` | Archetype catalog searchable by capability |
| `test_spawn_e2e` | Agent requests → gate → spawn → execute → output feeds downstream |

**Target:** ~30 new tests. Running total: ~1199.

---

### Sprint 34: Knowledge Graph Store (Weeks 67–68)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/intelligence/knowledge_graph.py` | `KnowledgeGraph` ABC + `SQLiteKnowledgeGraph` |
| `tests/unit/test_knowledge_graph.py` | Knowledge graph unit tests |
| `tests/integration/test_knowledge_accumulation.py` | Cross-run accumulation tests |

#### Knowledge graph

```python
"""agentos/intelligence/knowledge_graph.py — SQLite-backed knowledge graph."""
from __future__ import annotations

import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, UTC

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """A node in the knowledge graph."""
    entity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    entity_type: str = Field(description="person | company | concept | finding | decision")
    properties: dict = Field(default_factory=dict)
    provenance_workflow_id: str = ""
    provenance_agent_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Relationship(BaseModel):
    """An edge in the knowledge graph."""
    relationship_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    relation_type: str = Field(description="e.g. 'found_by', 'depends_on', 'contradicts'")
    properties: dict = Field(default_factory=dict)
    provenance_workflow_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class KnowledgeGraph(ABC):
    """Abstract knowledge graph store."""

    @abstractmethod
    def add_entity(self, entity: Entity) -> str:
        """Add an entity. Returns entity_id."""

    @abstractmethod
    def add_relationship(self, relationship: Relationship) -> str:
        """Add a relationship between entities."""

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None:
        """Get entity by ID."""

    @abstractmethod
    def find_entities(self, entity_type: str | None = None, name_pattern: str | None = None) -> list[Entity]:
        """Search entities by type and/or name pattern."""

    @abstractmethod
    def traverse(self, start_id: str, relation_types: list[str] | None = None, max_depth: int = 3) -> list[Entity]:
        """BFS/DFS traversal from a starting entity."""

    @abstractmethod
    def query_context(self, task_description: str, limit: int = 20) -> list[Entity]:
        """Find entities relevant to a task description."""


class SQLiteKnowledgeGraph(KnowledgeGraph):
    """SQLite-backed knowledge graph with provenance tracking."""

    SCHEMA_DDL = """\
    CREATE TABLE IF NOT EXISTS kg_entities (
        entity_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        properties TEXT NOT NULL DEFAULT '{}',
        provenance_workflow_id TEXT,
        provenance_agent_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_kg_entity_type ON kg_entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_kg_entity_name ON kg_entities(name);

    CREATE TABLE IF NOT EXISTS kg_relationships (
        relationship_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES kg_entities(entity_id),
        target_id TEXT NOT NULL REFERENCES kg_entities(entity_id),
        relation_type TEXT NOT NULL,
        properties TEXT NOT NULL DEFAULT '{}',
        provenance_workflow_id TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_kg_rel_source ON kg_relationships(source_id);
    CREATE INDEX IF NOT EXISTS idx_kg_rel_target ON kg_relationships(target_id);
    CREATE INDEX IF NOT EXISTS idx_kg_rel_type ON kg_relationships(relation_type);
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(self.SCHEMA_DDL)
        self._conn.commit()

    # ... add_entity, add_relationship, get_entity, find_entities, traverse, query_context
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_add_entity` | Entity stored and retrievable by ID |
| `test_add_relationship` | Relationship created between two entities |
| `test_find_by_type` | Entities filtered by entity_type |
| `test_find_by_name_pattern` | Name pattern search works (LIKE query) |
| `test_bfs_traversal` | BFS from entity reaches connected entities |
| `test_traversal_max_depth` | Traversal respects max_depth limit |
| `test_traversal_relation_filter` | Only specified relation types followed |
| `test_provenance_tracking` | Entity provenance links to workflow and agent |
| `test_cross_run_accumulation` | Entities from run #1 visible in run #2 |
| `test_query_context_relevance` | Task description finds relevant entities |
| `test_memory_store_integration` | Knowledge graph integrates with cross-run memory |
| `test_knowledge_events` | knowledge.entity_added, knowledge.relationship_added events logged |

**Target:** ~30 new tests. Running total: ~1229.

---

### Sprint 35: Workflow-Level Learning (Weeks 69–70)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/intelligence/learning.py` | `PatternDetector`, `ConfigRecommender` |
| `agentos/cli/suggest.py` | `agentos suggest` CLI command |
| `tests/unit/test_learning.py` | Learning unit tests |

#### Learning engine

```python
"""agentos/intelligence/learning.py — Workflow-level learning."""
from __future__ import annotations

from dataclasses import dataclass, field

from agentos.kernel.event_log import EventLog


@dataclass
class WorkflowPattern:
    """A detected pattern from historical workflow data."""
    pattern_type: str  # "team_composition" | "gate_placement" | "budget_config"
    description: str
    confidence: float  # 0.0–1.0
    evidence_count: int
    recommendation: str


@dataclass
class ConfigRecommendation:
    """A suggested configuration improvement."""
    target: str  # "agent" | "workflow" | "budget" | "gate"
    current_value: str
    recommended_value: str
    expected_improvement: str
    based_on_patterns: list[str]


class PatternDetector:
    """Detects correlations between workflow config and outcomes."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def detect(self, workflow_name: str | None = None) -> list[WorkflowPattern]:
        """Analyze historical runs and detect patterns."""
        # Correlation analysis: team composition → outcome quality
        # Gate placement → approval rate on first attempt
        # Budget allocation → completion rate
        ...


class ConfigRecommender:
    """Produces configuration recommendations from detected patterns."""

    def __init__(self, detector: PatternDetector) -> None:
        self._detector = detector

    def recommend(self, workflow_name: str) -> list[ConfigRecommendation]:
        """Generate recommendations for a workflow."""
        patterns = self._detector.detect(workflow_name)
        # Convert high-confidence patterns to actionable recommendations
        ...
```

#### CLI command

```
agentos suggest <workflow-name>         # Show recommendations for a workflow
agentos suggest --all                   # Show recommendations across all workflows
agentos suggest --min-confidence 0.8    # Only high-confidence recommendations
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_detect_team_composition` | Detects team size → outcome correlation |
| `test_detect_gate_placement` | Detects gate placement → approval rate correlation |
| `test_detect_budget_config` | Detects budget allocation → completion correlation |
| `test_pattern_confidence` | Patterns have evidence-based confidence scores |
| `test_recommend_team_change` | Recommends adding agent when pattern shows improvement |
| `test_recommend_gate_addition` | Recommends gate when rejection rate is high |
| `test_no_recommendations_insufficient_data` | No recommendations when <5 historical runs |
| `test_cli_suggest` | CLI command displays formatted recommendations |
| `test_recommendation_target_types` | Recommendations cover agent/workflow/budget/gate |

**Target:** ~25 new tests. Running total: ~1254.

---

### Sprint 36: V3 Integration & Hardening (Weeks 71–72)

#### Files to create

| File | Purpose |
|------|---------|
| `tests/e2e/test_dynamic_composition_e2e.py` | Dynamic team composition E2E |
| `tests/e2e/test_knowledge_graph_e2e.py` | Knowledge graph accumulation E2E |
| `tests/e2e/test_learning_e2e.py` | Learning recommendations E2E |

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_agent_spawns_new_agent` | Agent requests → approval gate → spawn → execute |
| `test_spawned_output_feeds_downstream` | Dynamically spawned agent's output consumed by dependent |
| `test_mutable_dag_replay` | Replayer reconstructs full graph including dynamic tasks |
| `test_knowledge_across_5_runs` | Knowledge graph entities accumulate over 5 workflow runs |
| `test_learning_from_history` | Recommendations improve after 10+ historical runs |
| `test_full_v3_scenario` | Dynamic spawn + knowledge + learning in one workflow |
| `test_dynamic_composition_with_channels` | Spawned agent uses message channels |
| `test_safety_score_dynamic_agents` | Safety score recalculated after dynamic spawn |

**Target:** ~25 new tests. Running total: ~1279.

**Phase 7 exit criteria:**
- [ ] Mutable DAG: tasks inserted at runtime, dispatched correctly
- [ ] Dynamic team: agent spawns new agent via gate, output feeds downstream
- [ ] Knowledge graph: entities accumulate across 5+ runs
- [ ] Learning: system recommends better configs based on history
- [ ] Replay: dynamic tasks reconstructed from events
- [ ] ~1279 tests passing (+515 from V1.5 baseline)

---

## Phase 8: Specialization (Sprints 37–39)

**Exit criterion:** Fine-tuning export produces valid training data from 10+ workflows. Specialization shows measurable improvement. All docs updated.

### Sprint 37: Fine-Tuning Data Pipeline (Weeks 73–74)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/intelligence/finetune.py` | Fine-tuning data extraction and export |
| `agentos/cli/finetune.py` | `agentos finetune export` CLI command |
| `tests/unit/test_finetune.py` | Fine-tuning pipeline unit tests |

#### Fine-tuning exporter

```python
"""agentos/intelligence/finetune.py — Fine-tuning data pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from agentos.kernel.event_log import EventLog


class ExportFormat(StrEnum):
    ANTHROPIC = "anthropic"  # Anthropic fine-tuning JSONL format
    OPENAI = "openai"        # OpenAI fine-tuning JSONL format


@dataclass
class ExportFilter:
    """Filters for training data quality."""
    min_confidence: float = 0.7
    min_approval_rate: float = 0.8
    require_gate_approved: bool = True
    exclude_failed_tasks: bool = True
    max_entries: int = 10000


@dataclass
class TrainingEntry:
    """A single training example extracted from workflow history."""
    system_prompt: str
    task_description: str
    agent_output: str
    feedback: str = ""
    approved: bool = True
    workflow_id: str = ""
    task_id: str = ""


class FinetuneExporter:
    """Extracts approved TaskOutputs + feedback into fine-tuning datasets."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def extract(self, filters: ExportFilter | None = None) -> list[TrainingEntry]:
        """Extract training entries from workflow history."""
        filters = filters or ExportFilter()
        # Query completed workflows, extract task outputs with gate feedback
        ...

    def export(
        self,
        entries: list[TrainingEntry],
        output_path: Path,
        format: ExportFormat = ExportFormat.ANTHROPIC,
    ) -> int:
        """Export training entries to JSONL file. Returns count written."""
        ...
```

#### CLI command

```
agentos finetune export --format anthropic --output training.jsonl
agentos finetune export --min-confidence 0.8 --require-approved
agentos finetune stats                  # Show training data statistics
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_extract_approved_outputs` | Only gate-approved outputs extracted |
| `test_filter_min_confidence` | Low-confidence findings excluded |
| `test_filter_failed_tasks` | Failed task outputs excluded |
| `test_export_anthropic_format` | Output conforms to Anthropic JSONL spec |
| `test_export_openai_format` | Output conforms to OpenAI JSONL spec |
| `test_feedback_included` | Gate rejection feedback included in training entry |
| `test_system_prompt_preserved` | Agent role/system prompt captured in entry |
| `test_max_entries_limit` | Export respects max_entries filter |
| `test_cli_export` | CLI command produces valid JSONL file |
| `test_stats_command` | Stats show entry count, quality distribution |
| `test_empty_history` | Graceful handling when no workflows exist |

**Target:** ~25 new tests. Running total: ~1304.

---

### Sprint 38: Cross-Workflow Specialization (Weeks 75–76)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/intelligence/specialization.py` | Agent performance tracking + specialization scoring |
| `tests/unit/test_specialization.py` | Specialization unit tests |
| `tests/integration/test_specialization_e2e.py` | Specialization integration tests |

#### Specialization engine

```python
"""agentos/intelligence/specialization.py — Cross-workflow agent specialization."""
from __future__ import annotations

from dataclasses import dataclass, field

from agentos.kernel.event_log import EventLog


@dataclass
class RolePerformance:
    """An agent's performance in a specific role."""
    agent_backend: str  # e.g. "claude-sonnet-4-6", "gpt-4o"
    role: str           # e.g. "researcher", "code_reviewer", "analyst"
    total_tasks: int = 0
    succeeded: int = 0
    approval_rate: float = 0.0
    avg_cost_usd: float = 0.0
    avg_quality_score: float = 0.0
    specialization_score: float = 0.0  # 0.0–1.0, higher = better fit


@dataclass
class PromptRefinement:
    """A suggested system prompt improvement based on accumulated feedback."""
    original_prompt: str
    refined_prompt: str
    incorporated_feedback: list[str]
    expected_improvement: str


class SpecializationTracker:
    """Tracks agent performance per role across workflows."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def compute_scores(self) -> list[RolePerformance]:
        """Compute specialization scores for all agent-role pairs."""
        ...

    def best_agent_for_role(self, role: str) -> str | None:
        """Return the best-performing agent backend for a given role."""
        ...


class PromptRefiner:
    """Refines system prompts based on accumulated gate feedback."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def refine(self, agent_backend: str, role: str, current_prompt: str) -> PromptRefinement | None:
        """Suggest prompt improvements based on rejection feedback."""
        ...
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_performance_tracking` | Agent performance recorded per role |
| `test_specialization_score` | Score reflects success rate and quality |
| `test_best_agent_for_role` | Returns highest-scoring agent for a role |
| `test_no_data_returns_none` | No data → best_agent returns None |
| `test_prompt_refinement` | Feedback incorporated into refined prompt |
| `test_refinement_preserves_core` | Core instructions not lost in refinement |
| `test_multi_backend_comparison` | Different backends compared for same role |
| `test_cross_workflow_accumulation` | Scores accumulate across multiple workflows |
| `test_specialization_e2e` | 5 runs → scoring → recommendation → improved prompt |

**Target:** ~25 new tests. Running total: ~1329.

---

### Sprint 39: V3+ Polish & Documentation (Weeks 77–78)

#### Files to create/update

| File | Purpose |
|------|---------|
| `docs/ADAPTER_GUIDE_V2.md` | Updated adapter development guide |
| `docs/WORKFLOW_GUIDE_V2.md` | Updated workflow authoring guide (channels, dynamic DAG) |
| `docs/KNOWLEDGE_GUIDE.md` | Knowledge graph + cross-run memory guide |
| `docs/SECURITY_GUIDE_V2.md` | Updated security guide (sandbox, safety score) |
| `examples/channel_collaboration.yaml` | Channel-based workflow example |
| `examples/dynamic_team.yaml` | Dynamic team composition example |
| `examples/benchmarking.yaml` | Benchmark configuration example |
| `tests/e2e/test_specialization_e2e.py` | Full specialization E2E |
| `tests/e2e/test_finetune_e2e.py` | Fine-tuning pipeline E2E |

#### Vertical compliance package templates

```yaml
# examples/compliance/financial_services.yaml
name: financial_services_compliance
description: "SEC audit trail, data handling rules, investment approval workflows"
channels:
  market_data:
    mode: broadcast
agents:
  analyst:
    adapter: tier1
    budget: { max_cost_usd: 5.0 }
    capabilities:
      - type: "domain:sec.gov"
      - type: "path:workspace/research/**"
    sandbox: container
tasks:
  # Pre-configured for SEC compliance requirements
  ...

# examples/compliance/healthcare.yaml
# examples/compliance/legal.yaml
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_finetune_10_workflows` | Export from 10+ workflows produces valid JSONL |
| `test_specialization_improvement` | Refined prompt improves approval rate |
| `test_compliance_financial` | Financial services template validates correctly |
| `test_compliance_healthcare` | Healthcare template validates correctly |
| `test_compliance_legal` | Legal template validates correctly |
| `test_all_v1_scope_deferred_covered` | Every V1_SCOPE deferred feature implemented or scheduled |
| `test_documentation_completeness` | All new modules have guide coverage |

**Target:** ~20 new tests. Running total: ~1349.

**Phase 8 exit criteria:**
- [ ] Fine-tuning: export produces valid training data from 10+ workflows
- [ ] Specialization: measurable improvement in approval rate after refinement
- [ ] Compliance: financial, healthcare, and legal templates validate
- [ ] Docs: Adapter Guide v2, Workflow Guide v2, Knowledge Guide, Security Guide v2
- [ ] ~1349 tests passing (+585 from V1.5 baseline)

---

## Feature Traceability

Every deferred feature from V1_SCOPE.md and every "Future Discussion" item from PROJECT_OVERVIEW.md is placed in a specific sprint.

### V1_SCOPE.md Deferred Features

| Feature | Target Version | Sprint |
|---------|---------------|--------|
| Visual workflow builder | V2 | 25–26 |
| Non-technical user interface | V2 | 26 |
| Message channels / async communication | V2 | 18 |
| Manager agent for message routing | V2+ | 29 |
| Sandbox-level security (containers, seccomp) | V2 | 19 |
| Runtime-verified policy for Tier 2/3 agents | V2 | 21 |
| Dynamic team composition at runtime | V3 | 33 |
| Cross-run memory / persistent knowledge bases | V2+ | 24 |
| Knowledge graphs / advanced RAG | V3+ | 34 |
| Fine-tuning pipelines | V3+ | 37 |
| Agent Safety Score | V2 | 20 |
| Benchmarking engine | V2+ | 28 |
| Multi-user deployment | V2 | 23 |

### PROJECT_OVERVIEW.md Future Discussion Items

| Topic | Sprint(s) |
|-------|-----------|
| Context management and knowledge infrastructure | 24, 34 |
| Agent health, degradation, lifecycle | V1 Sprint 10 (done) |
| Agent performance benchmarking and economics | 28 |
| Agent Safety Score | 20 |
| Dynamic team composition at runtime | 32–33 |
| Cross-workflow agent specialization through fine-tuning | 37–38 |
| Deployment and multi-user access | 23 |
| Cross-run memory | 24 |
| Workflow-level learning | 35 |

### GTM_STRATEGY.md Commercial Products

| Product | Sprint |
|---------|--------|
| Agent Audit | 27 |
| Agent Marketplace | 30–31 |
| Agent Economics Dashboard (Benchmarking) | 28 |
| Vertical Compliance Packages | 39 |

---

## Running Test Count Summary

| Sprint | New Tests | Running Total | Phase |
|--------|-----------|---------------|-------|
| V1.5 baseline | — | 764 | — |
| 18 — Message Channels | ~30 | ~794 | Phase 4 |
| 19 — Sandbox Security | ~35 | ~829 | Phase 4 |
| 20 — Agent Safety Score | ~30 | ~859 | Phase 4 |
| 21 — Post-Hoc Verification | ~25 | ~884 | Phase 4 |
| 22 — Streaming & WebSocket | ~25 | ~909 | Phase 4 |
| 23 — Auth & Multi-User | ~30 | ~939 | Phase 5 |
| 24 — Cross-Run Memory | ~30 | ~969 | Phase 5 |
| 25 — Builder Backend | ~25 | ~994 | Phase 5 |
| 26 — Builder Frontend | ~25 | ~1019 | Phase 5 |
| 27 — Platform Integration & Audit | ~25 | ~1044 | Phase 5 |
| 28 — Benchmarking Engine | ~25 | ~1069 | Phase 6 |
| 29 — Manager Agent | ~25 | ~1094 | Phase 6 |
| 30 — Marketplace Backend | ~25 | ~1119 | Phase 6 |
| 31 — Marketplace Frontend | ~20 | ~1139 | Phase 6 |
| 32 — Mutable DAG | ~30 | ~1169 | Phase 7 |
| 33 — Dynamic Team Composition | ~30 | ~1199 | Phase 7 |
| 34 — Knowledge Graph | ~30 | ~1229 | Phase 7 |
| 35 — Workflow-Level Learning | ~25 | ~1254 | Phase 7 |
| 36 — V3 Integration | ~25 | ~1279 | Phase 7 |
| 37 — Fine-Tuning Pipeline | ~25 | ~1304 | Phase 8 |
| 38 — Cross-Workflow Specialization | ~25 | ~1329 | Phase 8 |
| 39 — V3+ Polish & Docs | ~20 | ~1349 | Phase 8 |

**Total new tests: ~585 | Final target: ~1349+**

---

## Risk Register (V2+)

### Risk 7: Frontend Complexity

**Severity:** Medium — visual builder is a significant frontend effort for a solo founder.

**Mitigation:** Builder backend (Sprint 25) is decoupled from frontend (Sprint 26). If frontend velocity is slow, the backend API works with CLI. Consider hiring frontend contractor for Sprint 26.

**Monitor:** If Sprint 26 takes >3 weeks, reduce scope to import/export only (no drag-and-drop).

### Risk 8: Sandbox Platform Dependencies

**Severity:** Medium — namespace isolation requires Linux, container isolation requires Docker.

**Mitigation:** SandboxLevel.NONE is always available. Tests for namespace/container isolation are marked `@pytest.mark.slow` and skipped in CI without Docker. macOS users get NONE + CONTAINER (Docker Desktop).

**Monitor:** If >30% of users are on macOS without Docker, prioritize NONE-level hardening.

### Risk 9: Knowledge Graph Relevance

**Severity:** Low-Medium — knowledge graph may return irrelevant entities, degrading agent performance.

**Mitigation:** Confidence decay removes stale knowledge. Query interface supports filtering by entity type and provenance. Agent can ignore injected context that is not relevant to current task.

**Monitor:** If agents perform worse with knowledge injection than without, disable injection and investigate retrieval quality.

### Risk 10: Dynamic DAG Complexity

**Severity:** High — mutable DAGs are architecturally complex and difficult to debug.

**Mitigation:** MutableDAG is a thin wrapper with threading.Lock. All mutations emit events. Replayer reconstructs full graph. Static verification still runs on initial DAG. Dynamic additions validated at insertion time.

**Monitor:** If concurrent insertion tests show race conditions after 2 weeks of debugging, simplify to single-threaded insertion with executor pause.

### Risk 11: Fine-Tuning Data Quality

**Severity:** Medium — garbage-in-garbage-out for fine-tuning datasets.

**Mitigation:** Export filters (min confidence, require gate approval) ensure quality. Stats command shows data quality distribution before export. Users review samples before fine-tuning.

**Monitor:** If <50% of exported entries pass manual review, tighten filters and investigate extraction logic.
