# AgentOS — V1 Development Plan

**Companion to:** PROJECT_OVERVIEW.md | V1_SCOPE.md | GTM_STRATEGY.md
**Date:** March 2026
**Status:** Pre-Development — Fresh Build

---

## Purpose

The Project Overview describes what AgentOS is. The V1 Scope defines what ships. The GTM Strategy defines how it reaches users. This document answers: **how do we build it, week by week, with concrete schemas, file paths, and test specifications?**

This is a fresh build. The V0 codebase (archived in `v0/`) provides pattern reference but no code is carried forward. Every module is designed and implemented from scratch.

---

## Repository Structure

```
AgentOS/
├── agentos/
│   ├── __init__.py
│   ├── kernel/                    # Core infrastructure
│   │   ├── __init__.py
│   │   ├── event_log.py           # EventLog ABC + SQLiteEventLog
│   │   ├── state_machine.py       # TaskStateMachine (event-derived)
│   │   ├── dag_executor.py        # DAG scheduler + executor
│   │   ├── budget_manager.py      # 5-dimension budget tracking
│   │   ├── workspace.py           # Scoped dirs, file tracking
│   │   ├── gate_manager.py        # Approval gates + input gates
│   │   ├── lifecycle.py           # Agent spawn/stop/restart
│   │   └── seq.py                 # Global sequence counter (fixes V0 sync issue)
│   ├── adapters/                  # Agent adapters by tier
│   │   ├── __init__.py
│   │   ├── base.py                # AgentAdapter ABC
│   │   ├── tier1.py               # API-controlled tool-calling loop
│   │   └── tier2_claude_code.py   # Claude Code CLI integration
│   ├── security/                  # Capability enforcement
│   │   ├── __init__.py
│   │   ├── capabilities.py        # Capability model + policy
│   │   ├── enforcer.py            # Tool call interception (Tier 1)
│   │   └── secrets.py             # Credential store
│   ├── cli/                       # Click-based CLI
│   │   ├── __init__.py
│   │   ├── main.py                # CLI entry point
│   │   ├── workflow.py            # workflow run/verify commands
│   │   ├── status.py              # status/events/cost commands
│   │   └── gate.py                # gate list/approve/reject
│   ├── schemas/                   # All Pydantic v2 models
│   │   ├── __init__.py
│   │   ├── events.py              # Event envelope + all event types
│   │   ├── task.py                # TaskState, TaskConfig, TaskOutput
│   │   ├── workflow.py            # WorkflowDefinition (parsed YAML)
│   │   ├── budget.py              # BudgetSpec, BudgetUsage, BudgetDelta
│   │   ├── agent.py               # AgentConfig, AdapterTier
│   │   ├── gate.py                # GateConfig, GateResolution
│   │   ├── capability.py          # CapabilityGrant, CapabilityPolicy
│   │   └── workspace.py           # WorkspaceConfig, FileManifestEntry
│   └── validation/                # Pre-execution checks
│       ├── __init__.py
│       ├── workflow_verifier.py   # Static DAG analysis
│       └── adversarial.py         # Adversarial validation node logic
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (in-memory event log, etc.)
│   ├── unit/
│   │   └── ...                    # One test file per module
│   ├── integration/
│   │   └── ...                    # Cross-module integration tests
│   └── e2e/
│       └── ...                    # End-to-end workflow tests
├── examples/
│   ├── linear_research.yaml       # Research → gate → implement
│   ├── parallel_analysis.yaml     # Two agents → merge
│   └── fanout_with_gate.yaml      # One → three parallel → gate → merge
├── docs/
│   ├── PROJECT_OVERVIEW.md
│   ├── V1_SCOPE.md
│   ├── GTM_STRATEGY.md
│   ├── DEVELOPMENT_PLAN.md        # This document
│   └── suggested_dev_plan.md      # Reference from feedback team
├── v0/                            # Archived V0 codebase (reference only)
├── pyproject.toml
├── CLAUDE.md
└── .gitignore
```

**Package config** (`pyproject.toml`):

```toml
[project]
name = "agentos"
version = "1.0.0-dev"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "click>=8.0",
    "anthropic>=0.40",     # Tier 1 adapter (Claude API)
    "openai>=1.0",         # Tier 1 adapter (OpenAI API) — optional
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov", "ruff", "mypy"]

[project.scripts]
agentos = "agentos.cli.main:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration", "e2e", "slow"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

---

## Week 0: Pre-Development Spikes (Days 1–5)

Three spikes must be completed before committing to the 6-month plan. These are questions to answer, not features to build.

### Spike 1: Claude Code CLI Integration Surface

**Goal:** Determine if Claude Code can be orchestrated programmatically.

**Test script** (run 10 times, document results):

```python
"""spike_claude_code.py — Week 0 integration surface test."""
import subprocess
import json
import time
from pathlib import Path

TASK = "Create a file called hello.py that prints 'Hello from AgentOS test'"
WORKSPACE = Path("/tmp/agentos_spike")

