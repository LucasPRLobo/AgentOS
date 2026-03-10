# AgentOS V1 — System Report

**Date:** March 3, 2026
**Branch:** `dev`
**Status:** V1 complete — first working version with real LLM execution

---

## 1. What AgentOS Is

AgentOS is a **governance and orchestration platform for autonomous AI agents**. It coordinates multiple AI agents working together in structured DAG workflows, with:

- **Hard budget enforcement** (tokens, cost, time, API calls, concurrency)
- **Capability-based security** (tool allowlists, path scoping, domain whitelists)
- **Approval gates** for human-in-the-loop checkpoints
- **Complete audit trail** via an append-only, event-sourced SQLite log
- **Structured inter-agent handoffs** (findings, confidence levels, open questions)

It is a **generic orchestration kernel** — it contains zero domain-specific logic. Any multi-agent workflow that can be expressed as a directed acyclic graph can be run, governed, paused, resumed, and replayed.

### Why AgentOS Exists

The current multi-agent landscape orchestrates prompt chains — sequential LLM calls glued together with code (Layer 1). AgentOS orchestrates actual autonomous agent runtimes — Claude Code instances, API-driven tool-calling loops, and eventually third-party CLIs — with enterprise governance (Layer 2). Budget enforcement, capability-based security, structured inter-agent handoffs, and a complete audit trail are built into the kernel, not bolted on after. Nobody else does this at the runtime orchestration layer.

---

## 2. Codebase Overview

| Metric | Value |
|--------|-------|
| Source modules | 35 Python files |
| Source lines (statements) | 2,413 |
| Test files | 38 Python files |
| Test lines | 10,213 |
| Tests passing | 581 / 581 |
| Test coverage | **85%** overall (kernel 97-100%, adapters 65-94%, CLI 47-93%) |
| Example workflows | 5 YAML files |
| Sprints completed | 12 |
| Dependencies | pydantic v2, click, pyyaml, anthropic SDK, openai SDK |

**Coverage breakdown by layer:**

| Layer | Coverage | Notes |
|-------|----------|-------|
| Kernel (event_log, state_machine, dag_executor, budget, workspace, gates, lifecycle, seq) | **97-100%** | All core modules at 100% except dag_executor (99%) and workspace (97%) |
| Schemas (all 8 modules) | **100%** | Every model fully tested |
| Security (enforcer, secrets, capabilities) | **98-100%** | Including adversarial tool call tests |
| Validation (workflow_verifier, adversarial) | **100%** | All 8 verifier checks + adversarial logic |
| Adapters (tier1, tier2) | **65-94%** | Tier 1 at 94%; Tier 2 at 65% (streaming/Popen code paths require live subprocess) |
| CLI (workflow, status, gate, main) | **47-93%** | Live executor paths and replay commands are tested via e2e but not fully covered by unit tests |

The 85% overall coverage reflects a deliberate tradeoff: kernel and schemas are exhaustively tested (the governance core), while CLI and live adapter code paths — which require real subprocesses or API calls — have lower unit coverage compensated by manual live testing and e2e tests.

### Repository Layout

```
agentos/
├── kernel/                  # Core infrastructure (1,546 lines)
│   ├── seq.py                  Thread-safe sequence counter
│   ├── event_log.py            EventLog ABC + SQLiteEventLog (WAL mode)
│   ├── state_machine.py        Task state machine (event-derived)
│   ├── dag_executor.py         DAG scheduler + thread-pool executor
│   ├── budget_manager.py       5-dimension budget tracking + enforcement
│   ├── workspace.py            Scoped file sandbox + audit trail
│   ├── gate_manager.py         Approval/input gate lifecycle
│   └── lifecycle.py            Agent spawn/stop/restart with briefings
│
├── schemas/                 # Pydantic v2 models (599 lines)
│   ├── events.py               Event envelope + 14 event types
│   ├── task.py                 TaskConfig, TaskOutput, TaskStatus
│   ├── workflow.py             WorkflowDefinition (parsed from YAML)
│   ├── budget.py               BudgetSpec, BudgetUsage, BudgetDelta
│   ├── agent.py                AgentConfig, AdapterTier
│   ├── gate.py                 GateConfig, GateResolution
│   ├── capability.py           CapabilityGrant, CapabilityPolicy
│   └── workspace.py            WorkspaceConfig, FileManifestEntry
│
├── adapters/                # Agent adapters by tier (732 lines)
│   ├── base.py                 AgentAdapter ABC (async interface)
│   ├── tier1.py                API-controlled tool-calling loop
│   └── tier2_claude_code.py    Claude Code CLI subprocess integration
│
├── security/                # Capability enforcement (358 lines)
│   ├── capabilities.py         Capability model + policy
│   ├── enforcer.py             Tool call interception (Tier 1)
│   └── secrets.py              Credential store with capability gating
│
├── validation/              # Pre/post-execution checks (442 lines)
│   ├── workflow_verifier.py    Static DAG analysis (8 checks)
│   └── adversarial.py          Adversarial validation node logic
│
├── cli/                     # Click-based CLI (1,267 lines)
│   ├── main.py                 Entry point + demo command
│   ├── workflow.py             run / resume / verify commands
│   ├── status.py               status / events / cost / replay commands
│   └── gate.py                 list / approve / reject commands
│
tests/
├── unit/                    # One test file per module
├── integration/             # Cross-module integration tests
└── e2e/                     # End-to-end workflow tests
```

