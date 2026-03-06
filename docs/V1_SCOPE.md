# AgentOS — V1 Scope and Roadmap

This document defines what V1 of AgentOS includes, what it explicitly defers, and the milestones for getting there. The overriding principle is scope discipline: V1 earns credibility by doing one thing exceptionally well rather than many things adequately.

**A note on feature maturity**: Some features described in this document and in the broader project overview are well-understood and ready to implement. Others — particularly those in the deferred features table and the "open research areas" section below — are preliminary ideas that will require additional research, prototyping, and discussion before their design is finalized. These features are included to show the direction of the project, not to commit to a specific implementation. As development progresses and each feature enters its development phase, it will be discussed in detail with the people providing technical and business feedback to validate the approach, refine the design, or adjust scope based on what we learn from building and using earlier features.

## Target User

**Technical users only.** Software engineers, DevOps engineers, and engineering leads who are already using coding agents (Claude Code, Codex) individually and want to orchestrate, monitor, and govern them.

V1 interfaces: CLI, YAML/JSON configuration files, programmatic REST API.

Not in V1: Visual workflow builder, drag-and-drop canvas, non-technical user interface. These are V2 milestones that require UX research informed by real V1 usage patterns.

## Agent Class

**Coding and engineering agents.** This is the agent class with the most mature tooling, the clearest demand, and the fastest adoption cycle. The framework is designed to be agent-class agnostic, but V1 focuses development, testing, and documentation on engineering workflows.

## Runtime Model

**Locally managed processes.** Agents run as processes on the user's machine, managed by AgentOS. No cloud sandbox orchestration, no remote agent management in V1. The architecture supports future expansion to containers, remote servers, and cloud sandboxes, but V1 keeps the runtime model simple and fully local.

## Adapter Tiers

**Tier 1 (fully controlled) — priority.** AgentOS's own agent runtime and API-based agents where AgentOS controls the tool-calling loop. Full capability enforcement, full observability, full lifecycle management.

**Tier 2 (semi-controlled) — priority.** Claude Code integration as the flagship Tier 2 adapter. This must be deeply reliable — not a best-effort wrapper, but a production-grade integration that provides meaningful orchestration, monitoring, and task assignment. V1 credibility depends on this. If the only reliable agents are Tier 1 (which are essentially prompt chains), the Layer 2 positioning weakens. Achieving a strong Tier 2 Claude Code adapter may require engaging with Anthropic's developer relations for stable embedding APIs or extension points.

**Tier 3 (best-effort) — experimental.** Wrappers for other CLIs and tools. Explicitly marked as experimental, not recommended for production workflows. Available for exploration and community contribution.

### Claude Code Adapter Contingency

The Tier 2 Claude Code adapter is critical for V1 credibility, but depends on Claude Code's CLI interface remaining stable and scriptable. If Anthropic changes the CLI interface, restricts programmatic access, or deprecates embedding capabilities, the fallback plan is:

1. **Immediate fallback**: Use Claude API directly as a Tier 1 agent (AgentOS controls the tool-calling loop). This sacrifices the "orchestrating real autonomous runtimes" positioning but preserves a working product.
2. **Parallel investment**: Build Codex (OpenAI) adapter to Tier 2 quality. Having two Tier 2 adapters eliminates single-provider dependency.
3. **Relationship**: Engage Anthropic developer relations early. Position AgentOS as driving Claude Code adoption in enterprise settings — making their product more deployable increases their API revenue.

The architecture must ensure that no core feature (DAG execution, gates, budget enforcement, event log) depends on any specific adapter. Adapters are pluggable; the kernel works regardless.

## Core Features (In V1)

### Event-Sourced State

- Append-only SQLite event log as the single source of truth
- All state derived from events — no mutable state outside the log
- Queryable event log via SQL for technical users
- Event replay for state reconstruction and crash recovery

### DAG Workflow Engine

- Directed acyclic graph executor with topological scheduling
- Linear, parallel, fan-out/fan-in execution patterns
- Task state machine: PENDING → RUNNING → SUCCEEDED/FAILED/WAITING
- Controlled parallelism with configurable concurrency limits

### Workflow Verification