def run_claude_code_test(run_id: int) -> dict:
    """Launch Claude Code with a task, capture output, measure behavior."""
    workspace = WORKSPACE / f"run_{run_id}"
    workspace.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    result = subprocess.run(
        ["claude", "--print", "--output-format", "json",
         "--allowedTools", "Write,Read",
         TASK],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.monotonic() - start

    files_produced = list(workspace.rglob("*"))
    return {
        "run_id": run_id,
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "stdout_length": len(result.stdout),
        "stderr_length": len(result.stderr),
        "files_produced": [str(f.relative_to(workspace)) for f in files_produced if f.is_file()],
        "success": result.returncode == 0 and any(f.name == "hello.py" for f in files_produced),
    }

if __name__ == "__main__":
    results = [run_claude_code_test(i) for i in range(10)]
    successes = sum(1 for r in results if r["success"])
    print(json.dumps(results, indent=2))
    print(f"\n{successes}/10 successful runs")
```

**Questions to answer:**

| Question | How to test |
|----------|-------------|
| Headless launch? | `claude --print` flag, no TTY |
| Task input without prompt? | Pass task as positional arg |
| Capture structured output? | `--output-format json` flag |
| Monitor token consumption? | Parse JSON output for usage metrics |
| Programmatic termination? | `subprocess.terminate()` + check file integrity |
| Consistent across 10 runs? | Compare results array |
| Rate limits / restrictions? | Note any 429s or auth failures |

**Decision gate:**
- **8+/10 succeed** → Proceed with Tier 2 Claude Code adapter (Phase 2, weeks 9-10)
- **6-7/10** → Proceed cautiously; allocate extra time in weeks 9-10 for reliability work
- **<6/10** → Activate contingency: Tier 1 API fallback for demo, investigate Codex for Tier 2

### Spike 2: Task Output Schema v0.1

**Goal:** Produce a concrete Pydantic schema that every component codes against.

```python
"""agentos/schemas/task.py — Task output protocol v0.1"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING = "waiting"  # Blocked on gate or input


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    """A single finding produced by an agent."""
    finding: str = Field(description="What was found or concluded")
    confidence: Confidence = Field(description="Agent's confidence in this finding")
    sources: list[str] = Field(default_factory=list, description="URLs, file paths, or references")


class FileReference(BaseModel):
    """A file produced or modified by the task."""
    path: str = Field(description="Path relative to workspace root")
    description: str = Field(description="What this file contains or why it was created")
    role: str = Field(default="primary", description="primary | supporting | log")


class TaskOutput(BaseModel):
    """Structured output manifest produced by every task.

    Tier 1: enforced via JSON mode / tool use.
    Tier 2: agent instructed to write this as manifest.json; validated post-hoc.
    """
    schema_version: str = Field(default="0.1", description="Output schema version")
    task_id: str
    agent_id: str
    status: TaskStatus
    summary: str = Field(description="1-3 sentence summary of what was accomplished")
    key_findings: list[Finding] = Field(default_factory=list)
    files_produced: list[FileReference] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list,
        description="Unresolved questions for downstream agents or human review",
    )
    metrics: TaskMetrics | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class TaskMetrics(BaseModel):
    """Resource consumption metrics for a completed task."""
    tokens_consumed: int = 0
    api_calls_made: int = 0
    execution_time_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
```

**Validation:** Create a test that generates a `TaskOutput`, serializes to JSON, deserializes, and asserts round-trip fidelity. Write 3 example outputs covering: a research task, a code implementation task, and a failed task.

### Spike 3: Event Schema Design

**Goal:** Design the event envelope and all V1 event types as Pydantic models, plus the SQLite DDL.

**Event envelope:**

```python
"""agentos/schemas/events.py — Event log schema v0.1"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())

def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventType(StrEnum):
    """All V1 event types. Grouped by subsystem."""

    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"

    # Task lifecycle
    TASK_STATE_CHANGED = "task.state_changed"
    TASK_OUTPUT_PRODUCED = "task.output_produced"

    # Agent lifecycle
    AGENT_SPAWNED = "agent.spawned"
    AGENT_TERMINATED = "agent.terminated"

    # Gates
    GATE_WAITING = "gate.waiting"
    GATE_RESOLVED = "gate.resolved"

    # Budget
    BUDGET_CONSUMED = "budget.consumed"
    BUDGET_EXCEEDED = "budget.exceeded"

    # Workspace / files
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"

    # Security
    CAPABILITY_GRANTED = "capability.granted"
    CAPABILITY_DENIED = "capability.denied"

    # Errors
    ERROR_OCCURRED = "error.occurred"


class Event(BaseModel):
    """Immutable event in the append-only log.

    Every event has a common envelope. Type-specific data lives in `payload`.
    The `metadata` field provides extensibility without schema changes.
    """
    event_id: str = Field(default_factory=_uuid, description="Unique event ID (UUID)")
    event_type: EventType
    workflow_id: str = Field(description="Workflow this event belongs to")
    seq: int = Field(ge=0, description="Monotonic sequence within the workflow")
    timestamp: datetime = Field(default_factory=_utc_now)
    schema_version: str = Field(default="0.1")
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible key-value pairs for future features",
    )
```

**SQLite DDL:**

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    workflow_id  TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    timestamp    TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '0.1',
    payload      TEXT NOT NULL DEFAULT '{}',  -- JSON
    metadata     TEXT NOT NULL DEFAULT '{}',  -- JSON
    UNIQUE(workflow_id, seq)
);

CREATE INDEX idx_events_workflow ON events(workflow_id);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp);
```

**V1 event payload specifications:**