---

## 3. Architecture

### 3.1 Core Design Principles

1. **Event-sourced state.** All state changes are append-only events in SQLite. Task states, budget usage, gate resolutions — everything is derived from the event log. Nothing mutates silently. Any workflow can be fully reconstructed from its events.

2. **Budget-constrained execution.** Hard limits on 5 dimensions: tokens, API calls, execution time, cost, and concurrency. Exceeding any budget halts execution cleanly with a `BudgetExceededError` and a `BUDGET_EXCEEDED` event.

3. **Capability-based security.** Fine-grained permissions using type prefixes: `tool:file_read`, `path:src/**`, `domain:api.example.com`, `action:secret:API_KEY`. Deny-by-default posture. Tier 1: enforced at runtime in the tool-calling loop. Tier 2: orchestration-layer enforcement.

4. **Structured task output protocol.** Every task produces a `TaskOutput` manifest: summary, key findings with confidence levels, files produced, open questions. This is how agents hand off work — not via unstructured files, but via typed, validated data.

5. **DAG-based workflows.** Tasks form directed acyclic graphs. The executor does topological scheduling with controlled parallelism via thread pools, respecting `max_concurrent_tasks`. Failed tasks cascade — their dependents are skipped.

### 3.2 Agent Adapter Tiers

| Tier | Control Model | Enforcement | V1 Status |
|------|--------------|-------------|-----------|
| **Tier 1** | AgentOS controls the tool-calling loop via Anthropic Messages API | Full: tool allowlists, capability checks, budget per API call | Implemented + tested |
| **Tier 2** | AgentOS launches Claude Code CLI as subprocess, monitors externally | Orchestration-layer: workspace scoping, budget from JSON output, manifest validation post-hoc | Implemented + live-tested |
| **Tier 3** | Best-effort wrappers for other CLIs | Minimal | Not production-grade in V1 |

### 3.3 Event Log Schema

```sql
events(
  event_id   TEXT PRIMARY KEY,      -- UUID
  event_type TEXT NOT NULL,          -- one of 14 types
  workflow_id TEXT NOT NULL,         -- workflow scope
  seq        INTEGER NOT NULL,       -- monotonic within workflow
  timestamp  TEXT NOT NULL,          -- ISO 8601
  schema_version TEXT DEFAULT '0.1',
  payload    TEXT DEFAULT '{}',      -- JSON
  metadata   TEXT DEFAULT '{}',      -- JSON
  UNIQUE(workflow_id, seq)
)
```

**14 Event Types:**
- Workflow: `WORKFLOW_STARTED`, `WORKFLOW_COMPLETED`
- Task: `TASK_STATE_CHANGED`, `TASK_OUTPUT_PRODUCED`
- Agent: `AGENT_SPAWNED`, `AGENT_TERMINATED`
- Gates: `GATE_WAITING`, `GATE_RESOLVED`
- Budget: `BUDGET_CONSUMED`, `BUDGET_EXCEEDED`
- Files: `FILE_CREATED`, `FILE_MODIFIED`
- Security: `CAPABILITY_GRANTED`, `CAPABILITY_DENIED`
- Errors: `ERROR_OCCURRED`

### 3.4 Task State Machine

```
PENDING ──→ RUNNING ──→ SUCCEEDED
                   ├──→ FAILED
                   └──→ WAITING (gate) ──→ RUNNING (resumed)
```

All transitions go through the `TaskStateMachine` which emits `TASK_STATE_CHANGED` events. Invalid transitions raise `ValueError`.

### 3.5 Data Flow

