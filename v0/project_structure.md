Excellent. I will now rewrite the **complete implementation guide** as if I am a senior AI systems engineer working alongside a PhD researcher. This version integrates:

* The architectural constraints we defined
* The separation guarantees (AgentOS vs LabOS)
* The event-sourced kernel philosophy
* Budget-constrained cognition
* Evaluation-first discipline
* Reproducibility rigor
* GitFlow enforcement
* Production-grade engineering standards

This is not a brainstorm document.
This is an executable engineering blueprint.

---

# AGENTOS + LABOS

## Complete Implementation Guide (Engineering + Research Grade)

---

# 0. Mission Statement

We are building:

**AgentOS** — a domain-agnostic cognitive execution substrate
**LabOS** — an open-source research domain built on AgentOS

AgentOS is the product backbone.
LabOS is a reference implementation proving correctness and extensibility.

Future domains (e.g., FinanceResearchOS) must plug into AgentOS without modifying its internals.

This system must satisfy:

* Architectural separation
* Deterministic execution (best-effort)
* Budget-constrained autonomy
* Strict tool typing
* Event-sourced auditability
* Reproducibility-first research discipline
* GitFlow governance

---

# 1. Repository Structure

Monorepo with strict package boundaries:

```
agentos-monorepo/
│
├── packages/
│   ├── agentos/
│   └── labos/
│
├── examples/
│   └── labos_ml_replication/
│
├── docs/
│   ├── architecture.md
│   ├── agentos_api.md
│   ├── labos_spec.md
│   └── evaluation_protocol.md
│
├── tests/
│   ├── integration/
│   └── e2e/
│
└── pyproject.toml
```

Hard rule:

* `agentos` must never import `labos`
* `labos` depends on `agentos`
* CI must enforce this

---

# 2. Architectural Philosophy

## 2.1 Separation of Concerns

AgentOS provides:

* Workflow runtime
* Tool substrate
* Budget governance
* Concurrency control
* Event log
* Replay
* Memory primitives
* Provenance framework
* Evaluation harness

LabOS provides:

* Research ontology
* Domain schemas
* Domain workflows
* Research tools
* Statistical discipline
* Reproducibility metadata
* Domain evaluation suite

AgentOS contains no domain knowledge.

---

## 2.2 Event-Sourced Execution Model

All runs are append-only event streams.

Nothing mutates silently.

Every:

* Task start
* Task finish
* Tool call
* Budget update
* Permission decision
* Artifact creation

… must generate a structured event.

State is derived from events.

Replay must reconstruct behavior from events.

---

## 2.3 Budget-Constrained Cognition

Autonomy is bounded.

Every workflow enforces:

* Max tokens
* Max tool calls
* Max recursion depth
* Max parallel tasks
* Max execution time

Budget enforcement must halt execution cleanly and log the violation.

---

## 2.4 Typed Tool Interface

Tools are system calls.

Each tool must define:

* Input schema (Pydantic)
* Output schema (Pydantic)
* Side-effect classification
* Cost estimate (optional but preferred)

All tool calls must be validated before execution.

No dynamic dict passing.

---

# 3. AgentOS Implementation

---

# 3.1 Package Layout

```
packages/agentos/agentos/

core/
schemas/
runtime/
tools/
governance/
memory/
integrity/
observability/
eval/
```

---

# 3.2 Implementation Order

We follow strict phased development.

---

# PHASE 1 — Kernel Foundation

## Step 1 — Core Identifiers & Errors

Implement:

* RunId
* TaskId
* ToolCallId
* ArtifactId

Standardize UUID generation.

Define structured error hierarchy:

* BudgetExceededError
* ToolValidationError
* TaskExecutionError
* PermissionDeniedError

---

## Step 2 — Schemas (Typed Everything)

Define Pydantic models for:

### Budget

* BudgetSpec
* BudgetUsage
* BudgetDelta

### Events

* BaseEvent
* RunStarted
* RunFinished
* TaskStarted
* TaskFinished
* ToolCallStarted
* ToolCallFinished
* BudgetUpdated
* PolicyDecision
* ArtifactCreated

### ToolCallRecord

* tool name
* version
* input hash
* output hash
* timestamps
* success flag

### ArtifactMeta

* id
* path
* sha256
* produced_by_task
* mime type

All schemas must be JSON-serializable.

---

## Step 3 — Event Log (SQLite)

Implement:

* EventLog interface
* SQLiteEventLog implementation

Table:

```
events(
    run_id TEXT,
    seq INTEGER,
    timestamp TEXT,
    event_type TEXT,
    payload_json TEXT
)
```

Events must be strictly ordered by sequence.

No mutable state outside event log.

---

## Step 4 — Tool Substrate

Implement:

* Base Tool class
* Tool registry
* Input/output schema validation
* Side-effect classification

Tool execution must:

1. Emit ToolCallStarted
2. Validate input
3. Execute
4. Hash output
5. Emit ToolCallFinished

---

## Step 5 — Workflow Runtime (Linear First)

Implement:

* TaskNode
* Workflow (initially linear)
* Executor

Add state machine:

```
PENDING → RUNNING → SUCCEEDED/FAILED
```

Emit events for all transitions.

---

# PHASE 2 — Governance & DAG Support

## Step 6 — DAG Execution

Upgrade workflow to DAG:

* Dependency graph
* Topological scheduling
* Parallel branch support (controlled)

---

## Step 7 — Budget Manager

Before every:

* Task execution
* Tool call

Check budget constraints.

If exceeded:

* Emit BudgetExceeded event
* Abort workflow safely

---

## Step 8 — Concurrency Control

Implement:

* Max parallel tasks
* Per-tool concurrency limits
* Semaphore-based limiter

---

## Step 9 — Stop Conditions

Implement detection for:

* Recursion depth exceeded
* Repeated identical tool calls
* Excessive failure loops
* No-progress state

Stop must generate event.

---

## Step 10 — Permissions Engine

Tool calls must be evaluated against:

* Side-effect policy
* User permission config

Emit PolicyDecision event.

---

# PHASE 3 — Observability & Replay

## Step 11 — Deterministic Hashing

Canonical JSON serialization.
Stable sha256 for:

* Tool inputs
* Tool outputs
* Artifacts

---

## Step 12 — Replay Engine

Implement:

* Replay run from event log
* Option to:

  * Mock tool outputs (strict replay)
  * Re-execute deterministic tools

Replay must regenerate final artifacts if allowed.

---

# PHASE 4 — Memory & Integrity

## Step 13 — Episodic Store

Derive run summaries from event log.

---

## Step 14 — Semantic Store

Store structured facts with provenance.

Conflicts are allowed but flagged.

---

## Step 15 — Context Pack

Build evidence packs with:

* Claims
* Supporting evidence
* Freshness score
* Conflict markers

---

# PHASE 5 — Evaluation Harness

Implement:

* EvalCase abstraction
* EvalRunner
* Metrics:

  * success rate
  * cost usage
  * latency
  * provenance coverage
  * failure types

AgentOS must expose evaluation hooks.

---

# 4. LabOS Implementation

LabOS must use only public AgentOS APIs.

---

# 4.1 LabOS Structure

```
packages/labos/labos/

domain/schemas/
tools/
workflows/
eval/
```

---

# 4.2 LabOS MVP: ML Replication

Scope tightly:

* One dataset
* One baseline model
* One metric
* One plot
* One report

---

## Tools

* DatasetTool (download + checksum)
* PythonRunner (train model with fixed seed)
* PlotTool (generate PNG)
* ReportTool (generate markdown)
* ReviewerTool (validate reproducibility metadata)

---

## Workflow

DAG:

1. DefineQuestion
2. DesignExperiment
3. RunExperiment
4. AnalyzeResults
5. WriteReport
6. ReviewerCheck

All artifacts must be hash-stamped.

---

## Reproducibility Contract

Each run must record:

* Random seed
* Dataset checksum
* Config hash
* Environment spec
* Code version (if applicable)

Reviewer must fail if any missing.

---

# 5. GitFlow Workflow (Mandatory)

Branching model:

* main → production releases
* develop → integration branch
* feature/* → feature development
* release/* → release preparation
* hotfix/* → urgent production fixes

Rules:

* No direct commits to main
* No direct commits to develop
* All features in feature branches
* Atomic commits
* Conventional commit messages

CI must:

* Run tests
* Enforce type checking
* Enforce separation of packages
* Prevent agentos importing labos

---

# 6. Quality Gates Before Expansion

Before building FinanceResearchOS:

AgentOS must demonstrate:

* Stable replay
* Deterministic artifact hashing
* Budget enforcement
* DAG execution correctness
* Provenance tracking
* Passing LabOS evaluation suite

Only after these pass can new domains be added.

---

# 7. Non-Negotiable Engineering Rules

You must never:

* Introduce domain terms into AgentOS
* Bypass tool schema validation
* Store hidden mutable state
* Allow silent failures
* Skip event logging

You must always:

* Log everything
* Enforce budgets
* Enforce permissions
* Maintain reproducibility discipline
* Preserve abstraction boundaries

---

# 8. Final Objective

By completion of this implementation:

* AgentOS functions as a reusable cognitive execution substrate
* LabOS demonstrates scientific workflow automation
* The architecture cleanly supports future domain packs
* The system is reproducible, inspectable, and extensible

This is not an AI assistant.
This is a cognitive operating system kernel.

Engineering discipline is paramount.

---

If you would like, next I can:

* Write the precise AgentOS public API specification
* Define the exact Pydantic schemas
* Or generate the first GitFlow branch breakdown plan for initial implementation
