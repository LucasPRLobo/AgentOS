# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentOS is a **governance and orchestration platform for autonomous AI agents**. It coordinates multiple AI agents (Claude Code, Codex, API-based agents) working together in structured workflows, with hard budget enforcement, capability-based security, approval gates, and a complete audit trail via an append-only event log.

**Status**: V1 — clean slate build. Design documents finalized, implementation starting from scratch.

**Key documents** (in `docs/`):
- `PROJECT_OVERVIEW.md` — Central vision document
- `V1_SCOPE.md` — What ships in V1, what's deferred
- `GTM_STRATEGY.md` — Market positioning (governance, not just orchestration)
- `DEVELOPMENT_PLAN.md` — Week-by-week engineering blueprint with schemas and test specs

## Architecture

### Repository Layout

```
agentos/
├── kernel/           # Core infrastructure
│   ├── event_log.py       # EventLog ABC + SQLiteEventLog
│   ├── state_machine.py   # TaskStateMachine (event-derived)
│   ├── dag_executor.py    # DAG scheduler + executor
│   ├── budget_manager.py  # 5-dimension budget tracking
│   ├── workspace.py       # Scoped dirs, file tracking
│   ├── gate_manager.py    # Approval gates + input gates
│   ├── lifecycle.py       # Agent spawn/stop/restart
│   └── seq.py             # Shared thread-safe sequence counter
├── adapters/         # Agent adapters by tier
│   ├── base.py            # AgentAdapter ABC
│   ├── tier1.py           # API-controlled tool-calling loop
│   └── tier2_claude_code.py  # Claude Code CLI integration
├── security/         # Capability enforcement
│   ├── capabilities.py    # Capability model + policy
│   ├── enforcer.py        # Tool call interception (Tier 1)
│   └── secrets.py         # Credential store
├── cli/              # Click-based CLI
│   ├── main.py, workflow.py, status.py, gate.py
├── schemas/          # All Pydantic v2 models
│   ├── events.py          # Event envelope + all event types
│   ├── task.py            # TaskState, TaskConfig, TaskOutput
│   ├── workflow.py        # WorkflowDefinition (parsed from YAML)
│   ├── budget.py          # BudgetSpec, BudgetUsage, BudgetDelta
│   ├── agent.py           # AgentConfig, AdapterTier
│   ├── gate.py            # GateConfig, GateResolution
│   ├── capability.py      # CapabilityGrant, CapabilityPolicy
│   └── workspace.py       # WorkspaceConfig, FileManifestEntry
└── validation/       # Pre-execution checks
    ├── workflow_verifier.py  # Static DAG analysis
    └── adversarial.py        # Adversarial validation node logic
tests/
├── unit/             # One test file per module
├── integration/      # Cross-module integration tests
└── e2e/              # End-to-end workflow tests
examples/
├── linear_research.yaml
├── parallel_analysis.yaml
└── fanout_with_gate.yaml
```

### Agent Adapter Tiers

- **Tier 1** (fully controlled): AgentOS controls the tool-calling loop via LLM API. Full capability enforcement, full observability.
- **Tier 2** (semi-controlled): AgentOS monitors from outside (e.g., Claude Code CLI). Orchestration-layer enforcement (workspace scoping, budget, task assignment). Output validated post-hoc.
- **Tier 3** (best-effort): Experimental wrappers for other CLIs. Not production-grade in V1.

### Key Architectural Patterns

- **Event-sourced state**: All state changes are append-only events in SQLite. State is derived from events. Nothing mutates silently.
- **Budget-constrained execution**: Hard limits on tokens, API calls, execution time, cost, and concurrency. Exceeding budget halts execution cleanly.
- **Capability-based security**: Fine-grained permissions (tool allowlists, path scoping, domain whitelists). Runtime-enforced for Tier 1, orchestration-layer for Tier 2.
- **Structured task output protocol**: JSON manifests for inter-agent handoffs (key findings, confidence, sources, files produced). Tier 1: enforced via JSON mode. Tier 2: validated post-hoc.
- **DAG-based workflows**: Tasks form directed acyclic graphs with topological scheduling, controlled parallelism, approval gates, and adversarial validation nodes.
- **Shared sequence counter**: Thread-safe `SeqCounter` passed to all components — no manual sync needed.

### Event Log Schema (SQLite)

```sql
events(
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  workflow_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  timestamp TEXT NOT NULL,
  schema_version TEXT NOT NULL DEFAULT '0.1',
  payload TEXT NOT NULL DEFAULT '{}',   -- JSON
  metadata TEXT NOT NULL DEFAULT '{}',  -- JSON
  UNIQUE(workflow_id, seq)
)
```

### Task State Machine

```
PENDING → RUNNING → SUCCEEDED / FAILED / WAITING
                                         ↓
                                       RUNNING  (resume after gate)
```

## Tech Stack

- Python 3.11+
- Pydantic v2 (all schemas)
- SQLite with WAL mode (event log persistence)
- Click (CLI framework)
- Anthropic SDK + OpenAI SDK (Tier 1 adapters)
- Pytest with markers: `integration`, `e2e`, `slow`
- Type hints everywhere, no dynamic typing for core interfaces

## Development Phases

V1 follows three phases over 24 weeks:

1. **Phase 1 — Foundation (Weeks 1-8)**: Event log → State machine → DAG executor → Budget manager → Workspace → Tier 1 adapter → Gates → CLI → Internal demo (Tier 1)
2. **Phase 2 — Agent Integration (Weeks 9-16)**: Tier 2 Claude Code adapter → Structured handoffs → Workflow verification → Pause/resume → Public demo
3. **Phase 3 — Security & Launch (Weeks 17-24)**: Capability model → Secrets store → Adversarial validation → Lifecycle management → Replay → Documentation → DevOps demo

**Week 0 spikes** (before Phase 1): Claude Code CLI integration surface test, task output schema v0.1, event schema design.

## Git Workflow

- `main` → production releases only, no direct commits
- `feature/*` → scoped feature branches (e.g., `feature/event-log-sqlite`, `feature/dag-executor`)
- `docs/*` → documentation branches

**Commit format**: Conventional commits — `feat(kernel): add DAG executor`, `fix(budget): enforce hard cost limit`, `test(adapters): tier1 structured output`

## Non-Negotiable Rules

- AgentOS contains zero domain-specific logic — it is a generic orchestration/governance kernel
- Never bypass budget checks or capability enforcement
- Never store mutable run state outside the event log
- Never allow silent failures — emit events for all transitions
- All state must be derivable from the event log (event-sourced)
- Structured task output protocol is mandatory for inter-agent handoffs — no unstructured file passing
- Prefer clarity over cleverness, deterministic behavior over convenience