| Event Type | Payload Fields | Example |
|---|---|---|
| `workflow.started` | `workflow_name`, `config_hash`, `task_count` | `{"workflow_name": "research_pipeline", "config_hash": "a1b2c3", "task_count": 3}` |
| `workflow.completed` | `status` ("succeeded"/"failed"), `duration_seconds`, `total_cost_usd` | `{"status": "succeeded", "duration_seconds": 142.5, "total_cost_usd": 0.34}` |
| `task.state_changed` | `task_id`, `task_name`, `from_state`, `to_state`, `agent_id` (nullable) | `{"task_id": "t1", "from_state": "pending", "to_state": "running", "agent_id": "a1"}` |
| `task.output_produced` | `task_id`, `agent_id`, `output_path` (manifest file), `output_hash` | `{"task_id": "t1", "agent_id": "a1", "output_path": "workspace/t1/manifest.json"}` |
| `agent.spawned` | `agent_id`, `agent_name`, `adapter_tier` (1/2/3), `config_hash` | `{"agent_id": "a1", "adapter_tier": 1, "agent_name": "researcher"}` |
| `agent.terminated` | `agent_id`, `reason` ("completed"/"budget"/"error"/"manual"), `metrics` | `{"agent_id": "a1", "reason": "completed", "metrics": {"tokens": 4200}}` |
| `gate.waiting` | `gate_id`, `task_id`, `gate_type` ("approval"/"input"), `output_summary` | `{"gate_id": "g1", "task_id": "t1", "gate_type": "approval"}` |
| `gate.resolved` | `gate_id`, `resolution` ("approved"/"rejected"/"edited"), `reviewer`, `feedback` | `{"gate_id": "g1", "resolution": "approved", "reviewer": "user"}` |
| `budget.consumed` | `agent_id`, `resource` ("tokens"/"api_calls"/"time"/"cost"), `amount`, `cumulative`, `limit` | `{"agent_id": "a1", "resource": "tokens", "amount": 500, "cumulative": 2100, "limit": 10000}` |
| `budget.exceeded` | `agent_id`, `resource`, `limit`, `attempted` | `{"agent_id": "a1", "resource": "tokens", "limit": 10000, "attempted": 10350}` |
| `file.created` | `path`, `agent_id`, `task_id`, `size_bytes` | `{"path": "research/findings.md", "agent_id": "a1", "task_id": "t1", "size_bytes": 2048}` |
| `file.modified` | `path`, `agent_id`, `task_id`, `size_bytes` | `{"path": "src/main.py", "agent_id": "a2", "task_id": "t2", "size_bytes": 4096}` |
| `capability.granted` | `agent_id`, `capability` ("tool:web_search", "path:/workspace/src/*"), `scope` | `{"agent_id": "a1", "capability": "tool:web_search"}` |
| `capability.denied` | `agent_id`, `capability`, `reason` | `{"agent_id": "a1", "capability": "tool:shell_exec", "reason": "not in allowlist"}` |
| `error.occurred` | `source`, `error_type`, `message`, `recoverable` | `{"source": "agent.a1", "error_type": "timeout", "recoverable": true}` |

**Week 0 exit gate:** Review the event schema and task output schema together. Confirm that `task.output_produced` references the task output schema consistently. Confirm no gaps that would force a redesign.

---

## Sequence Counter Design

V0 had error-prone manual `set_seq()` calls between executor and budget manager. V1 fixes this with a shared, thread-safe counter:

```python
"""agentos/kernel/seq.py — Thread-safe monotonic sequence counter."""
from __future__ import annotations

import threading


class SeqCounter:
    """Shared monotonic sequence counter for a workflow execution.

    Passed to all components (executor, budget manager, gate manager).
    Each call to next() returns a unique, monotonically increasing integer.
    Thread-safe for parallel task execution.
    """

    def __init__(self, start: int = 0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            seq = self._value
            self._value += 1
            return seq

    @property
    def current(self) -> int:
        return self._value
```

Every component receives a reference to the same `SeqCounter` instance. No manual sync needed.

---

## Phase 1: Foundation (Weeks 1–8)

**Exit criterion:** A working Tier 1 demo — two API-based agents collaborating through the DAG executor with an approval gate, event logging, and budget enforcement.

### Sprint 1: Event Log + Task State Machine (Weeks 1–2)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/event_log.py` | `EventLog` ABC + `SQLiteEventLog` implementation |
| `agentos/kernel/state_machine.py` | `TaskStateMachine` — derives state from events |
| `agentos/kernel/seq.py` | `SeqCounter` (shared monotonic counter) |
| `agentos/schemas/events.py` | `Event` model + `EventType` enum (from spike 3) |
| `agentos/schemas/task.py` | `TaskStatus`, `TaskOutput`, `TaskConfig` (from spike 2) |
| `tests/conftest.py` | Shared fixtures |
| `tests/unit/test_event_log.py` | Event log tests |
| `tests/unit/test_state_machine.py` | State machine tests |
| `tests/unit/test_seq.py` | Sequence counter tests |
| `tests/unit/test_schemas.py` | Schema serialization round-trip tests |

#### EventLog interface

```python
"""agentos/kernel/event_log.py"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from agentos.schemas.events import Event, EventType


class EventLog(ABC):
    """Abstract append-only event log."""

    @abstractmethod
    def append(self, event: Event) -> None:
        """Append an event. Must preserve ordering within workflow_id."""

    @abstractmethod
    def query(
        self,
        workflow_id: str | None = None,
        event_type: EventType | None = None,
        since_seq: int | None = None,
    ) -> list[Event]:
        """Query events with optional filters."""

    @abstractmethod
    def replay(self, workflow_id: str) -> list[Event]:
        """Return all events for a workflow, ordered by seq."""

    @abstractmethod
    def last_seq(self, workflow_id: str) -> int:
        """Return the highest seq for a workflow, or -1 if none."""


class SQLiteEventLog(EventLog):
    """SQLite-backed event log with WAL mode for concurrent reads."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                schema_version TEXT NOT NULL DEFAULT '0.1',
                payload TEXT NOT NULL DEFAULT '{}',
                metadata TEXT NOT NULL DEFAULT '{}',
                UNIQUE(workflow_id, seq)
            );
            CREATE INDEX IF NOT EXISTS idx_events_workflow ON events(workflow_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        """)
        self._conn.commit()

    # ... append, query, replay, last_seq implementations
```

#### TaskStateMachine — event-derived (fixes V0 mutable state)