```
                    ┌─────────────────────┐
                    │  Workflow YAML       │
                    │  (definition)        │
                    └─────────┬───────────┘
                              │ parse + validate
                              ▼
                    ┌─────────────────────┐
                    │  DAGExecutor         │
                    │  (topological sched) │
                    └──┬──────┬──────┬────┘
                       │      │      │       parallel dispatch
                       ▼      ▼      ▼
                    ┌─────┐┌─────┐┌─────┐
                    │Agent││Agent││Agent│   (Tier 1 or Tier 2)
                    │  A  ││  B  ││  C  │
                    └──┬──┘└──┬──┘└──┬──┘
                       │      │      │       TaskOutput (findings,
                       ▼      ▼      ▼        confidence, questions)
                    ┌─────────────────────┐
                    │  Structured Handoff  │
                    │  (predecessor_context│
                    │   → downstream task) │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Event Log (SQLite)  │
                    │  append-only audit   │
                    └─────────────────────┘
```

---

## 4. Module-by-Module Analysis

### 4.1 Kernel

**`seq.py` (29 lines)** — Thread-safe monotonic counter. Single `SeqCounter` instance shared by all kernel components via constructor injection. Guarantees event ordering across concurrent threads.

**`event_log.py` (135 lines)** — Abstract `EventLog` interface + `SQLiteEventLog` implementation. WAL mode for concurrent reads. Thread-locked writes. JSON serialization for payload/metadata. `UNIQUE(workflow_id, seq)` prevents duplicate events. Methods: `append`, `query` (with filters), `replay` (ordered by seq), `last_seq`.

**`state_machine.py` (78 lines)** — Stateless task state machine. All state derived from replaying `TASK_STATE_CHANGED` events. Validates transitions against allowed set. Never stores state in memory — always queries the event log.

**`dag_executor.py` (382 lines)** — The orchestration hub. Validates DAG via Kahn's algorithm (cycle detection + missing dependency checks). Dispatches ready tasks to a `ThreadPoolExecutor` with `max_concurrent_tasks`. Handles:
- Parallel execution with dependency resolution
- Cascade failure (skip dependents of failed tasks)
- Structured handoffs (predecessor `TaskOutput` list passed to each task)
- Pause/resume via event-derived state reconstruction
- Both `run()` (from scratch) and `resume()` (from persisted events)

**`budget_manager.py` (123 lines)** — 5-dimension budget tracking. Hierarchical: workflow-level limits + per-agent limits. `apply()` records usage delta, emits `BUDGET_CONSUMED`, then checks all dimensions. Exceeding any dimension raises `BudgetExceededError` and emits `BUDGET_EXCEEDED`. The DAG executor catches the exception and marks the task as FAILED.

**`workspace.py` (227 lines)** — File sandbox. Path containment validation (rejects `..` traversal). Glob-pattern access control (`allowed_patterns`). Read-only mode. Full manifest tracking (every file operation recorded with agent/task context). Emits `FILE_CREATED`/`FILE_MODIFIED` events.

**`gate_manager.py` (195 lines)** — Approval and input gate lifecycle. Creates gates (emits `GATE_WAITING`), resolves them (emits `GATE_RESOLVED`). State derived from events — stateless queries. Supports: approved, rejected, edited resolutions with reviewer identity and feedback.

**`lifecycle.py` (377 lines)** — Agent spawn/stop/restart. Configurable policies per agent (max tokens, max turns, max time, max restarts). On restart, generates a `CuratedBriefing` — a compressed context summary of the previous run's findings, trimmed to fit a token budget. Emits `AGENT_SPAWNED`/`AGENT_TERMINATED` events.

### 4.2 Adapters

**`base.py` (41 lines)** — `AgentAdapter` ABC. Three abstract methods: `tier` (property), `execute_task` (async), `terminate` (async). Async from the start. Every adapter returns a `TaskOutput`.

**`tier1.py` (381 lines)** — API-controlled adapter. AgentOS owns the tool-calling loop:
1. Build system prompt with role + predecessor context + tool constraints
2. Call Anthropic Messages API with tool definitions
3. For each `tool_use` block: dispatch to handler (file_read/file_write work, others stubbed)
4. Track budget after each API call
5. Loop until `task_complete` tool called or `end_turn`
6. Return structured `TaskOutput`

Built-in tools: `file_read`, `file_write`, `shell_exec`, `web_search`, `task_complete`. The `task_complete` tool is always included — it's how the agent signals it's done with structured output.

