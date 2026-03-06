# AgentOS — Implementation Status

**Date:** March 2026
**Total Tests:** 1,193 (all passing)
**Codebase:** 69 Python source files, 15 example workflows

This document maps every feature described in PROJECT_OVERVIEW.md, V1_SCOPE.md, and DEVELOPMENT_PLAN.md against the current implementation. Each item is marked **Done**, **Partial**, or **Missing**.

---

## Core Kernel

| Feature | Status | Implementation | Notes |
|---------|--------|---------------|-------|
| Event-sourced state (append-only SQLite) | **Done** | `kernel/event_log.py` — `EventLog` ABC + `SQLiteEventLog` with WAL mode | Schema: event_id, event_type, workflow_id, seq, timestamp, schema_version, payload, metadata |
| Shared sequence counter | **Done** | `kernel/seq.py` — Thread-safe `SeqCounter` | Passed to all components, eliminates manual sync |
| Task state machine | **Done** | `kernel/state_machine.py` — `TaskStateMachine` | States: PENDING → RUNNING → SUCCEEDED/FAILED/WAITING → RUNNING (resume) |
| DAG executor | **Done** | `kernel/dag_executor.py` — Topological scheduling, controlled parallelism | Supports linear, parallel, fan-out/fan-in, conditional edges |
| Budget manager (5-dimension) | **Done** | `kernel/budget_manager.py` — tokens, API calls, time, cost, concurrency | Per-agent, per-team, per-workflow enforcement. Hard limits halt execution cleanly |
| Workspace management | **Done** | `kernel/workspace.py` — Scoped dirs, file tracking | File manifest, predecessor context injection, team-scoped workspaces |
| Gate manager | **Done** | `kernel/gate_manager.py` — Approval gates + input gates | Pause/resume, gate resolution via CLI |
| Agent lifecycle | **Done** | `kernel/lifecycle.py` — Spawn, stop, restart | Fresh restart with curated briefing, configurable policies |
| Channel router | **Done** | `kernel/channel_router.py` — Inter-agent messaging | Broadcast and direct modes, publish/subscribe |
| Condition evaluator | **Done** | `kernel/condition_evaluator.py` — Expression evaluation | Field access, comparisons, boolean logic for conditional branching |
| Replayer | **Done** | `kernel/replayer.py` — Event replay for state reconstruction | Deterministic replay from event log |

## Schemas (Pydantic v2)

| Schema | Status | File | Notes |
|--------|--------|------|-------|
| Events (envelope + all types) | **Done** | `schemas/events.py` | All event types defined |
| Task (state, config, output) | **Done** | `schemas/task.py` | `TaskConfig` with conditions, retry_policy, consultation fields |
| Workflow (YAML definition) | **Done** | `schemas/workflow.py` | `WorkflowDefinition` with agents, tasks, budget, channels, teams |
| Budget (spec, usage, delta) | **Done** | `schemas/budget.py` | `BudgetSpec`, `BudgetUsage`, `BudgetDelta` |
| Agent (config, tier) | **Done** | `schemas/agent.py` | `AgentConfig` with adapter, role, model, budget, team, capabilities |
| Gate (config, resolution) | **Done** | `schemas/gate.py` | Approval and input gate types |
| Capability (grant, policy) | **Done** | `schemas/capability.py` | Tool allowlists, path scoping, domain whitelists |
| Workspace (config, manifest) | **Done** | `schemas/workspace.py` | File manifest entries |
| Channel (config, mode) | **Done** | `schemas/channel.py` | `ChannelConfig` with broadcast/direct modes |
| Team (config) | **Done** | `schemas/team.py` | `TeamConfig` with manager, members, budget, workspace, human_input |

## Adapters

| Adapter | Status | File | Notes |
|---------|--------|------|-------|
| Base ABC | **Done** | `adapters/base.py` | `AgentAdapter` with `async execute_task()` |
| Tier 1 (API-controlled) | **Done** | `adapters/tier1.py` | Anthropic + OpenAI tool-calling loops, structured JSON output |
| Tier 2 — Claude Code | **Done** | `adapters/tier2_claude_code.py` | Production-grade CLI integration, `--print --output-format json` |
| Tier 2 — Aider | **Done** | `adapters/tier2_aider.py` | Second Tier 2 adapter |
| Tier 2 — Shared utilities | **Done** | `adapters/tier2_shared.py` | Common Tier 2 logic |
| Manager adapter | **Done** | `adapters/manager_adapter.py` | `ManagerAgentAdapter` — wraps CC instance as team supervisor |
| Manager agent | **Done** | `adapters/manager_agent.py` | Multi-round supervision: plan → execute members → review → reassign |

## Teams & Manager Orchestration