```python
"""agentos/kernel/state_machine.py"""
from __future__ import annotations

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskStatus


# Valid state transitions
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.WAITING},
    TaskStatus.WAITING: {TaskStatus.RUNNING},  # Resume after gate
    # SUCCEEDED and FAILED are terminal
}


class TaskStateMachine:
    """Manages task state transitions via events.

    State is NEVER stored as a mutable field on the task.
    It is always derived from the event log. This class emits
    state change events and provides a query method to derive
    current state from events.
    """

    def __init__(self, event_log: EventLog, seq: SeqCounter, workflow_id: str) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

    def transition(self, task_id: str, from_state: TaskStatus, to_state: TaskStatus,
                   agent_id: str | None = None) -> None:
        """Emit a state transition event. Raises ValueError on invalid transition."""
        if to_state not in VALID_TRANSITIONS.get(from_state, set()):
            raise ValueError(f"Invalid transition: {from_state} → {to_state}")

        self._event_log.append(Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": task_id,
                "task_name": task_id,  # Name can be enriched later
                "from_state": from_state.value,
                "to_state": to_state.value,
                "agent_id": agent_id,
            },
        ))

    def get_state(self, task_id: str) -> TaskStatus:
        """Derive current task state from events."""
        events = self._event_log.query(
            workflow_id=self._workflow_id,
            event_type=EventType.TASK_STATE_CHANGED,
        )
        state = TaskStatus.PENDING
        for event in events:
            if event.payload.get("task_id") == task_id:
                state = TaskStatus(event.payload["to_state"])
        return state
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_append_and_replay` | Events appended in order, replay returns them sorted by seq |
| `test_workflow_isolation` | Events for workflow A don't appear in workflow B queries |
| `test_append_only_guarantee` | No update/delete operations succeed on the events table |
| `test_concurrent_appends` | 10 threads appending simultaneously, all events present, no seq collision |
| `test_valid_transitions` | PENDING→RUNNING→SUCCEEDED, RUNNING→WAITING→RUNNING→SUCCEEDED |
| `test_invalid_transitions` | PENDING→SUCCEEDED raises ValueError, FAILED→RUNNING raises ValueError |
| `test_state_derived_from_events` | `get_state()` returns correct state after sequence of transitions |
| `test_seq_counter_thread_safety` | 100 threads calling `next()`, all values unique and monotonic |
| `test_schema_round_trip` | Event → JSON → Event preserves all fields |
| `test_task_output_round_trip` | TaskOutput → JSON → TaskOutput preserves all fields |

**Target:** ~35-45 tests passing.

---

### Sprint 2: DAG Executor + Budget Manager (Weeks 3–4)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/schemas/workflow.py` | `WorkflowDefinition`, `NodeConfig`, `EdgeConfig` |
| `agentos/schemas/budget.py` | `BudgetSpec`, `BudgetUsage`, `BudgetDelta` |
| `agentos/schemas/agent.py` | `AgentConfig`, `AdapterTier` |
| `agentos/kernel/dag_executor.py` | DAG parser, topological sort, executor with thread pool |
| `agentos/kernel/budget_manager.py` | 5-dimension tracking, hard enforcement |
| `tests/unit/test_dag_executor.py` | DAG execution tests |
| `tests/unit/test_budget_manager.py` | Budget enforcement tests |
| `tests/unit/test_workflow_schema.py` | YAML parsing tests |

#### Workflow YAML format

This is the format users write. Designed before building the parser.

```yaml
# examples/linear_research.yaml — Research → Gate → Implement
name: research_and_implement
version: "1.0"

budget:
  max_tokens: 50000
  max_cost_usd: 2.00
  max_time_seconds: 600

agents:
  researcher:
    adapter: tier1
    model: claude-sonnet-4-6
    role: >
      You are a research analyst. Investigate the given topic thoroughly.
      Produce a structured manifest.json with your findings.
    tools: [web_search, file_read, file_write]
    budget:
      max_tokens: 25000
      max_cost_usd: 1.00

  implementer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: >
      You are a software engineer. Based on the research provided,
      implement the solution. Write clean, tested code.
    tools: [file_read, file_write, shell_exec]
    budget:
      max_tokens: 25000
      max_cost_usd: 1.00

tasks:
  research:
    agent: researcher
    description: >
      Research the requirements for a Python CLI tool that converts
      CSV files to JSON. Identify edge cases and best practices.
    workspace: shared

  review_gate:
    type: approval_gate
    depends_on: [research]
    prompt: "Review the research findings before implementation begins."

  implement:
    agent: implementer
    description: >
      Implement the CSV-to-JSON converter based on the approved research.
    depends_on: [review_gate]
    workspace: shared
```

```yaml
# examples/parallel_analysis.yaml — Two agents simultaneously → merge
name: parallel_analysis
version: "1.0"

budget:
  max_tokens: 80000
  max_cost_usd: 3.00
  max_time_seconds: 900

agents:
  analyst_a:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Analyze the technical feasibility of the proposed solution."
    tools: [web_search, file_read, file_write]
    budget: { max_tokens: 30000 }

  analyst_b:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Analyze the market viability and competitive landscape."
    tools: [web_search, file_read, file_write]
    budget: { max_tokens: 30000 }

  synthesizer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Synthesize the technical and market analyses into a recommendation."
    tools: [file_read, file_write]
    budget: { max_tokens: 20000 }

tasks:
  tech_analysis:
    agent: analyst_a
    description: "Assess technical feasibility, identify risks and dependencies."
    workspace: shared

  market_analysis:
    agent: analyst_b
    description: "Assess market size, competition, and go-to-market viability."
    workspace: shared

  synthesis:
    agent: synthesizer
    description: "Combine both analyses into a single investment recommendation."
    depends_on: [tech_analysis, market_analysis]
    workspace: shared
```

