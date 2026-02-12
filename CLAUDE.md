# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentOS is a domain-agnostic cognitive execution substrate — a kernel for AI agent workflows. LabOS is a reference research domain built on top of AgentOS demonstrating scientific workflow automation (ML experiment replication).

**Status**: Early stage — specification documents exist (`project_structure.md`, `system_prompt.md`) but implementation has not started yet.

## Architecture

### Core Separation Constraint

```
agentos  ← NEVER imports labos
   ↑
labos    ← depends on agentos via public API only
   ↑
future domains (e.g., FinanceResearchOS)
```

AgentOS contains **zero domain-specific logic**. LabOS registers tools and workflows via public AgentOS interfaces only. CI must enforce that `agentos` never imports `labos`.

### Monorepo Layout (Planned)

```
packages/
  agentos/agentos/    → core/, schemas/, runtime/, tools/, governance/, memory/, integrity/, observability/, eval/
  labos/labos/        → domain/schemas/, tools/, workflows/, eval/
examples/
  labos_ml_replication/
tests/
  integration/
  e2e/
```

### Key Architectural Patterns

- **Event-sourced execution**: All state changes are append-only events in SQLite. State is derived from events. Nothing mutates silently.
- **Budget-constrained cognition**: Hard limits on tokens, tool calls, execution time, recursion depth, and parallelism. Exceeding budget halts execution cleanly.
- **Typed tool interface**: Tools are syscalls with strict Pydantic v2 input/output schemas, side-effect classification, and event emission (ToolCallStarted/ToolCallFinished). No untyped dict passing.
- **Deterministic replay**: Runs can be reconstructed from event logs.
- **DAG-based workflows**: Tasks form directed acyclic graphs with topological scheduling and controlled parallelism.

### Event Log Schema (SQLite)

```sql
events(run_id TEXT, seq INTEGER, timestamp TEXT, event_type TEXT, payload_json TEXT)
```

### Task State Machine

```
PENDING → RUNNING → SUCCEEDED/FAILED
```

## Tech Stack

- Python 3.11+
- Pydantic v2 (all schemas)
- SQLite (event log persistence)
- Type hints everywhere, no dynamic typing for core interfaces

## Implementation Order (Strict)

Development must follow these phases in order:

1. **Kernel Foundation**: Core IDs/errors → Pydantic schemas → SQLite event log → Tool substrate → Linear workflow runtime
2. **Governance & DAG**: DAG execution → Budget manager → Concurrency control → Stop conditions → Permissions engine
3. **Observability & Replay**: Deterministic hashing → Replay engine
4. **Memory & Integrity**: Episodic store → Semantic store → Context pack builder
5. **Evaluation Harness**: EvalCase abstraction → EvalRunner → Metrics collection

LabOS MVP (ML Replication) comes after AgentOS kernel is stable.

## Git Workflow

**GitFlow is mandatory.**

- `main` → production releases only, no direct commits
- `develop` → integration branch, no direct commits
- `feature/*` → scoped feature branches (e.g., `feature/event-log-sqlite`, `feature/dag-executor`)
- `release/*` → release preparation
- `hotfix/*` → urgent fixes from main

**Commit format**: Conventional commits — `feat(runtime): add DAG executor`, `fix(governance): enforce recursion depth cap`

## Non-Negotiable Rules

- Never introduce domain terms into AgentOS
- Never bypass tool schema validation or budget checks
- Never store mutable run state outside the event log
- Never allow silent failures — log everything, emit events for all transitions
- Prefer clarity over cleverness, deterministic behavior over convenience