**`tier2_claude_code.py` (476 lines)** — Subprocess-based adapter. Launches `claude` CLI with:
- `--print --output-format stream-json --verbose --max-turns 30`
- `--allowedTools` with mapped tool names (YAML `file_read` → CLI `Read`)
- Anti-nesting guard stripped from environment (`CLAUDECODE`)
- Predecessor context written as `.agentos_context/*.json` files

Streaming support: when `log_fn` is provided, uses `subprocess.Popen` with background threads to stream NDJSON events in real time — tool calls, text output, searches — all visible in the terminal as they happen.

Manifest validation: after each run, reads `manifest.json` from workspace. If missing/invalid, retries up to 2 times with a focused prompt.

### 4.3 Security

**`capabilities.py` (108 lines)** — Capability model with 4 type prefixes: `tool:`, `path:`, `domain:`, `action:`. Supports wildcards (`tool:*`), glob patterns (`path:src/**`), subdomain matching (`domain:*.example.com`), and namespace hierarchies (`action:secret:*`).

**`enforcer.py` (150 lines)** — Runtime interception for Tier 1 tool calls. Validates: tool in allowlist, file paths within scope (rejects traversal), domains in whitelist. Emits `CAPABILITY_GRANTED` or `CAPABILITY_DENIED` events for every check.

**`secrets.py` (100 lines)** — In-memory credential store with capability-gated access. Secret values are never logged — only access events. Requires `action:secret:<name>` capability grant. Deny-by-default.

### 4.4 Validation

**`workflow_verifier.py` (263 lines)** — Static pre-execution analysis. 8 checks:
1. Missing dependencies (ERROR)
2. Undefined agents (ERROR)
3. Cycle detection via Kahn's algorithm (ERROR)
4. Unreachable tasks (ERROR)
5. Budget allocation overruns (WARNING)
6. Gates with unnecessary agent field (WARNING)
7. Agent tasks missing agent field (ERROR)
8. Empty workflow (WARNING)

**`adversarial.py` (179 lines)** — Post-execution quality check. An independent validation agent (ideally different model) reviews another agent's `TaskOutput`. Checks: summary exists, findings have content, status is succeeded. Configurable failure actions: RETRY, REVISE, GATE (escalate to human), or FAIL.

### 4.5 CLI

**`main.py` (441 lines)** — Entry point. Registers all subcommand groups. Contains the `demo` command — the reference implementation that wires everything together with stub or Tier 2 execution.

**`workflow.py` (413 lines)** — Core workflow commands:
- `run` — Execute workflow with `--live` flag for real adapters or stubs (default)
- `resume` — Continue paused workflow after gate resolution
- `verify` — Static validation without execution

The `--live` flag activates `_build_live_executor()` which creates real `Tier1Adapter` or `ClaudeCodeAdapter` instances per agent, with real-time streaming output.

**`status.py` (265 lines)** — Inspection commands: `status` (workflow overview), `events` (filtered event replay), `cost` (per-agent budget consumption), `replay` (full state reconstruction via `WorkflowReplayer`).

**`gate.py` (148 lines)** — Gate management: `list` (pending/all gates), `approve`, `reject`. Supports multi-process workflows — creates `SeqCounter` from last event seq for safe concurrent appending.

---

## 5. Live Execution Demo

On March 3, 2026, we ran a **hedge fund research pipeline** — 5 agents, 6 tasks, fully autonomous with real Claude Code instances.

### Workflow DAG

```
fundamentals ──┐
               ├──→ risk_assessment ──→ review_gate ──→ recommendation
technicals ────┘         ↑
                         │
macro_scan ──────────────┘
```

### Execution Timeline

```
[15:33:45] START fundamentals (fundamental_analyst / tier2)
[15:33:45] START technicals (technical_analyst / tier2)
[15:33:45] START macro_scan (macro_analyst / tier2)
           ... 3 agents researching in parallel ...
           ... web searches, file reads, analysis writing ...
[15:36:05] DONE  technicals     tokens=5195  cost=$0.30  time=139s
[15:36:32] DONE  macro_scan     tokens=6470  cost=$0.38  time=167s
[15:36:41] DONE  fundamentals   tokens=7943  cost=$0.44  time=175s
[15:36:41] START risk_assessment (risk_analyst / tier2)
           ... synthesizing 3 reports via structured handoff ...
[15:38:32] DONE  risk_assessment tokens=4702  cost=$0.24  time=111s
[15:38:32] GATE  review_gate — auto-approved
[15:38:32] START recommendation (portfolio_manager / tier2)
           ... reading predecessor contexts, writing final memo ...
[15:41:05] DONE  recommendation  tokens=5763  cost=$0.31  time=153s

Result:    SUCCEEDED
Completed: 6  |  Failed: 0  |  Skipped: 0
Wall time: 440s  |  Total cost: ~$1.67
```