```yaml
# examples/fanout_with_gate.yaml — One → three parallel → gate → merge
name: fanout_review
version: "1.0"

budget:
  max_tokens: 120000
  max_cost_usd: 5.00

agents:
  planner:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Break down the project into implementation tasks."
    tools: [file_read, file_write]
    budget: { max_tokens: 15000 }

  dev_a:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Implement the data layer."
    tools: [file_read, file_write, shell_exec]
    budget: { max_tokens: 30000 }

  dev_b:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Implement the API layer."
    tools: [file_read, file_write, shell_exec]
    budget: { max_tokens: 30000 }

  dev_c:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Implement the CLI interface."
    tools: [file_read, file_write, shell_exec]
    budget: { max_tokens: 30000 }

  integrator:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Integrate all components and run final tests."
    tools: [file_read, file_write, shell_exec]
    budget: { max_tokens: 15000 }

tasks:
  plan:
    agent: planner
    description: "Create an implementation plan with clear task boundaries."
    workspace: shared

  data_layer:
    agent: dev_a
    description: "Implement data models and database layer per the plan."
    depends_on: [plan]
    workspace: shared

  api_layer:
    agent: dev_b
    description: "Implement REST API endpoints per the plan."
    depends_on: [plan]
    workspace: shared

  cli_layer:
    agent: dev_c
    description: "Implement CLI commands per the plan."
    depends_on: [plan]
    workspace: shared

  review_gate:
    type: approval_gate
    depends_on: [data_layer, api_layer, cli_layer]
    prompt: "Review all three implementations before integration."

  integration:
    agent: integrator
    description: "Wire components together, fix integration issues, run tests."
    depends_on: [review_gate]
    workspace: shared
```

#### WorkflowDefinition schema (parsed from YAML)

```python
"""agentos/schemas/workflow.py"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec
from agentos.schemas.agent import AgentConfig


class TaskConfig(BaseModel):
    """A single task (node) in the workflow DAG."""
    name: str = Field(description="Unique task identifier within the workflow")
    agent: str | None = Field(default=None, description="Agent name (null for gates)")
    type: str = Field(default="agent_task", description="agent_task | approval_gate | input_gate")
    description: str = Field(default="")
    depends_on: list[str] = Field(default_factory=list)
    workspace: str = Field(default="shared")
    prompt: str = Field(default="", description="Gate prompt for approval/input gates")


class WorkflowDefinition(BaseModel):
    """Complete workflow parsed from YAML."""
    name: str
    version: str = "1.0"
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    tasks: dict[str, TaskConfig] = Field(default_factory=dict)
```

```python
"""agentos/schemas/budget.py"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetSpec(BaseModel):
    """Resource limits. None means unlimited for that dimension."""
    max_tokens: int | None = None
    max_api_calls: int | None = None
    max_time_seconds: float | None = None
    max_cost_usd: float | None = None
    max_concurrent_tasks: int = Field(default=4, ge=1)


class BudgetUsage(BaseModel):
    """Accumulated resource usage."""
    tokens_used: int = 0
    api_calls_made: int = 0
    time_elapsed_seconds: float = 0.0
    cost_usd: float = 0.0


class BudgetDelta(BaseModel):
    """Incremental usage from a single operation."""
    tokens: int = 0
    api_calls: int = 0
    time_seconds: float = 0.0
    cost_usd: float = 0.0
```

```python
"""agentos/schemas/agent.py"""
from __future__ import annotations

from enum import IntEnum
from pydantic import BaseModel, Field

from agentos.schemas.budget import BudgetSpec


class AdapterTier(IntEnum):
    TIER1 = 1  # Fully controlled
    TIER2 = 2  # Semi-controlled
    TIER3 = 3  # Best-effort


class AgentConfig(BaseModel):
    """Configuration for a single agent."""
    adapter: str = Field(default="tier1", description="tier1 | tier2_claude_code")
    model: str = Field(default="claude-sonnet-4-6")
    role: str = Field(default="", description="System prompt / role description")
    tools: list[str] = Field(default_factory=list, description="Tool allowlist")
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
```

#### DAG Executor design

```python
"""agentos/kernel/dag_executor.py — core logic outline"""

class DAGExecutor:
    """Executes a workflow DAG with topological scheduling.

    Responsibilities:
    - Parse WorkflowDefinition into execution graph
    - Topological sort (Kahn's algorithm)
    - Dispatch tasks to thread pool respecting concurrency limits
    - Handle task completion → update dependencies → dispatch next ready tasks
    - On gate: pause execution, wait for resolution
    - On failure: mark dependent tasks as blocked
    - All state changes go through TaskStateMachine (emitting events)
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        event_log: EventLog,
        seq: SeqCounter,
        budget_manager: BudgetManager,
        adapter_registry: dict[str, AgentAdapter],
    ) -> None: ...

    def run(self, workflow_id: str) -> WorkflowResult: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
```

#### BudgetManager design (event-sourced, uses shared SeqCounter)