- Static analysis of DAGs before execution
- Checks: circular dependencies, permission sufficiency, budget adequacy, orphan dependencies
- Verification report available via CLI before workflow runs

### Approval Gates and Human-in-the-Loop

- Approval gates on edges between tasks
- Human input nodes for mid-workflow user input
- Pause/resume at any point
- Gate resolution via API (enabling future UI integration)

### Adversarial Validation Nodes

- Validator node type as a native workflow primitive
- Receives predecessor output, independently verifies claims
- Produces validation report with pass/fail and confidence
- On failure: triggers retry, revision loop, or human gate

### Structured Task Output Protocol

- JSON schema for task outputs: key findings, confidence levels, data sources, open questions, file references
- Downstream agents receive organized context, not raw file dumps
- Enforcement differs by adapter tier:
  - **Tier 1** (fully controlled): Enforced directly — AgentOS controls the tool-calling loop and uses structured output features (tool use, JSON mode) to guarantee schema compliance
  - **Tier 2** (semi-controlled): Best-effort with validation — the agent is instructed to produce a JSON manifest file alongside its regular output; AgentOS validates the manifest post-hoc and rejects non-conforming outputs (triggering retry or human gate)
  - If a Tier 2 agent fails to produce a conforming manifest after retries, the task is marked as requiring human review rather than silently passing unstructured output downstream

### Workspace Management

- Scoped workspaces per team
- File change tracking with event emission
- File manifest: who created what, when, in what context
- Predecessor file context injected into downstream agent prompts

### Budget and Governance

- Per-agent, per-team, per-workflow budget limits
- Token, API call, time, and cost constraints
- Hard enforcement — exceeding budget halts execution cleanly
- Budget events in the log for cost monitoring

### Security (Orchestration Layer)

- Capability-based permission model (tool allowlists, workspace scoping, domain whitelists)
- Enforcement at the orchestration layer for Tier 1 agents (tool call interception)
- Workspace-level isolation between teams
- Secrets store for credential management — credentials injected at runtime, never in logs or prompts
- Full audit trail via event log

### Observability

- CLI: `agentos status`, `agentos events`, `agentos cost`
- Real-time event streaming
- Per-agent, per-team, per-workflow cost dashboards (CLI output)
- Basic deterministic replay: inspect event log to reconstruct execution history

### Agent Lifecycle

- Spawn, monitor, stop agent instances
- Fresh restart with curated briefing (not context resume)
- Configurable lifecycle policies: restart on token threshold, turn count, or time limit

### CLI Interface

- `agentos workflow run <file>` — run a workflow from YAML/JSON
- `agentos workflow verify <file>` — static verification before execution
- `agentos status` — current execution state
- `agentos events [--follow]` — event stream
- `agentos cost` — budget consumption
- `agentos gate list` — pending approval gates
- `agentos gate approve/reject <id>` — resolve gates
- `agentos agent restart <id>` — fresh restart

## Explicitly Deferred (Not in V1)

| Feature | Target Version | Rationale |
|---------|---------------|-----------|
| Visual workflow builder | V2 | Requires UX research, stable backend |
| Non-technical user interface | V2 | Depends on visual builder |
| Message channels / async communication | V2 | DAG model sufficient for V1 workflows |
| Manager agent for message routing | V2+ | Depends on channel infrastructure |
| Sandbox-level security (containers, seccomp) | V2 | Orchestration-layer enforcement sufficient for V1 |
| Runtime-verified policy for Tier 2/3 agents | V2 | Requires sandbox infrastructure |
| Dynamic team composition at runtime | V3 | Architecturally complex, requires mature workflow engine |
| Cross-run memory / persistent knowledge bases | V2+ | Requires knowledge infrastructure design |
| Knowledge graphs / advanced RAG | V3+ | Research-grade, needs experimentation |
| Fine-tuning pipelines | V3+ | Requires significant data accumulation |
| Agent Safety Score | V2 | Requires full security infrastructure |
| Benchmarking engine | V2+ | Requires significant usage data |
| Multi-user deployment | V2 | Local-first is sufficient for initial users |
| Web dashboard (read-only monitoring) | V1.5 | Can be added once API is stable |
| Conditional branching in DAGs | Done | Implemented in V1.5 — condition evaluator, conditional edges in DAG executor |
| Review/revision loops | Done | Implemented in V1.5 — native revision loops with `max_revisions` support |