### What the System Produced

| File | Size | Content |
|------|------|---------|
| `fundamentals/fundamentals.md` | ~4,000 words | Revenue trends, margins, P/E, balance sheet, competitive position |
| `technicals/technicals.md` | ~3,000 words | Moving averages, RSI, MACD, support/resistance, volume analysis |
| `macro/macro.md` | ~3,500 words | AI capex cycle, export controls, Fed policy, semiconductor cycle, ASIC competition |
| `synthesis/risk_assessment.md` | ~2,500 words | Cross-analyst synthesis, top 3 risks, top 3 catalysts, conviction score 7/10 |
| `synthesis/recommendation.md` | ~4,500 words | Full investment memo: thesis, position sizing, entry/exit criteria, price targets |

### Excerpts from Agent Outputs

The following are selected excerpts from the actual files produced by the agents. No human edited or post-processed these — each agent received a task prompt, executed autonomously, and produced its output.

#### Fundamental Analyst — Revenue Analysis

The fundamental analyst constructed detailed financial tables from web research:

> | Fiscal Year | Revenue ($B) | YoY Growth |
> |-------------|-------------|------------|
> | FY2024      | $60.9       | +126%      |
> | FY2025      | $130.5      | +114%      |
> | FY2026      | $215.9      | +65%       |
>
> The deceleration from triple-digit to ~65% growth in FY2026 reflects base effects, not demand erosion. Q4 FY2026 actually re-accelerated to 73% YoY, and Q1 FY2027 guidance of $78.0B (+/- 2%) implies continued sequential momentum.
>
> **Key takeaway:** Revenue has compounded at a ~97% CAGR over the last three fiscal years. While growth is normalizing, the absolute dollar increments remain massive — NVIDIA added ~$85B in revenue in FY2026 alone.

The agent also produced a peer valuation comparison showing NVIDIA at ~22x forward P/E vs AMD (~24x) and Broadcom (~25x), and a competitive moat assessment of the CUDA ecosystem's 4M+ developers and 20 years of software investment.

#### Technical Analyst — Pattern Recognition

The technical analyst identified specific chart formations and price levels:

> **Active MACD sell signal** — the daily MACD histogram crossed negative, confirming bearish momentum
>
> **Head-and-shoulders formation** on the weekly chart with neckline at $170-$175, coinciding with the 200-day SMA — a critical support confluence
>
> **Distribution volume** — post-earnings selloffs on beat-and-raise quarters are a late-cycle warning sign

*(This agent produced ~3,000 words of technical analysis including support/resistance levels, RSI readings, and volume analysis.)*

#### Macro Analyst — AI Capex Cycle

The macro analyst provided hyperscaler spending projections with specific company commitments:

> | Year | Top-5 Hyperscaler Capex | YoY Growth |
> |------|------------------------|------------|
> | 2024 | ~$256B | +63% |
> | 2025 | ~$443B | +73% |
> | 2026E | ~$602B | +36% |
>
> Individual commitments are staggering. Amazon leads with $200B projected for 2026 (up from $131B in 2025). Meta plans up to $135B (from $72B). Google has signaled as much as $185B (from $91B). Capital intensity ratios have reached historically unprecedented levels: 57% for Oracle, 45% for Microsoft.
>
> **Key risk:** The YoY growth rate is already decelerating (73% → 36%). Jensen Huang has framed the $700B annual spend as "just the start," but the financing side is stressed — hyperscaler debt issuance reached $108B in 2025 with projections of $1.5T required through 2030.

#### Risk Analyst — Cross-Agent Synthesis

This is where structured handoffs prove their value. The risk analyst received `TaskOutput` from all three parallel agents and produced a synthesis that identifies **where the analysts agree and disagree**:

> **Analyst Agreement Matrix**
>
> | Topic | Fundamentals | Technicals | Macro | Consensus |
> |-------|-------------|------------|-------|-----------|
> | Revenue growth trajectory | Strong (97% 3Y CAGR) | N/A | Strong (+65% YoY FY26) | **Aligned** |
> | Valuation | Reasonable (~22x fwd) | N/A | Reasonable (~23x fwd) | **Aligned** |
> | Near-term price direction | Implicitly bullish | **Bearish** (H&S, MACD sell) | Favorable for 2026 | **DISAGREEMENT** |
>
> **Key Contradiction:** The most significant disagreement is between the fundamentals/macro analysts (both constructive) and the technical analyst (bearish near-term). Fundamentals point to a $5.4B Q1 FY2027 guidance beat and $500B+ backlog as reasons for optimism. The technical analyst counters that the stock *sold off on good earnings*, volume patterns show institutional distribution, and a weekly head-and-shoulders pattern threatens a move to $170-$175.