```python
"""agentos/kernel/budget_manager.py — core logic outline"""

class BudgetManager:
    """Tracks resource usage and enforces hard limits.

    Uses shared SeqCounter (no manual set_seq needed).
    State is event-sourced: can be reconstructed from budget events.
    """

    def __init__(
        self,
        spec: BudgetSpec,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None: ...

    def check(self, agent_id: str) -> None:
        """Check limits. Raises BudgetExceededError if any exceeded."""

    def apply(self, agent_id: str, delta: BudgetDelta) -> None:
        """Apply usage delta, emit budget.consumed event, then check limits."""

    def usage_for(self, agent_id: str) -> BudgetUsage:
        """Return accumulated usage for a specific agent."""

    @property
    def total_usage(self) -> BudgetUsage:
        """Return workflow-level accumulated usage."""
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_linear_execution` | A → B → C executes in order, all events emitted |
| `test_parallel_execution` | A and B run concurrently (verify overlapping timestamps) |
| `test_fanout_fanin` | A → (B, C, D) → E, E waits for all three |
| `test_cycle_detection` | Circular dependency raises error before execution |
| `test_missing_dependency` | Task depending on non-existent task raises error |
| `test_task_failure_blocks_dependents` | When B fails, C (depends on B) is not started |
| `test_concurrency_limit` | With limit=2, at most 2 tasks run simultaneously |
| `test_yaml_parse_linear` | Parse linear_research.yaml correctly |
| `test_yaml_parse_parallel` | Parse parallel_analysis.yaml correctly |
| `test_yaml_parse_fanout` | Parse fanout_with_gate.yaml correctly |
| `test_budget_hard_enforcement` | Exceeding token limit stops execution cleanly |
| `test_budget_per_agent` | Agent A's usage doesn't count against Agent B's limit |
| `test_budget_workflow_level` | Workflow-level limit enforced across all agents |
| `test_budget_event_sourced` | Reconstruct BudgetUsage from events matches live tracking |
| `test_budget_multiple_dimensions` | Enforce tokens AND cost simultaneously |

**Target:** ~50-60 new tests. Running total: ~85-105.

---

### Sprint 3: Workspace + Tier 1 Adapter (Weeks 5–6)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/workspace.py` | Scoped workspace with file tracking |
| `agentos/schemas/workspace.py` | `WorkspaceConfig`, `FileManifestEntry` |
| `agentos/adapters/base.py` | `AgentAdapter` ABC |
| `agentos/adapters/tier1.py` | API-controlled agent with tool loop |
| `tests/unit/test_workspace.py` | Workspace tests |
| `tests/unit/test_tier1_adapter.py` | Tier 1 adapter tests |
| `tests/integration/test_tier1_workflow.py` | End-to-end Tier 1 workflow |

#### Workspace schema

```python
"""agentos/schemas/workspace.py"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class WorkspaceConfig(BaseModel):
    """Configuration for a scoped workspace."""
    root: str = Field(description="Root directory path")
    allowed_patterns: list[str] = Field(default_factory=lambda: ["**"])
    read_only: bool = False


class FileManifestEntry(BaseModel):
    """Record of a file operation within a workspace."""
    path: str
    operation: str  # "created" | "modified" | "deleted"
    agent_id: str
    task_id: str
    size_bytes: int
    timestamp: datetime
```

#### AgentAdapter ABC

```python
"""agentos/adapters/base.py"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agentos.schemas.task import TaskOutput


class AgentAdapter(ABC):
    """Abstract base for all agent adapters.

    Tier 1: AgentOS controls the tool-calling loop.
    Tier 2: AgentOS monitors from outside the loop.
    """

    @property
    @abstractmethod
    def tier(self) -> int:
        """Adapter tier (1, 2, or 3)."""

    @abstractmethod
    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Execute a task and return structured output.

        Tier 1: Output is enforced via JSON mode.
        Tier 2: Output is parsed from manifest.json in workspace.
        """

    @abstractmethod
    async def terminate(self) -> None:
        """Stop the agent cleanly."""
```

#### Test specifications

| Test | What it verifies |
|------|-----------------|
| `test_workspace_path_containment` | Paths outside root are rejected |
| `test_workspace_file_tracking` | File create/modify emits events |
| `test_workspace_manifest_query` | Query files by task_id returns correct set |
| `test_workspace_read_only` | Write operations blocked in read-only mode |
| `test_tier1_execute_returns_task_output` | Adapter returns valid TaskOutput |
| `test_tier1_budget_enforcement` | Adapter stops when budget exceeded |
| `test_tier1_tool_allowlist` | Only allowed tools are passed to the model |
| `test_tier1_predecessor_context` | Predecessor TaskOutputs injected into prompt |
| `test_tier1_structured_output` | Output conforms to TaskOutput schema |

**Target:** ~35-45 new tests. Running total: ~120-150.

---

### Sprint 4: Gates + CLI + Internal Demo (Weeks 7–8)

#### Files to create

| File | Purpose |
|------|---------|
| `agentos/kernel/gate_manager.py` | Gate lifecycle management |
| `agentos/schemas/gate.py` | `GateConfig`, `GateResolution` |
| `agentos/cli/main.py` | CLI entry point with Click |
| `agentos/cli/workflow.py` | `workflow run`, `workflow verify` |
| `agentos/cli/status.py` | `status`, `events`, `cost` |
| `agentos/cli/gate.py` | `gate list`, `gate approve`, `gate reject` |
| `tests/unit/test_gate_manager.py` | Gate tests |
| `tests/unit/test_cli.py` | CLI command tests |
| `tests/e2e/test_tier1_demo.py` | Internal demo (10 runs) |

#### Gate schema

```python
"""agentos/schemas/gate.py"""
from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, Field


class GateType(StrEnum):
    APPROVAL = "approval"
    INPUT = "input"


class GateResolution(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class GateState(BaseModel):
    """Current state of a gate."""
    gate_id: str
    task_id: str
    gate_type: GateType
    prompt: str = ""
    pending: bool = True
    resolution: GateResolution | None = None
    feedback: str | None = None
    reviewer: str | None = None
```

#### CLI commands

```
agentos workflow run <file>              # Run workflow from YAML
agentos workflow verify <file>           # Static verification
agentos status                           # Current workflow state
agentos events [--follow] [--type TYPE]  # Event stream
agentos cost [--agent AGENT]             # Budget consumption
agentos gate list                        # Pending gates
agentos gate approve <gate-id>           # Approve gate
agentos gate reject <gate-id> [--feedback TEXT]  # Reject gate
agentos agent restart <agent-id>         # Fresh restart
```

#### Phase 1 exit criteria