### Open Research Areas

Several features listed above — and discussed in more detail in the Project Overview — involve problems that do not yet have well-established solutions in the industry. These are areas where the right approach will become clearer as we build the foundation, gain real usage data, and consult with technical advisors. Examples:

- **Context management and agent degradation**: How to detect when an agent's context window is becoming saturated and its output quality is declining ("spoiled" agents). V1 uses pragmatic policy-based lifecycle management (restart on token threshold, turn count, or time limit), but more sophisticated approaches — automated quality degradation detection, intelligent context pruning, seamless context handoff between agent restarts — require research and experimentation. The right design will depend on what we learn from running real workflows and observing where agents actually fail.

- **Cross-run memory and knowledge persistence**: How agents retain useful information across workflow runs. This intersects with active research in RAG, vector stores, and episodic memory. The event log provides a foundation (everything is recorded), but turning that into useful agent memory is a design problem we will address after V1 is stable.

- **Dynamic team composition**: Allowing workflows to spawn or reassign agents at runtime based on intermediate results. This is architecturally complex and the right abstraction will depend on the workflow patterns that emerge from real V1 usage.

- **Agent safety scoring**: Quantifying the risk profile of an agent configuration. The inputs are clear (permission scope, isolation level, budget constraints), but the scoring model requires calibration against real incidents and near-misses.

These are not abandoned — they are intentionally deferred to the development phase where they become relevant. When each comes up, the approach will be discussed in detail with the people providing technical and business feedback, refined based on what we've learned from earlier phases, and scoped concretely before implementation begins.

### V1.5 Definition

V1.5 is not a separate release — it is the set of features added in the 2-3 months immediately following V1 launch, informed by early adopter feedback. V1.5 is when the product transitions from "working framework" to "usable product for daily workflows."

**V1.5 scope** (month 7-9):
- **Read-only web dashboard**: Real-time session monitoring, event log viewer, cost charts. No workflow builder — CLI remains the authoring interface.
- ~~**Conditional branching in DAGs**~~: **Done.** If/else edges based on task output, with a `ConditionEvaluator` supporting field access, comparisons, and boolean logic. 4 example workflows demonstrate conditional patterns.
- ~~**Review/revision loops**~~: **Done.** Native `max_revisions` on task nodes, automatic re-routing with feedback on gate rejection or validation failure.
- **Consultation tasks** (added): A new collaborative primitive allowing agents to request mid-workflow input from other agents without a full task handoff. Enables code review loops and expert consultation patterns.
- **Second Tier 2 adapter**: Codex or another autonomous agent tool at production-grade quality.

**Remaining V1.5 work:**
- Read-only web dashboard
- Second Tier 2 adapter (Codex or equivalent)

V1.5 is scoped small intentionally — it should be 4-6 weeks of focused development, not a second V1.

## First Demo Milestone

The first working demo that proves the concept:

**Two Claude Code instances collaborating on a software task with an approval gate between them.**

Specifically:

1. Agent A (Researcher): receives a task description, analyzes requirements, produces a structured research document with findings, recommendations, and file references.
2. Approval Gate: user reviews the research output. Approve to continue, reject with feedback.
3. Agent B (Implementer): receives the approved research as structured context, implements the solution, produces code files and a summary.

This demo exercises: Tier 2 adapter (Claude Code), DAG execution (two tasks with dependency), structured handoff protocol, approval gate with human review, workspace file tracking, event log, and budget monitoring.

Target: working demo within first 2 months of development.

## 6-Month Milestone Plan

### Month 1-2: Foundation

- Event log (SQLite, append-only, queryable)
- Task state machine and DAG executor
- Workspace management with file tracking
- Budget manager with hard enforcement
- Tier 1 adapter: API-based agent with controlled tool loop
- Basic CLI: run workflow, view status, view events

### Month 3-4: Agent Integration and Gates