| Feature | Status | Notes |
|---------|--------|-------|
| TeamConfig schema | **Done** | Manager, members, description, channel, human_input, budget, workspace |
| Team expander (compile-time) | **Done** | `kernel/team_expander.py` — Validates, creates channels, tags agents, resolves workspace |
| Active manager supervision | **Done** | Manager is a CC instance that plans assignments, executes members, reviews quality |
| Team-level budget enforcement | **Done** | BudgetManager aggregates usage across team members, enforces team limits |
| Team-scoped workspaces | **Done** | Auto-created directories per team under workflow workspace root |
| Inter-team communication | **Done** | Via channels — teams publish/subscribe to shared channels |
| Workflow verifier team checks | **Done** | Manager/member existence, overlap detection, budget warnings |

## Security

| Feature | Status | File | Notes |
|---------|--------|------|-------|
| Capability model + policy | **Done** | `security/enforcer.py` | Tool call interception for Tier 1 |
| Secrets store | **Done** | `security/secrets.py` | Credential injection at runtime |
| Post-hoc verifier | **Done** | `security/post_hoc_verifier.py` | Output validation for Tier 2 |
| Audit trail | **Done** | `security/audit.py` | Full audit via event log |
| Safety score | **Done** | `security/safety_score.py` | Agent risk profiling |
| Sandbox model | **Done** | `security/sandbox.py` | Schema-level sandbox config |
| Sandbox-level enforcement (containers, seccomp) | **Missing** | — | V2 — schema exists but no runtime enforcement |

## Validation

| Feature | Status | File | Notes |
|---------|--------|------|-------|
| Workflow verifier (static DAG analysis) | **Done** | `validation/workflow_verifier.py` | Cycles, orphans, undefined agents, unreachable tasks, budgets, teams |
| Adversarial validation nodes | **Done** | `validation/adversarial.py` | Validator node type, verification reports, pass/fail + confidence |

## CLI

| Command | Status | Notes |
|---------|--------|-------|
| `agentos workflow run <file>` | **Done** | YAML parse → team expansion → adapter assembly → DAG execution |
| `agentos workflow verify <file>` | **Done** | Static verification before execution |
| `agentos workflow resume <id>` | **Done** | Resume paused workflows |
| `agentos status` | **Done** | Current execution state |
| `agentos events [--follow]` | **Done** | Event stream |
| `agentos cost` | **Done** | Budget consumption |
| `agentos gate list` | **Done** | Pending approval gates |
| `agentos gate approve/reject <id>` | **Done** | Resolve gates |
| `agentos agent restart <id>` | **Partial** | Lifecycle module exists; CLI command may not be wired |

## Dashboard (V1.5)

| Feature | Status | Notes |
|---------|--------|-------|
| FastAPI backend | **Done** | `dashboard/app.py` — REST API + static file serving |
| WebSocket live streaming | **Done** | `dashboard/websocket.py` — Real-time event push |
| Serializers | **Done** | `dashboard/serializers.py` — WorkflowSnapshot → JSON |
| React frontend (Vite + TypeScript) | **Done** | DAG visualization, task nodes, log table, agent panels |
| Auth | **Done** | `dashboard/auth.py` |
| Workflow builder UI | **Done** | `dashboard/builder.py` — Visual workflow editor |

## Workflow Patterns

| Pattern | Status | Notes |
|---------|--------|-------|
| Linear (sequential tasks) | **Done** | `examples/linear_research.yaml` |
| Parallel (concurrent execution) | **Done** | `examples/parallel_analysis.yaml` |
| Fan-out/fan-in with gate | **Done** | `examples/fanout_with_gate.yaml` |
| Conditional branching | **Done** | `examples/conditional_deploy.yaml` |
| Review/revision loops | **Done** | `examples/code_review_loop.yaml` |
| Consultation tasks | **Done** | `examples/research_with_consultation.yaml` |
| Collaborative routing | **Done** | `examples/collaborative_routing.yaml` |
| Team-based (single team) | **Done** | `examples/event_planning.yaml` |
| Team-based (multi-team) | **Done** | `examples/market_research.yaml` |
| Hedge fund (full teams) | **Done** | `examples/hedge_fund_full.yaml` — 4 teams, inter-team channels |
| DevOps pipeline | **Done** | `examples/devops_pipeline.yaml` |
| Aider code review | **Done** | `examples/aider_code_review.yaml` |

## V3+ / Intelligence Features

| Feature | Status | File | Notes |
|---------|--------|------|-------|
| Cross-run memory | **Done** | `kernel/memory_store.py` | Knowledge persistence across workflow runs |
| Knowledge graphs | **Done** | `intelligence/knowledge_graph.py` | Advanced RAG |
| Learning / pattern detection | **Done** | `intelligence/learning.py` | Config recommendations from execution history |
| Specialization tracking | **Done** | `intelligence/specialization.py` | Cross-workflow agent specialization |
| Fine-tuning data pipeline | **Done** | `intelligence/finetune.py` | Multi-provider export |
| Benchmarking | **Done** | `intelligence/benchmark.py` | Performance measurement |
| Dynamic team composition | **Done** | `kernel/team_composer.py` | Runtime team modification |
| Mutable DAG | **Done** | `kernel/mutable_dag.py` | Runtime DAG modification |
| Marketplace / registry | **Done** | `marketplace/registry.py` | Agent/workflow sharing |