- [ ] Event log stores/retrieves events correctly (append-only, thread-safe)
- [ ] Task state machine handles all valid transitions, rejects invalid ones
- [ ] DAG executor handles linear, parallel, and fan-out/fan-in patterns
- [ ] Budget manager enforces hard limits across 5 dimensions
- [ ] Workspace tracks file changes and emits events
- [ ] Tier 1 adapter executes tasks with structured output
- [ ] Approval gates pause/resume workflows correctly
- [ ] CLI provides full visibility into workflow state, events, costs
- [ ] Internal Tier 1 demo completes 10/10 times
- [ ] ~170-200 tests passing, 90%+ coverage on kernel/ and schemas/

---

## Phase 2: Agent Integration and Hardening (Weeks 9–16)

**Exit criterion:** Public demo — two Claude Code instances (or Tier 1 fallback) collaborating through AgentOS with full governance. Demo video recorded.

### Sprint 5: Tier 2 Adapter (Weeks 9–10)

**If spike 1 succeeded:** Build production-grade Claude Code adapter.
**If spike 1 failed:** Use Tier 1 API fallback + investigate Codex.

#### Tier 2 Claude Code adapter design

```python
"""agentos/adapters/tier2_claude_code.py — core logic outline"""

class ClaudeCodeAdapter(AgentAdapter):
    """Tier 2 adapter for Claude Code CLI.

    Launches Claude Code as subprocess, monitors from outside the tool loop.
    AgentOS does NOT intercept individual tool calls.

    Enforcement model:
    - Task assignment: only assigned tasks, structured prompt
    - Workspace scoping: Claude Code runs in scoped directory
    - Budget: monitor token usage from output, enforce time limits
    - Output: instruct agent to produce manifest.json, validate post-hoc
    """

    tier = 2

    async def execute_task(self, ...) -> TaskOutput:
        # 1. Prepare workspace with predecessor context files
        # 2. Construct prompt: role + task + "produce manifest.json"
        # 3. Launch: subprocess.run(["claude", "--print", ...])
        # 4. Monitor: parse output for metrics
        # 5. Validate: read manifest.json, validate against TaskOutput schema
        # 6. If invalid: retry (up to 2 attempts), then human gate
        # 7. Return validated TaskOutput
        ...
```

**Target:** ~40-50 new tests. Running total: ~210-250.

### Sprint 6: Structured Handoffs + Workflow Verification (Weeks 11–12)

#### Workflow verifier checks

```python
"""agentos/validation/workflow_verifier.py — core logic outline"""

class WorkflowVerifier:
    """Static analysis of workflow DAGs before execution.

    Checks:
    1. No circular dependencies (cycle detection)
    2. All depends_on references exist (orphan dependencies)
    3. All task.agent references exist in agents section
    4. Agent tools are sufficient for task requirements (when inferable)
    5. Budget allocations sum correctly (per-agent <= workflow total)
    6. Gates exist at configured critical points
    7. No unreachable tasks (tasks with no path from any root)
    """

    def verify(self, workflow: WorkflowDefinition) -> VerificationReport: ...


class VerificationReport(BaseModel):
    valid: bool
    errors: list[VerificationError] = []
    warnings: list[VerificationWarning] = []
```

**Target:** ~50-60 new tests. Running total: ~260-310.

### Sprint 7: CLI Completion + Integration Testing (Weeks 13–14)

- Polish all CLI commands
- Comprehensive integration tests: both Tier 1 and Tier 2 workflows end-to-end
- Budget enforcement under stress (gradual approach, sudden spike, exact limit)
- Failure recovery (agent crash, timeout, API rate limit)
- Gate resolution via both CLI and programmatic API

**Target:** ~30-40 new tests. Running total: ~290-350.

### Sprint 8: Public Demo + Video (Weeks 15–16)

- Build the demo scenario (two Claude Code instances, approval gate)
- Run 10 consecutive times, fix everything that breaks
- Record 3-minute demo video
- Demo checklist:
  - [ ] Agent A produces structured manifest conforming to schema
  - [ ] Gate pauses execution and presents output
  - [ ] User approves via CLI
  - [ ] Agent B receives structured context
  - [ ] Event log captures every action
  - [ ] Budget tracking accurate
  - [ ] Video recorded and publishable

**Phase 2 exit criteria:**
- [ ] Tier 2 adapter (or Tier 1 fallback) is production-grade
- [ ] Structured handoffs work for Tier 1 (enforced) and Tier 2 (validated)
- [ ] Workflow verification catches all error classes
- [ ] Pause/resume works correctly
- [ ] Public demo works 10/10 times
- [ ] Demo video recorded
- [ ] ~290-350 tests passing

---

## Phase 3: Security, Reliability, and Launch (Weeks 17–24)

**Exit criterion:** Launchable V1 meeting all 7 success criteria from V1_SCOPE.md.

### Sprint 9: Capability-Based Security + Secrets (Weeks 17–18)

#### Capability model

```python
"""agentos/schemas/capability.py"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityGrant(BaseModel):
    """A single capability granted to an agent."""
    type: str = Field(description="tool:<name> | path:<glob> | domain:<host> | action:<name>")
    scope: str = Field(default="*", description="Scope restriction within the type")


class CapabilityPolicy(BaseModel):
    """Complete capability policy for an agent."""
    agent_id: str
    grants: list[CapabilityGrant] = Field(default_factory=list)
    deny_by_default: bool = Field(default=True, description="Deny anything not explicitly granted")
```

#### Security enforcer (Tier 1)

```python
"""agentos/security/enforcer.py — core logic outline"""

class CapabilityEnforcer:
    """Intercepts Tier 1 tool calls and validates against capability policy.

    For each tool call:
    1. Check if tool is in agent's allowlist
    2. Check if file paths are within workspace scope
    3. Check if network targets are in domain whitelist
    4. If denied: emit capability.denied event, return error to agent
    5. If granted: emit capability.granted event, proceed
    """
```