- Tier 2 adapter: Claude Code integration (production-grade)
- Approval gates and human input nodes
- Pause/resume
- Structured task output protocol
- Workflow verification (static analysis)
- CLI: gate management, cost reporting, workflow verification

### Month 5-6: Security and Reliability

- Capability-based permission model (orchestration-layer enforcement)
- Secrets store and credential injection
- Adversarial validation nodes
- Agent lifecycle management (restart, lifecycle policies)
- Basic deterministic replay
- DevOps demo workflow: end-to-end engineering pipeline
- Documentation: getting started, adapter development guide, workflow authoring guide

### After 6 Months (V1 Launch)

- Stable CLI-first product targeting engineering teams
- Claude Code as flagship agent integration
- Event-sourced, budget-governed, gate-controlled workflows
- Orchestration-layer security with capability model
- Structured handoffs and adversarial validation
- Ready for customer discovery and early adopter feedback

### Hedge Fund Timeline

The hedge fund product (Phase 3 in the Project Overview) does not compete with V1 for development time. Hedge fund development does not begin until V1 is launched, stable, and validated through early adopter usage. The earliest this enters active scope is month 9-12, and only if the framework has demonstrated sufficient reliability. A dedicated scope document will be produced at that time, informed by what was learned from building the framework and the DevOps demo. Until then, the hedge fund exists as a long-term product vision that shapes architectural decisions (e.g., ensuring the framework handles financial data requirements) but does not consume development resources.

## Resource Plan

V1 is designed to be buildable by a **solo founder-engineer** working full-time over 6 months. The architecture is intentionally scoped to make this feasible:

- **No distributed systems**: Local runtime, SQLite, single-process server. No Kubernetes, no message queues, no cloud infrastructure to manage.
- **No frontend complexity in V1**: CLI-first. The existing React frontend (workspace browser, session dashboard) is bonus, not a requirement.
- **Existing foundation**: The core kernel (event log, DAG executor, task state machine, budget manager, workspace management) is already implemented and tested (~400+ tests). V1 development continues from this base, not from scratch.
- **Python monorepo**: Single language, simple tooling, fast iteration.

The solo-founder constraint is a feature, not a limitation. It enforces scope discipline and prevents architectural bloat. Every feature must justify its inclusion against "can one person build and maintain this?"

If development velocity allows or a co-founder joins:
- **Priority hire #1**: Systems/infrastructure engineer — adapter development, security enforcement, reliability hardening.
- **Priority hire #2**: Developer advocate — documentation, tutorials, community building, conference talks.

## Success Criteria for V1

1. **The demo works reliably**: Two Claude Code instances (or Tier 1 agents as fallback) collaborating through AgentOS, with an approval gate between them, completing successfully across 10 consecutive runs. "Successfully" means the orchestration works correctly: Agent A produces a structured output conforming to the task output schema; the approval gate pauses execution and presents the output for review; after approval, Agent B receives the structured context and produces implementation files; the event log captures every action; budget tracking is accurate. Success is measured by the framework's orchestration correctness, not the quality of the agents' generated content (which AgentOS does not control).
2. **Event log is complete**: Every agent action, state transition, gate resolution, and budget event can be reconstructed from events. No state exists outside the log. Verified by replaying a completed workflow and confirming identical state reconstruction.
3. **Budget enforcement is hard**: Exceeding a budget halts execution cleanly, no exceptions. Verified by setting a budget below what a workflow requires and confirming clean termination with appropriate events.
4. **Security boundaries hold**: A Tier 1 agent cannot exceed its granted capabilities. Tested with adversarial tool calls that attempt to exceed permissions — all blocked and logged.
5. **Users can author workflows**: YAML configuration is documented with at least 3 example workflows (linear, parallel, fan-out with gate) that a developer can clone and modify for their use case in under 30 minutes.
6. **At least 5 external users with meaningful usage**: Early adopters who have run at least 3 real workflows each (not just the demo) and provided structured feedback. "Meaningful" means they used AgentOS to accomplish a task they would have done manually otherwise — not just kicked the tires.
7. **Test coverage**: 90%+ line coverage on core packages (agentos kernel, platform orchestrator). All core features have both unit and integration tests.