The risk analyst also produced a weighted conviction score:

> | Factor | Score | Weight | Contribution |
> |--------|-------|--------|-------------|
> | Fundamental quality | 9/10 | 30% | 2.7 |
> | Valuation | 7/10 | 20% | 1.4 |
> | Macro support | 7/10 | 20% | 1.4 |
> | Technical setup | 4/10 | 15% | 0.6 |
> | Competitive moat durability | 7/10 | 15% | 1.05 |
> | **Weighted Total** | | | **7.15 → 7** |

#### Portfolio Manager — Final Recommendation

The portfolio manager received all predecessor contexts and produced a complete investment memo. Key sections include tiered entry strategy, stop-loss framework, and monitoring metrics:

> **Entry Strategy — Tiered Accumulation**
>
> | Tranche | Entry Zone | % of Target Position | Trigger |
> |---|---|---|---|
> | Tranche 1 | $178-$183 | 40% | Initiate at current levels |
> | Tranche 2 | $170-$175 | 35% | Add on test of 200-day SMA / H&S neckline |
> | Tranche 3 | $155-$162 | 25% | Aggressive accumulation on confirmed H&S breakdown |
>
> **Stop-Loss Framework**
>
> | Type | Level | Action |
> |---|---|---|
> | Technical stop | Weekly close below $165 | Reduce position by 50% |
> | Fundamental stop | Any hyperscaler capex guide-down >10% | Reassess entire thesis |
> | Hard stop | Weekly close below $148 | Exit to benchmark weight |

The PM also produced hedging recommendations — a Broadcom pair trade for ASIC risk, a $175/$155 put spread, and a collar strategy — and a comparison to Street consensus:

> | | Our View | Street Consensus | Variance |
> |---|---|---|---|
> | 12-month target | $210-$230 | $178 (median) | Above consensus |
> | Key risk | AI capex ROI scrutiny | Geopolitics / export controls | We weight capex sustainability higher |
> | Timeline concern | 2H 2027 capex deceleration | 2028+ ASIC competition | We see capex risk as more imminent |

### Why These Excerpts Matter

The quality of output is not the point — that comes from the underlying LLM. What AgentOS demonstrates here is:

1. **Parallel specialization works.** Three agents researched simultaneously without interference, each scoped to their own workspace, producing complementary analysis.
2. **Structured handoffs enable synthesis.** The risk analyst didn't just read files — it received typed `TaskOutput` objects with findings and confidence levels, enabling it to build a formal agreement matrix and identify contradictions.
3. **Context chains through the DAG.** The portfolio manager referenced specific numbers from the fundamental analyst ($97B FCF, 75% margins), patterns from the technical analyst (H&S neckline at $175), and projections from the macro analyst ($600B hyperscaler capex) — all mediated through AgentOS's predecessor context mechanism.
4. **Budget governance held.** The entire pipeline cost ~$1.67 and completed in ~440 seconds, well within the $5 / 1800s workflow budget.

### Structured Handoff Example

The risk analyst received this from the fundamental analyst via `TaskOutput`:

```json
{
  "task_id": "fundamentals",
  "status": "succeeded",
  "summary": "Comprehensive fundamental equity analysis of NVIDIA (NVDA)...",
  "key_findings": [
    {"finding": "Revenue grew 65% YoY to $215.9B in FY2026",
     "confidence": "high", "sources": []},
    {"finding": "Gross margins stable at 75% despite Blackwell ramp",
     "confidence": "high", "sources": []},
    ...
  ],
  "open_questions": [],
  "metrics": {"tokens_consumed": 7943, "estimated_cost_usd": 0.4385}
}
```

The portfolio manager then read the risk assessment plus all three upstream contexts from `.agentos_context/` and produced a coherent 4,500-word investment recommendation with entry zones, stop-losses, and monitoring metrics — all referencing specific findings from the parallel research phase.

### Event Log

Every state transition, budget consumption, and task output was recorded:

```
seq= 0  workflow.started
seq= 1  task.state_changed       fundamentals  pending→running
seq= 2  task.state_changed       technicals    pending→running
seq= 3  task.state_changed       macro_scan    pending→running
seq= 4  budget.consumed          (technicals)
seq= 5  task.state_changed       technicals    running→succeeded
seq= 6  task.output_produced     technicals
seq= 7  budget.consumed          (macro_scan)
...
seq=17  task.output_produced     recommendation
seq=18  workflow.completed       status=succeeded
```