---

## Gap Analysis: Docs vs Implementation

### PROJECT_OVERVIEW.md Gaps

| Area | Doc Says | Reality | Action Needed |
|------|----------|---------|---------------|
| Manager agent | "Message router" that routes messages between team members | Active CC-based supervisor with multi-round plan/execute/review loop | **Doc needs update** — implementation exceeds the described design |
| Sandbox security | "Container-level isolation, seccomp profiles" | Schema exists (`schemas/sandbox.py`, `security/sandbox.py`) but no runtime enforcement | Expected — V2 scope per V1_SCOPE.md |
| Multi-user deployment | Mentioned as future direction | Not implemented | Expected — V2 scope |

### V1_SCOPE.md Gaps

| Deferred Feature | Current Status | Action Needed |
|------------------|---------------|---------------|
| Message channels / async communication | **Done** — `kernel/channel_router.py`, `schemas/channel.py` | **Update deferred table** → mark as Done |
| Manager agent for message routing | **Done** — `adapters/manager_adapter.py`, `adapters/manager_agent.py` | **Update deferred table** → mark as Done |
| Dynamic team composition at runtime | **Done** — `kernel/team_composer.py` | **Update deferred table** → mark as Done |
| Cross-run memory | **Done** — `kernel/memory_store.py` | **Update deferred table** → mark as Done |
| Knowledge graphs / advanced RAG | **Done** — `intelligence/knowledge_graph.py` | **Update deferred table** → mark as Done |
| Fine-tuning pipelines | **Done** — `intelligence/finetune.py` | **Update deferred table** → mark as Done |
| Agent Safety Score | **Done** — `security/safety_score.py` | **Update deferred table** → mark as Done |
| Benchmarking engine | **Done** — `intelligence/benchmark.py` | **Update deferred table** → mark as Done |
| Web dashboard (read-only) | **Done** — `dashboard/` (full CRUD, not just read-only) | **Update deferred table** → mark as Done |
| Sandbox-level security | Schema only, no runtime | Correct — remains V2 |
| Runtime-verified policy for Tier 2/3 | Not implemented | Correct — remains V2 |
| Multi-user deployment | Not implemented | Correct — remains V2 |

### DEVELOPMENT_PLAN.md Gaps

| Area | Gap | Action Needed |
|------|-----|---------------|
| Sprint entry for teams | No sprint documents the team orchestration implementation | **Add sprint entry** for team schema, expander, manager rewrite, verifier updates |
| Team budget enforcement | Not mentioned in any sprint | Covered by current implementation, needs sprint log |

---

## Test Coverage Summary

| Category | Test Files | Approx. Tests |
|----------|-----------|---------------|
| Unit tests | 42 files | ~900 |
| Integration tests | 13 files | ~200 |
| E2E tests | 6 files | ~90 |
| **Total** | **61 files** | **1,193** |

Key team-related test files:
- `tests/unit/test_team_schema.py` — TeamConfig schema validation
- `tests/unit/test_team_expander.py` — Channel creation, agent tagging, validation errors, budget enforcement
- `tests/unit/test_manager_agent.py` — Prompt building, assignment parsing, review loop
- `tests/unit/test_manager_adapter.py` — End-to-end with mock member adapters
- `tests/integration/test_team_workflow.py` — Full team workflow with YAML parsing and verification

---

## What Is Still Missing

### Needs Implementation

1. **Sandbox runtime enforcement** — Container-level isolation, seccomp profiles. Schema exists but no process-level enforcement. (V2)
2. **Runtime-verified policy for Tier 2/3** — Policy enforcement beyond orchestration layer. (V2)
3. **Multi-user deployment** — Auth, isolation, multi-tenant event logs. (V2)
4. **`agentos agent restart` CLI wiring** — Lifecycle module exists but CLI command integration may be incomplete.

### Needs Documentation Updates

1. **V1_SCOPE.md deferred table** — 9 features marked "deferred" are now implemented (channels, manager, teams, memory, knowledge graphs, fine-tuning, safety score, benchmarking, dashboard).
2. **PROJECT_OVERVIEW.md manager description** — Currently describes a "message router"; implementation is an active CC-based supervisor with structured assignment plans and quality review loops.
3. **DEVELOPMENT_PLAN.md sprint log** — No sprint entry for team orchestration (schema, expander, manager rewrite, budget enforcement, workspace).
4. **CLAUDE.md repo layout** — Missing entries for `schemas/team.py`, `kernel/team_expander.py`, `dashboard/`, `intelligence/`, `marketplace/`.