**Target:** ~40-50 new tests.

### Sprint 10: Adversarial Validation + Lifecycle (Weeks 19–20)

- Adversarial validation node as native workflow primitive
- Agent lifecycle: spawn, stop, restart with curated briefing
- Configurable lifecycle policies (token threshold, turn count, time limit)

**Target:** ~40-50 new tests.

### Sprint 11: Replay + Documentation + Examples (Weeks 21–22)

- Basic deterministic replay (read-only inspection from events)
- Three documentation guides: Getting Started, Adapter Development, Workflow Authoring
- Three example workflows tested end-to-end

**Target:** ~20-30 new tests.

### Sprint 12: Hardening + DevOps Demo + Launch Prep (Weeks 23–24)

- Full DevOps demo workflow (multi-agent pipeline)
- Load testing (5, 10, 20 concurrent tasks)
- Final test suite run (target: 400+ tests, 90%+ coverage)
- Launch materials: HN post draft, blog post, README

**Phase 3 exit criteria (= V1 launch criteria):**
- [ ] Demo: 10/10 consecutive successful runs
- [ ] Event log: complete, verified by replay
- [ ] Budget: hard enforcement, verified by adversarial test
- [ ] Security: Tier 1 capabilities enforced, adversarial tests pass
- [ ] Workflows: 3 documented examples, author in <30 minutes
- [ ] Users: 5+ external users with 3+ real workflows each
- [ ] Tests: 400+, 90%+ coverage on kernel + adapters
- [ ] Docs: Getting Started, Adapter Guide, Workflow Guide
- [ ] Video: 3-minute demo recorded

---

## Risk Register

### Risk 1: Claude Code Adapter Instability

**Severity:** High — threatens V1 credibility and Layer 2 positioning.

**Mitigation:** Week 0 spike tests integration surface before planning depends on it. Three-part contingency: Tier 1 API fallback, parallel Codex adapter, Anthropic DevRel engagement. Architecture ensures no core feature depends on any specific adapter.

**Monitor:** If spike fails, activate contingency immediately. If adapter works in spike but becomes unstable in Phase 2, switch to Tier 1 fallback for demo.

### Risk 2: Event Schema Lock-In

**Severity:** Medium — wrong schema forces painful migration of all downstream components.

**Mitigation:** Version every event from day one (`schema_version: "0.1"`). Include extensible `metadata` field. Review schema at end of Phase 1 before downstream features cement assumptions.

**Monitor:** If adding a new event type requires changing the core schema (not just adding a new `EventType` value), the schema is insufficiently extensible.

### Risk 3: Structured Output Compliance for Tier 2

**Severity:** Medium — if autonomous agents cannot reliably produce conforming manifests, handoff quality degrades.

**Mitigation:** Post-hoc validation with retry (up to 2 attempts). Clear failure path: non-conforming → retry → human gate. Never silent passthrough. Invest in prompt engineering for manifest instructions.

**Monitor:** If <70% of Tier 2 completions produce conforming manifests on first attempt, rework the prompt. If <90% after one retry, escalate to design review.

### Risk 4: Solo Founder Key-Person Risk

**Severity:** Medium-High — if sole engineer is unavailable, project stops.

**Mitigation:** Solo scope constraint means V1 is achievable by one person. Architecture avoids complexity requiring specialized knowledge. Comprehensive test suite enables second engineer to onboard from tests. Priority hire plan activated when feasible.

**Monitor:** If velocity drops below 70% of plan for two consecutive sprints, assess scope reduction or co-founder search.

### Risk 5: Insufficient Early Adopter Engagement

**Severity:** Medium — "5 external users" criterion depends on other people's schedules.

**Mitigation:** Start conversations early (not after launch). Maintain prospect tracker. Each conversation is a recruitment opportunity. Getting Started guide must be genuinely achievable in 15 minutes.

**Monitor:** If no one has expressed willingness to beta test by week 16, the outreach approach needs a reset.

### Risk 6: Platform Risk from First-Party Orchestration

**Severity:** High (long-term) — Anthropic/OpenAI/Microsoft ships native multi-agent orchestration.

**Mitigation:** Governance positioning (not orchestration) as primary value. Provider neutrality. On-premises option. Competitive response playbook (detailed in GTM_STRATEGY.md).

**Monitor:** Monitor provider announcements weekly. If any ships governance-focused multi-agent product, accelerate open-source timeline.

---

## Decision Log Template

For each significant decision during development, record:

- **Date:** When decided
- **Decision:** One sentence
- **Context:** Alternatives considered and why this was chosen
- **Consequences:** What this enables and forecloses
- **Revisit trigger:** When to reconsider

Expected decisions that will arise:
- Default Tier 1 model backend (Claude vs OpenAI vs configurable)
- Tier 2 session timeout behavior (no output after N seconds)
- Custom fields in task output schema (extensible or strict)
- Curated briefing generation for fresh restarts (what to include, max length)
- Secrets store implementation (encrypted file vs keyring vs env vars)

---

## Success Checklist

- [ ] **Demo reliability:** 10/10 consecutive successful runs (orchestration correctness)
- [ ] **Event log completeness:** Replay reconstructs identical state
- [ ] **Budget enforcement:** Under-budget test confirms clean termination
- [ ] **Security boundaries:** Adversarial tool calls blocked and logged
- [ ] **Workflow authoring:** 3 examples, clone-and-modify in <30 minutes
- [ ] **External users:** 5+ users, 3+ real workflows each, structured feedback
- [ ] **Test coverage:** 400+ tests, 90%+ on kernel and adapters
- [ ] **Documentation:** Getting Started + Adapter Guide + Workflow Guide
- [ ] **Demo video:** 3-minute recording of public demo