The entire workflow can be replayed from this log: `agentos replay /tmp/hedge.db <workflow-id>`.

---

## 6. V1 Success Criteria Assessment

The V1 Scope defined seven success criteria. Here is the honest status of each:

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | **Demo works reliably (10 consecutive runs)** | **Partially demonstrated** | The hedge fund demo (5 agents, 6 tasks) completed successfully. Single successful run documented. The 10-consecutive-run criterion has not yet been formally executed — this needs to be run and documented before claiming reliability. |
| 2 | **Event log completeness** | **Demonstrated** | 18-event sequence from hedge fund run shows full lifecycle. `agentos replay` reconstructs complete state. |
| 3 | **Budget enforcement is hard** | **Demonstrated** | Pipeline stayed within $5 / 1800s budget. Earlier testing showed `BudgetExceededError` raised and task marked FAILED when a 20K-token budget was exceeded by actual usage (32,614 tokens). `BUDGET_EXCEEDED` event emitted. |
| 4 | **Security boundaries hold** | **Demonstrated in tests** | 4 adversarial security tests confirm: path traversal (`../../etc/shadow`) blocked, reads outside workspace (`/etc/passwd`) blocked, network exfiltration to unauthorized domains blocked, tool escalation (file_read agent attempts shell_exec) blocked. Multi-agent isolation tested — agents cannot access each other's scoped paths. Secret values confirmed absent from all event payloads. See `tests/integration/test_capability_enforcement.py`. |
| 5 | **Workflow authoring (3 examples, <30 min)** | **Exceeded target** | 5 example YAML files shipped. No Getting Started documentation yet — this is the primary gap for developer onboarding. |
| 6 | **5 external users with meaningful usage** | **Not yet started** | No external users have tested the system. This depends on documentation and outreach, both of which are next priorities. |
| 7 | **Test coverage 90%+** | **85%** | Kernel and schemas at 97-100%. Shortfall is in CLI live-execution paths (47-54%) and Tier 2 streaming code (65%), which require real subprocesses. The governance core is exhaustively tested. |

### Tier 2 Manifest Compliance

In all live test runs (single-task, 2-task pipeline, 6-task hedge fund pipeline), every Tier 2 agent produced a valid `manifest.json` on the first attempt — **0 retries needed across 10+ task executions**. The `MAX_MANIFEST_RETRIES = 2` retry mechanism exists but has not been triggered in practice. This suggests the manifest instruction in the system prompt is reliably followed by Claude Code, though more runs are needed to establish a statistically meaningful compliance rate.

### Adversarial Validation — Honest Assessment

The `AdversarialValidator` module (179 lines) provides **infrastructure for adversarial validation, not full adversarial validation itself**:

- The **default validator** (`_default_validate`) performs structural checks: summary exists, findings have content, status is succeeded. This is schema validation, not independent verification of claims.
- The module is designed with **dependency injection** — `validate_fn` accepts any callable, including an LLM-backed verifier that would independently challenge claims against source data. The tests confirm this injection mechanism works, including retry-on-failure logic.
- A `check_model_separation()` utility warns when producer and validator use the same model, enforcing the principle that adversarial validation requires independent verification.
- **What has not been demonstrated:** A live run with a different model backend performing genuine content-level verification. The infrastructure exists; the "adversarial" part — an independent model challenging another model's findings — has not been wired into a live workflow.

This is partially implemented. The next step is wiring a Tier 1 adapter with a different model (e.g., GPT-4o) as the validation agent in a workflow that includes an adversarial validation node.

---

## 7. What Works

- **Parallel DAG execution** with dependency resolution and cascade failure
- **Real LLM execution** via both Tier 1 (API) and Tier 2 (Claude Code CLI)
- **Structured inter-agent handoffs** with findings, confidence, and open questions
- **Hard budget enforcement** that halts tasks cleanly on any dimension exceeded
- **Real-time streaming output** showing each agent's tool calls, searches, and writes as they happen
- **Event-sourced audit trail** — every state change persisted, full replay capability
- **Pause/resume** — workflows can pause at approval gates and resume after human resolution
- **Interactive gate prompts** — `--interactive` flag enables manual approve/reject at gates in live mode
- **Static workflow verification** — 8 pre-execution checks catch errors before any LLM call
- **Capability-based security** for Tier 1 agents — adversarially tested (path traversal, exfiltration, tool escalation all blocked)
- **Secret store** with capability-gated access (values never logged, confirmed via event audit)
- **581 passing tests** at 85% coverage (kernel 97-100%)

---

## 8. Known Limitations (V1)

1. **Budget time tracking in Tier 2** — The adapter reports cumulative elapsed time as a delta on each API call, which can overcount when retries occur. The budget still enforces correctly, but the numbers can be inflated. **Fix plan:** Track cumulative time in the adapter and compute deltas from the difference between calls, not from absolute elapsed time.

2. **Tier 1 tool handlers** — `shell_exec` and `web_search` return stubs in the default handler. A real deployment needs custom tool handlers injected via the `tool_handler` parameter.

3. **No Agent SDK integration yet** — Tier 2 uses `subprocess.Popen` to launch Claude Code. The structured output protocol relies on instructing the agent via system prompt to produce `manifest.json`, validated post-hoc with up to 2 retries. In practice the compliance rate has been 100% (0 retries across 10+ tasks), but migrating to the Claude Agent SDK would provide structured output natively and eliminate this dependency on prompt compliance.

4. **No persistent adapter state** — Tier 2 adapters don't resume Claude Code sessions across workflow restarts. Each task invocation is a fresh subprocess.

5. **Single-node execution** — The thread-pool executor runs on one machine. No distributed scheduling.

6. **No documentation** — The V1 plan specified three documents: Getting Started guide, Adapter Development guide, Workflow Authoring guide. None have been written. This is the primary blocker for the "5 external users" success criterion.

7. **10-consecutive-run reliability not formally tested** — The system has been tested across multiple runs with varying configurations, but the specific "10 consecutive runs with 0 failures" criterion has not been formally executed and documented.

---

## 8. Sprint History

| Sprint | Commit | What Shipped |
|--------|--------|-------------|
| 0 | `cc3b1e6` | Project scaffolding, task/event schemas, SeqCounter |
| 1 | `4717c85` | EventLog, SQLiteEventLog, TaskStateMachine |
| 2 | `7847bbe` | `agentos demo` command for end-to-end execution |
| 3 | `2816ff9` | DAG executor, budget manager, workflow schemas, examples |
| 4 | `6d7cb12` | Workspace, Tier 1 adapter, integration |
| 5 | `0773a54` | Gate manager, full CLI commands, e2e demo tests |
| 6 | `00e47e5` | Tier 2 Claude Code adapter with mocked subprocess tests |
| 7 | `a726d3f` | WorkflowVerifier, structured handoffs through DAG executor |
| 8 | `ce50420` | Workflow pause/resume, public demo |
| 9 | `7da8eb2` | Capability-based security, secret store |
| 10 | `dee1160` | Adversarial validation, agent lifecycle manager |
| 11 | `eae7739` | WorkflowReplayer, replay CLI command |
| 12 | `a94d6a8` | DevOps pipeline, load tests, V1 launch criteria |
| Live | (dev) | Real adapter wiring, streaming output, hedge fund demo |

---

## 9. How to Run

```bash
# Install
pip install -e .

# Verify a workflow
agentos workflow verify examples/hedge_fund_research.yaml

# Run with stubs (no API key needed)
agentos workflow run examples/linear_research.yaml

# Run with real adapters (Tier 2, no API key needed)
agentos workflow run examples/hedge_fund_research.yaml --live --db /tmp/run.db

# Run with interactive gate approval (manual approve/reject at each gate)
agentos workflow run examples/hedge_fund_research.yaml --live --interactive --db /tmp/run.db

# Run with real adapters (Tier 1, needs API key)
export ANTHROPIC_API_KEY=sk-ant-...
agentos workflow run examples/linear_research.yaml --live --db /tmp/run.db

# Inspect results
agentos replay /tmp/run.db <workflow-id>
agentos cost /tmp/run.db
agentos events /tmp/run.db

# Gate management (for paused workflows)
agentos gate list --db /tmp/run.db
agentos gate approve <gate-id> --db /tmp/run.db --reviewer "your-name"
agentos workflow resume examples/workflow.yaml <workflow-id> --db /tmp/run.db

# Run tests
pytest tests/ -v
```

---

*Generated from codebase analysis on March 3, 2026. 2,413 statements across 35 modules, 10,213 lines of tests, 581 passing tests at 85% coverage (kernel 97-100%), 5 example workflows, and one successful 5-agent live demo producing a complete NVIDIA investment recommendation at $1.67 total cost.*
