# AgentOS — V1 Development Plan

**Companion to:** Project Overview | V1 Scope & Roadmap | Go-to-Market Strategy
**Date:** March 2026
**Status:** Confidential — Pre-Development

---

## Purpose of This Document

The Project Overview describes what AgentOS is. The V1 Scope and Roadmap defines what ships in V1. The Go-to-Market Strategy defines how it reaches users. This document answers the remaining question: **how do you build it, week by week, decision by decision, from today through V1 launch?**

This plan translates the architectural vision and roadmap milestones into concrete development actions. It incorporates every finding from four rounds of technical and business review, including identified risks, recommended mitigations, and the specific execution priorities that emerged from that analysis. Where the roadmap says "Month 1-2: Foundation," this document says exactly what gets built in week 1, what gets built in week 2, what decisions must be made before week 3, and what the exit criteria are before moving to the next phase.

The plan is organized into three parallel tracks that run throughout the 6-month development period: the **Engineering Track** (building the product), the **Validation Track** (customer discovery and market evidence), and the **Operational Track** (documentation, community, and launch preparation). These tracks are not sequential — they run concurrently, and the plan specifies which activities happen in parallel at each stage.

---

## Week 0: Pre-Development Spike (Days 1–5)

Before committing to the 6-month plan, three critical uncertainties must be resolved. These are not features to build — they are questions to answer. The answers determine whether the plan proceeds as written or requires adjustment in the first two weeks.

### Spike 1: Claude Code CLI Integration Surface

**Why this is urgent:** The entire V1 credibility story depends on a production-grade Tier 2 Claude Code adapter. The roadmap allocates months 3-4 for this integration. If the CLI integration surface is unstable, restricted, or insufficient, the contingency plan (Tier 1 API fallback + parallel Codex adapter) must be activated immediately — not discovered in month 3, which would waste two months of planning built on a false assumption.

**What to test:** Launch a Claude Code session programmatically from a Python script. Pass it a structured task description. Capture its output (both files produced and terminal output). Monitor its resource consumption (tokens, API calls). Terminate it cleanly. Repeat 10 times and note any instability, interface changes, or access restrictions.

**Specific questions to answer:**

- Can Claude Code be launched headlessly (no interactive terminal required)?
- Can a task description be passed as input without manual prompt entry?
- Can AgentOS capture structured output from the session (files produced, completion status)?
- Can AgentOS monitor token consumption and API calls during the session?
- Can the session be terminated programmatically without data loss?
- Does the CLI interface behave identically across 10 consecutive runs?
- Are there rate limits, authentication requirements, or usage restrictions that would prevent orchestrated use?

**Decision gate:** If 8 of 10 runs succeed with consistent behavior, proceed with the Claude Code Tier 2 adapter as planned for months 3-4. If fewer than 6 succeed, or if the interface is unstable, activate the contingency: shift Tier 2 development to Codex, and plan for Claude Code support via the Tier 1 API fallback (AgentOS controls the tool-calling loop using the Anthropic API directly). Document the findings either way — they inform the adapter architecture decisions in week 2.

### Spike 2: Structured Task Output Schema v0.1

**Why this is urgent:** The structured task output protocol is described conceptually across all three documents — "a JSON schema with required fields for key findings, confidence levels, data sources consulted, open questions, and references to files produced" — but no concrete schema exists yet. Every component being built in months 1-4 touches this schema: the DAG executor passes it between tasks, the workspace manager indexes files referenced in it, the approval gate displays it for human review, and the downstream agent context injection parses it. If each component author interprets the schema differently, integration in month 3-4 will require rework.

**What to produce:** A v0.1 JSON schema that is concrete enough to code against, with the explicit understanding that it will evolve. The schema should define:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["task_id", "agent_id", "status", "output"],
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Unique identifier for the task that produced this output"
    },
    "agent_id": {
      "type": "string",
      "description": "Identifier of the agent that produced this output"
    },
    "status": {
      "type": "string",
      "enum": ["completed", "partial", "failed"],
      "description": "Completion status of the task"
    },
    "output": {
      "type": "object",
      "required": ["summary", "key_findings", "files_produced"],
      "properties": {
        "summary": {
          "type": "string",
          "description": "Brief natural-language summary of what was accomplished"
        },
        "key_findings": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["finding", "confidence"],
            "properties": {
              "finding": { "type": "string" },
              "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"]
              },
              "sources": {
                "type": "array",
                "items": { "type": "string" }
              }
            }
          }
        },
        "files_produced": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["path", "description"],
            "properties": {
              "path": { "type": "string" },
              "description": { "type": "string" },
              "role": {
                "type": "string",
                "enum": ["primary", "supporting", "log"]
              }
            }
          }
        },
        "open_questions": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Unresolved questions for downstream agents or human review"
        }
      }
    },
    "metrics": {
      "type": "object",
      "properties": {
        "tokens_consumed": { "type": "integer" },
        "api_calls_made": { "type": "integer" },
        "execution_time_seconds": { "type": "number" },
        "estimated_cost_usd": { "type": "number" }
      }
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    }
  }
}
```

This is a starting point, not a final specification. The critical requirement is that every component built in months 1-4 codes against this schema (or its evolved version) rather than inventing its own output format. Version the schema from day one — `"schema_version": "0.1"` — so that older outputs remain parseable as the schema evolves.

### Spike 3: Event Schema Design

**Why this is urgent:** The event log is the architectural foundation of the entire system. Every feature from V1 through V3+ reads from it: the DAG executor writes task state transitions, the budget manager writes cost events, the approval gate writes human decisions, the security layer writes capability enforcement events, and every future feature (dashboard, replay, benchmarking, compliance reports) reads from the same log. The event schema designed in week 1-2 will be extremely difficult to change later because every downstream component depends on it.

**What to produce:** A versioned event type catalog with concrete field definitions. At minimum, the V1 event types include:

| Event Type | Key Fields | Emitted By |
|---|---|---|
| `workflow.started` | workflow_id, config_hash, timestamp | DAG executor |
| `workflow.completed` | workflow_id, status, duration | DAG executor |
| `task.state_changed` | task_id, from_state, to_state, agent_id | Task state machine |
| `task.output_produced` | task_id, agent_id, output_manifest_ref | Agent adapter |
| `agent.spawned` | agent_id, adapter_tier, config_hash | Agent lifecycle |
| `agent.terminated` | agent_id, reason, final_metrics | Agent lifecycle |
| `gate.waiting` | gate_id, task_id, gate_type | Gate manager |
| `gate.resolved` | gate_id, resolution, reviewer, feedback | Gate manager |
| `budget.consumed` | agent_id, resource_type, amount, remaining | Budget manager |
| `budget.exceeded` | agent_id, resource_type, limit, attempted | Budget manager |
| `file.created` | path, agent_id, task_id, size | Workspace tracker |
| `file.modified` | path, agent_id, task_id, diff_summary | Workspace tracker |
| `capability.granted` | agent_id, capability_type, scope | Security layer |
| `capability.denied` | agent_id, capability_type, reason | Security layer |
| `error.occurred` | source, error_type, message, recoverable | Any component |

**Design principles for the event schema:**

Every event must include a common envelope: `event_id` (UUID), `event_type` (string), `timestamp` (ISO 8601), `schema_version` (string), and a `payload` object containing type-specific fields. Include a `metadata` field (key-value map) in the envelope for extensibility — future features can attach additional context without changing the schema. Use `schema_version` on every event so that readers can handle schema evolution gracefully.

Store events in SQLite with a single table: `events(event_id TEXT PRIMARY KEY, event_type TEXT, timestamp TEXT, schema_version TEXT, payload JSON, metadata JSON)`. Index on `event_type` and `timestamp`. This is simple, queryable, and sufficient for V1 volumes. The schema supports future migration to a different store without changing the event format.

**Decision gate:** The event schema and task output schema should be reviewed together at the end of week 0 to ensure they are consistent (the `task.output_produced` event references the task output schema) and that neither has gaps that would require the other to be redesigned.

---

## Phase 1: Foundation (Weeks 1–8)

This phase builds the core kernel that everything else depends on. The exit criterion is a working Tier 1 demo: two API-based agents collaborating through the DAG executor with an approval gate, event logging, and budget enforcement. This is not the public demo (which requires the Tier 2 Claude Code adapter) — it is the internal proof that the kernel works.

### Weeks 1–2: Event Log and Task State Machine

**Engineering Track:**

Build the append-only SQLite event log with the schema designed in week 0. Implement the event emitter interface that all components will use to write events. Implement the event reader interface that all components will use to query events. Build the task state machine: PENDING, RUNNING, SUCCEEDED, FAILED, WAITING. Each state transition emits an event. State can be fully reconstructed by replaying events — verify this with a test that replays a sequence of events and asserts the resulting state matches the state built incrementally.

Build the workspace manager: create scoped directories for teams, track file changes by watching the filesystem, emit file events to the event log. The workspace manager should support the file manifest query: "given a task_id, return all files that were created or modified during that task."

Write tests for event log integrity (append-only guarantee, no event loss on process crash), state machine transitions (all valid and invalid transitions), and workspace file tracking (create, modify, delete detection).

**Target:** Event log stores and retrieves events correctly. Task state machine transitions are tested for all paths. Workspace tracks file changes and emits events. ~50-70 new tests passing.

**Validation Track:**

Begin customer discovery conversations. Target 3-5 informal conversations with engineers who use coding agents (Claude Code, Codex, Copilot) in their daily work. Focus on pain validation: "Do you coordinate multiple agents? How? What breaks?" These are 20-30 minute conversations, not sales pitches. Document each conversation with: date, person's role and company size, key quotes, pain points mentioned, current workarounds, and whether they expressed interest in being an early tester.

Start a simple tracking spreadsheet with columns: Name, Role, Company, Date, Key Pain, Workaround, Interest Level, Follow-up Notes. This spreadsheet will be referenced throughout development for prioritization decisions and becomes evidence for investor conversations.

**Operational Track:**

Set up the project repository structure. Establish the Python monorepo layout: `agentos/kernel/` (event log, state machine, budget), `agentos/platform/` (DAG executor, gates, workspace), `agentos/adapters/` (tier 1, tier 2), `agentos/cli/`, `tests/`. Configure CI to run tests on every commit. Establish code coverage reporting targeting 90%+ on kernel and platform packages.

### Weeks 3–4: DAG Executor and Budget Manager

**Engineering Track:**

Build the DAG executor. It reads a workflow definition (YAML/JSON), parses it into a directed acyclic graph, performs topological sort for execution order, and runs tasks respecting dependencies. Implement linear execution (A then B then C), parallel execution (A and B simultaneously, then C), and fan-out/fan-in (A triggers B+C+D in parallel, E waits for all three).

The executor manages concurrency: a configurable limit on how many tasks run simultaneously. Each task execution emits state change events through the task state machine. The executor handles task failure: when a task fails, dependent tasks are marked as blocked, and the workflow enters a recoverable state where the user can retry, skip, or abort.

Build the budget manager. It tracks resource consumption per agent, per team, and per workflow: tokens consumed, API calls made, execution time, and estimated cost. Budget limits are hard constraints — when a limit is exceeded, the agent is stopped cleanly, an event is emitted, and the workflow enters the WAITING state for human decision. The budget manager reads its state from events (it is event-sourced like everything else) and can be reconstructed from the log at any time.

Integrate the budget manager with the DAG executor: before a task starts, the executor checks that sufficient budget remains. During execution, the budget manager monitors consumption in real time and can interrupt a task that exceeds its allocation.

**Target:** DAG executor handles linear, parallel, and fan-out/fan-in patterns. Budget manager enforces hard limits. Both are fully event-sourced. ~60-80 new tests.

**Validation Track:**

Continue customer discovery. Target 3-5 more conversations, expanding beyond your immediate network. If the week 0 Claude Code spike succeeded, mention in conversations that you are building orchestration for Claude Code — this is a natural conversation prop even before the demo exists. If the spike revealed issues, pivot the conversation toward: "If you could orchestrate any coding agents together, what would you build first?"

### Weeks 5–6: Tier 1 Adapter and Approval Gates

**Engineering Track:**

Build the Tier 1 agent adapter. This adapter wraps any LLM API (Anthropic, OpenAI, etc.) and gives AgentOS full control over the tool-calling loop. AgentOS constructs the prompt (system prompt + task description + predecessor context from the structured output protocol), sends it to the API, receives the response, intercepts any tool calls, validates them against the capability set, executes approved tool calls, and returns the result to the model for the next iteration. This loop continues until the agent signals task completion or a budget limit is reached.

The Tier 1 adapter enforces the structured task output protocol directly: it uses the model's structured output features (tool use, JSON mode) to guarantee that the final output conforms to the v0.1 schema. This is the reference implementation of enforcement that the Tier 2 adapter will approximate through post-hoc validation.

Build approval gates and human input nodes. An approval gate is an edge in the DAG that pauses execution after a task completes and before the next task begins. The gate presents the preceding task's structured output (via CLI for V1) and accepts one of three responses: approve (workflow continues), reject with feedback (task can be retried or workflow fails), or edit (user modifies the output before passing it downstream). Implement human input nodes: points where the workflow pauses and asks the user to provide text input, a decision, or a parameter before an agent can proceed.

Gate resolution happens through the CLI (`agentos gate approve <id>`, `agentos gate reject <id> --feedback "..."`) and through the REST API (enabling future UI integration). All gate events are logged: when a gate opens, what it presents, how the user responds, and how long it waited.

**Target:** Tier 1 adapter completes multi-turn tool-calling tasks with budget enforcement. Approval gates pause and resume workflows correctly. Gate resolution works via CLI and API. ~50-60 new tests.

### Weeks 7–8: Internal Demo and CLI Completion

**Engineering Track:**

Build the basic CLI interface: `agentos workflow run <file>`, `agentos status`, `agentos events [--follow]`, `agentos cost`, `agentos gate list`, `agentos gate approve/reject <id>`. The CLI is the primary user interface for V1 — it must be clear, responsive, and informative.

Integrate all components into the internal demo: two Tier 1 agents (API-based) collaborating on a software task. Agent A (Researcher) receives a task description, uses web search and file tools to analyze requirements, and produces a structured research document conforming to the task output schema. The approval gate pauses and presents the research output. After approval, Agent B (Implementer) receives the structured context and produces code files and a summary. The event log captures every action. Budget tracking is accurate.

Run this demo 10 consecutive times. Document any failures, instability, or inconsistencies. Fix everything that breaks. This is the internal validation that the kernel works before investing in the Tier 2 adapter.

**Target:** The internal Tier 1 demo completes successfully 10/10 times. CLI provides full visibility into workflow state, events, and costs. The kernel is solid.

**Exit criteria for Phase 1:** All kernel components (event log, task state machine, DAG executor, budget manager, workspace manager) are implemented, tested, and integrated. The Tier 1 adapter demonstrates end-to-end workflow execution with gates. Test coverage on kernel and platform packages exceeds 90%. The internal demo proves the architecture works.

**Validation Track milestone:** 8-12 customer discovery conversations completed and documented. At least 3 people have expressed interest in being early testers. Pain points are cataloged and cross-referenced with V1 feature priorities.

---

## Phase 2: Agent Integration and Hardening (Weeks 9–16)

This phase adds the Tier 2 Claude Code adapter (or contingency alternative), the structured task output protocol enforcement for semi-controlled agents, workflow verification, and the pause/resume capability. The exit criterion is the public demo: two Claude Code instances collaborating through AgentOS with full governance.

### Weeks 9–10: Tier 2 Adapter — Claude Code (or Contingency)

**If Week 0 spike succeeded (Claude Code CLI is stable):**

Build the Tier 2 Claude Code adapter. This is not a thin wrapper — it is a production-grade integration that provides meaningful orchestration, monitoring, and task assignment. The adapter must: launch a Claude Code session programmatically with a specific system prompt and tool configuration, pass a task description and predecessor context (from the structured output protocol), monitor the session's progress (file changes, token consumption, API calls), capture the session's output (files produced, terminal output), instruct the agent to produce a JSON manifest file alongside its regular output, validate the manifest against the task output schema post-hoc, and terminate the session cleanly when the task is complete or a budget limit is reached.

The critical difference from Tier 1: AgentOS does not control the tool-calling loop. Claude Code makes its own decisions about what tools to use and when. AgentOS monitors and constrains from outside the loop rather than intercepting each tool call. This means security enforcement is at the orchestration layer (task assignment, workspace scoping, budget limits) rather than at the tool-call level.

**If Week 0 spike failed (Claude Code CLI is unstable):**

Activate the contingency plan. Build the Tier 1 Claude API fallback: use the Anthropic API directly with AgentOS controlling the tool-calling loop. This provides the full Tier 1 enforcement capabilities but sacrifices the "orchestrating real autonomous runtimes" positioning. Simultaneously, begin investigating the Codex CLI integration surface for a Tier 2 adapter (same spike methodology as week 0 for Claude Code). The goal is to have at least one viable Tier 2 adapter by month 4 — whether it is Claude Code, Codex, or another autonomous agent tool.

**Target:** A working Tier 2 adapter (or Tier 1 fallback with Tier 2 investigation underway) that can be assigned tasks, monitored, and terminated by the DAG executor. ~40-50 new tests.

### Weeks 11–12: Structured Handoffs and Workflow Verification

**Engineering Track:**

Implement the structured task output protocol enforcement for Tier 2 agents. The Tier 2 agent is instructed (via its system prompt) to produce a JSON manifest file in the workspace alongside its regular output. After the agent completes its task, AgentOS reads the manifest, validates it against the task output schema, and either accepts it (passing the structured context to downstream agents) or rejects it (triggering a retry or human gate). If the agent fails to produce a conforming manifest after the configured number of retries, the task is marked as requiring human review rather than silently passing unstructured output downstream. This is the "best-effort with validation" approach described in the V1 Scope.

Build workflow verification — the "compiler for agent workflows." Before a workflow runs, the verifier statically analyzes the DAG and checks for: circular dependencies (invalid DAG), agents with insufficient permissions to complete their assigned tasks (permission mismatch), budget allocations that are mathematically insufficient given task requirements (budget shortfall), data dependencies where a downstream agent expects input that no upstream agent is configured to produce (orphan dependencies), and missing approval gates at points where the workflow configuration requires them. The verification report is available via CLI (`agentos workflow verify <file>`) and includes specific, actionable error messages for each issue found.

Implement pause/resume. A user can pause a running workflow at any time. Pausing means stopping the executor — no new tasks are started, running tasks are allowed to complete (or can be forcibly stopped). Resuming means the executor reads the event log, reconstructs the current state, and picks up where it left off. This is possible because all state is event-sourced — there is nothing to "save" when pausing and nothing to "restore" when resuming.

**Target:** Structured handoffs work for both Tier 1 (enforced) and Tier 2 (validated). Workflow verification catches all specified error classes. Pause/resume works correctly. ~50-60 new tests.

**Validation Track:**

Begin structured interviews (moving beyond informal conversations). Target 5-8 interviews across the three segments defined in the GTM: engineering teams using coding agents, financial firms using AI for research, and enterprise IT leaders evaluating agent governance. Use the working internal demo as a conversation prop — screen share it during calls if possible. Focus on willingness to pay: "Would you use this? What would you pay? What is missing before you would deploy this?"

### Weeks 13–14: CLI Refinement and Integration Testing

**Engineering Track:**

Complete the CLI interface with all V1 commands: `agentos workflow run`, `agentos workflow verify`, `agentos status`, `agentos events [--follow]`, `agentos cost`, `agentos gate list`, `agentos gate approve/reject <id>`, `agentos agent restart <id>`. Focus on user experience: clear output formatting, helpful error messages, progress indicators for long-running operations, and consistent command structure.

Run comprehensive integration tests: end-to-end workflow execution with both Tier 1 and Tier 2 agents, gate resolution via CLI and API, budget enforcement under various conditions (gradual approach, sudden spike, exact limit), workflow verification with deliberately malformed configurations, pause/resume across different workflow states, and failure recovery (agent crash, network timeout, API rate limit).

**Target:** CLI is complete and polished. Integration test suite covers all critical paths. No known issues with core workflow execution.

### Weeks 15–16: Public Demo Construction

**Engineering Track:**

Build the public demo: two Claude Code instances (or best available Tier 2 agents) collaborating on a software development task with an approval gate between them. This is the demo described in the V1 Scope:

Agent A (Researcher) receives a task description, analyzes requirements and technical specifications, and produces a structured research document with findings, recommendations, and file references. The approval gate pauses execution and presents the research output for human review. After approval, Agent B (Implementer) receives the approved research as structured context, implements the solution, and produces code files and a summary.

Run this demo 10 consecutive times. Every run must succeed. "Success" means the orchestration works correctly: structured output conforms to schema, gate pauses and presents output, downstream agent receives structured context, event log captures every action, budget tracking is accurate. Success is measured by the framework's orchestration correctness, not the quality of the agents' generated content.

Record a 3-minute video of the demo working. This video is more valuable than any slide deck for investor conversations, Hacker News posts, and conference talk proposals. Show the workflow starting, Agent A working (with live event stream visible), the gate pausing for approval, the user reviewing and approving, Agent B picking up the structured context, and the final result — all with budget tracking visible throughout.

**Target:** Public demo works reliably (10/10 runs). Demo video recorded. This is the primary marketing asset for launch.

**Exit criteria for Phase 2:** Tier 2 adapter (or contingency) is production-grade. Structured handoffs work across tiers. Workflow verification catches errors before execution. Pause/resume is reliable. Public demo works 10/10 times. Demo video is recorded.

**Validation Track milestone:** 15-20 total customer discovery conversations completed. At least 5 people have expressed willingness to be early adopters. Evidence of pain is documented with specific quotes quantifying the problem ("I spend X hours per week..."). Willingness-to-pay signals are recorded.

---

## Phase 3: Security, Reliability, and Launch Preparation (Weeks 17–24)

This phase adds the security layer, adversarial validation, agent lifecycle management, deterministic replay, and documentation. The exit criterion is a launchable V1 product that meets all seven success criteria defined in the V1 Scope.

### Weeks 17–18: Capability-Based Security Model

**Engineering Track:**

Build the capability-based permission model. Each agent is granted a specific set of capabilities: tool allowlists (which tools the agent can use), workspace scoping (which directories the agent can read/write), domain whitelists (which external URLs the agent can access), and action restrictions (which operations require human approval).

For Tier 1 agents (where AgentOS controls the tool-calling loop), enforcement is direct: every tool call is intercepted and validated against the capability set before execution. A tool call that exceeds the agent's capabilities is blocked, logged as a `capability.denied` event, and the agent receives an error response. For Tier 2 agents, enforcement is at the orchestration layer: workspace scoping (the agent only has filesystem access to its assigned directories), budget limits (hard enforcement regardless of adapter tier), and task assignment (the agent only receives tasks appropriate to its granted capabilities). Deeper enforcement (sandbox-level isolation via containers) is deferred to V2 as specified in the roadmap.

Build the secrets store. Credentials (API keys, tokens, passwords) are registered once and stored encrypted at rest. When an agent needs a credential, AgentOS injects it into the agent's environment at runtime through a secure channel. Credentials never appear in plain text in event logs, workspace files, agent prompts, or CLI output. When an agent is terminated or its permissions change, credential access is revoked immediately.

Test security enforcement adversarially: create a Tier 1 agent and attempt tool calls that exceed its capabilities (file writes outside its workspace, HTTP requests to non-whitelisted domains, execution of disallowed commands). All must be blocked and logged. Verify that credential injection works and that credentials are not visible in logs or workspace files.

**Target:** Capability model enforced for Tier 1 agents. Secrets store operational. Adversarial tests pass. ~40-50 new tests.

### Weeks 19–20: Adversarial Validation and Lifecycle Management

**Engineering Track:**

Build adversarial validation nodes as a native workflow primitive. A validator node receives the output of a predecessor task, independently verifies claims, checks for internal consistency, flags confidence levels, and produces a validation report with pass/fail status and specific findings. On validation failure, the workflow can automatically trigger: a retry of the original task, a revision loop (sending the validation feedback back to the original agent), or escalation to a human gate.

The validator agent should use a different model backend than the agent it is validating — this should be the strong default, not just a recommendation. When configuring a workflow with validation, the framework should warn (or error) if the validator uses the same backend as the producer. The purpose of adversarial validation is genuine independent verification, and using the same model for both roles undermines that purpose.

Build agent lifecycle management. Support spawning new agent instances, monitoring running instances, stopping instances cleanly, and restarting instances with a fresh context. The fresh restart is critical: it creates a new agent instance with a clean context window, re-injects the agent's configuration (role, tools, permissions, constraints), and provides a framework-generated briefing summarizing the work completed so far (derived from the event log and workspace state). This addresses the "spoiled context" problem without requiring automated degradation detection.

Implement configurable lifecycle policies: restart on token threshold (agent has consumed N tokens of context), restart on turn count (agent has completed N conversation turns), and restart on time limit (agent has been running for N minutes). These are user-configurable with sensible defaults.

**Target:** Adversarial validation nodes work end-to-end with automatic retry/revision/escalation. Agent lifecycle management supports fresh restart with context briefing. Lifecycle policies are configurable. ~40-50 new tests.

### Weeks 21–22: Replay, Documentation, and Example Workflows

**Engineering Track:**

Build basic deterministic replay. Given a completed workflow, the user can inspect the event log to reconstruct the execution history at any point: what was the state of each task, what inputs did each agent receive, what outputs did it produce, and what decisions were made at each gate. This is the read-only version of time-travel debugging — full re-execution from modified state is deferred to post-V1, but the ability to inspect past executions in detail is V1 scope.

Write documentation. This is not optional and not cosmetic — documentation determines whether the "5 external users with meaningful usage" success criterion is achievable. Target three documents: a Getting Started guide (install AgentOS, run the demo workflow, understand the output — under 15 minutes), an Adapter Development guide (implement the adapter interface, test the adapter, register it with the framework), and a Workflow Authoring guide (YAML configuration reference, workflow patterns, gate configuration, budget configuration, security configuration).

Create at least 3 example workflows that a developer can clone and modify in under 30 minutes: a linear workflow (research then implement with gate), a parallel workflow (two agents working simultaneously, results merged), and a fan-out-with-gate workflow (one agent triggers three parallel agents, human reviews before final merge). Each example should include the YAML configuration, a README explaining what it does, and instructions for running it.

**Target:** Deterministic replay reconstructs execution history from events. Three documentation guides written. Three example workflows created and tested.

### Weeks 23–24: Hardening, Launch Prep, and the DevOps Demo

**Engineering Track:**

Build the end-to-end DevOps demo workflow described in the V1 Scope and Project Overview. This is the full showcase: a multi-agent software development pipeline with research, implementation, review, and approval gates. This exercises every V1 feature: multiple agents, structured handoffs, adversarial validation, approval gates, budget enforcement, security boundaries, and full event logging.

Run the complete V1 test suite. Verify 90%+ line coverage on kernel and platform packages. Run the public demo 10 consecutive times and the DevOps demo 10 consecutive times. Fix anything that breaks. Perform load testing: run workflows with 5, 10, and 20 concurrent tasks and verify that the executor handles concurrency correctly without resource exhaustion or deadlocks.

Review all success criteria:

1. Demo works reliably across 10 consecutive runs — verified.
2. Event log is complete (replay test) — verified.
3. Budget enforcement is hard (under-budget test) — verified.
4. Security boundaries hold (adversarial capability test) — verified.
5. Users can author workflows (3 example workflows, documentation) — verified.
6. At least 5 external users with meaningful usage — in progress (see validation track).
7. 90%+ test coverage on core packages — verified.

**Validation Track (final push):**

Contact all customer discovery participants who expressed interest in early testing. Provide them with access to AgentOS, the Getting Started guide, and one of the example workflows. Offer a 30-minute onboarding call. The goal is 5 external users who each run at least 3 real workflows (not just the demo) and provide structured feedback. "Meaningful" means they used AgentOS to accomplish a task they would have done manually otherwise.

Prepare a structured feedback template: What did you try to build? Did it work? What broke? What was confusing? What is missing? Would you use this again? Would you pay for it? How much?

**Operational Track:**

Prepare launch materials. The Hacker News post, blog post, and README are the three critical launch artifacts. The HN post should be a "Show HN" with the demo video and a clear explanation of what AgentOS is and why it exists. The blog post should be a practical tutorial: "How I orchestrate 2 Claude Code instances on one project with approval gates." The README should get a developer from clone to running the demo in under 15 minutes.

---

## Parallel Track: Customer Discovery Timeline

This is a consolidated view of the validation activities that run alongside engineering throughout the 6-month development period. These are not separate from development — they inform feature prioritization, validate assumptions, and produce the evidence needed for investor conversations.

| Period | Activity | Target | Focus |
|---|---|---|---|
| Week 0 | Identify first 5 conversation targets | 5 names and contact info | Engineers using coding agents in your network |
| Weeks 1-4 | Informal pain validation | 5-10 conversations | "Do you coordinate multiple agents? How? What breaks?" |
| Weeks 5-8 | Expanded outreach | 5-8 more conversations | Beyond immediate network; include engineering leads |
| Weeks 9-12 | Structured interviews with demo | 5-8 interviews across 3 segments | Willingness to pay; use demo as conversation prop |
| Weeks 13-16 | Enterprise buyer conversations | 3-5 conversations with CISOs/CTOs | Deployment requirements; governance pain |
| Weeks 17-20 | Early adopter recruitment | Identify 8-10 candidates | People who expressed strongest interest |
| Weeks 21-24 | Beta onboarding | 5+ active users | Structured feedback on real workflows |

**Total target:** 20-30 conversations before V1 launch, with documented evidence of pain and willingness to pay. At least 5 users with meaningful usage providing structured feedback.

---

## Risk Register

This section consolidates all identified risks from four rounds of technical and business review, with their mitigations and monitoring triggers.

### Risk 1: Claude Code Adapter Instability

**Severity:** High — threatens V1 credibility and Layer 2 positioning.

**Mitigation:** Week 0 spike tests integration surface before any planning depends on it. Three-part contingency: (1) Tier 1 API fallback using Claude API directly, (2) parallel Codex Tier 2 adapter development, (3) early engagement with Anthropic developer relations. Architecture ensures no core feature depends on any specific adapter.

**Monitoring trigger:** If the week 0 spike fails, activate contingency immediately. If the adapter works in week 0 but becomes unstable during month 3-4 development, switch to the Tier 1 fallback for the demo and continue Tier 2 work on a parallel branch.

### Risk 2: Event Schema Lock-In

**Severity:** Medium — wrong schema design forces painful migration of all downstream components.

**Mitigation:** Invest extra time in week 0 on schema design. Version every event from day one. Include extensible metadata fields. Review schema at the end of phase 1 (week 8) before downstream features cement assumptions.

**Monitoring trigger:** If adding a new event type requires changing the core schema (not just adding a new type), the schema is insufficiently extensible. Refactor before phase 2 begins.

### Risk 3: Structured Output Compliance for Tier 2 Agents

**Severity:** Medium — if autonomous agents cannot reliably produce conforming output manifests, the structured handoff protocol degrades to unstructured file passing, and the quality of multi-agent collaboration suffers.

**Mitigation:** Post-hoc validation with retry. Clear failure path: non-conforming output triggers retry, then human gate, never silent passthrough. Invest in prompt engineering for the manifest instruction — test across different task types and agent configurations to find instructions that reliably produce conforming output.

**Monitoring trigger:** If fewer than 70% of Tier 2 task completions produce conforming manifests on the first attempt, the prompt instruction needs rework. If fewer than 90% produce conforming manifests after one retry, escalate to a design review of the protocol.

### Risk 4: Solo Founder Key-Person Risk

**Severity:** Medium-High — if the sole engineer is unavailable, the entire project stops.

**Mitigation:** Solo-founder scope constraint means V1 is achievable by one person. Architecture avoids complexity that requires specialized knowledge. Comprehensive test suite means a second engineer could onboard from tests. Priority hiring plan (systems engineer first) is activated as soon as funding or revenue allows.

**Monitoring trigger:** If development velocity drops below 70% of plan for two consecutive weeks due to founder availability, assess whether scope reduction or a co-founder search is needed.

### Risk 5: Insufficient Early Adopter Engagement

**Severity:** Medium — the "5 external users with meaningful usage" criterion is the hardest to meet on a 6-month timeline because it depends on other people's schedules and willingness.

**Mitigation:** Start customer discovery in week 1, not after launch. Maintain a prospect tracker from day one. Each discovery conversation is also a recruitment opportunity. Offer 30-minute onboarding calls. Make the Getting Started guide genuinely achievable in 15 minutes.

**Monitoring trigger:** If fewer than 10 conversations have happened by week 12, or if no one has expressed willingness to beta test, the customer discovery approach needs a reset (different channels, different messaging, different target segment).

### Risk 6: Platform Risk from First-Party Orchestration

**Severity:** High (long-term) — Anthropic, OpenAI, or Microsoft ships native multi-agent orchestration.

**Mitigation:** Governance positioning (not orchestration) as primary value proposition. Provider neutrality (multi-provider workflows). On-premises deployment option. Speed to market establishing the governance category before competitors recognize it. Competitive response playbook with specific scenarios and actions (detailed in GTM document).

**Monitoring trigger:** Monitor Anthropic, OpenAI, and Microsoft product announcements weekly. If any ships a governance-focused multi-agent product (not just orchestration), accelerate the open-source timeline and community building.

---

## Decision Log Template

Throughout development, architectural and strategic decisions will need to be made that are not fully specified in the planning documents. Each decision should be recorded with enough context that it can be reviewed later.

For each significant decision, record:

- **Date:** When the decision was made.
- **Decision:** What was decided (one sentence).
- **Context:** What alternatives were considered and why this option was chosen.
- **Consequences:** What this decision enables and what it forecloses.
- **Revisit trigger:** Under what conditions this decision should be reconsidered.

Examples of decisions that will arise during development:

- Which specific LLM API to use for the default Tier 1 adapter (Anthropic Claude API vs. OpenAI API vs. configurable).
- How to handle Tier 2 agent sessions that exceed their allocated time without producing output.
- Whether the structured task output schema should support custom fields beyond the defined set.
- How to generate the "curated briefing" for fresh agent restarts (what to include, what to omit, maximum length).
- Whether to implement the secrets store as an encrypted file, a system keyring integration, or an environment variable injection.

Maintaining a decision log prevents relitigating settled questions and provides context for anyone who joins the project later.

---

## Post-V1 Immediate Priorities (Weeks 25-32 / V1.5)

V1.5 is not a separate release — it is the set of features added in the 2-3 months immediately following V1 launch, informed by early adopter feedback. V1.5 is scoped to 4-6 weeks of focused development.

**Read-only web dashboard:** Real-time session monitoring, event log viewer, cost charts. This is the first visual interface, built on the stable REST API established in V1. No workflow builder — CLI remains the authoring interface. The dashboard is primarily a monitoring and observability tool that makes AgentOS accessible to team leads and managers who do not use the CLI.

**Conditional branching in DAGs:** If/else edges based on task output. "If tests pass, deploy; if tests fail, notify and trigger review." Requires a simple expression evaluator on edge conditions — keep this minimal (JSON path expressions against the task output schema, basic comparison operators) rather than building a full expression language.

**Review/revision loops:** When an approval gate rejects output, automatically re-route back to the producing agent with the rejection feedback for revision. In V1, this can be achieved manually by re-running with modified input. V1.5 makes it a native workflow primitive with configurable retry limits.

**Second Tier 2 adapter:** Codex or another autonomous agent tool at production-grade quality. This eliminates single-provider dependency and strengthens the provider-neutrality positioning.

---

## Deferred Documents and Their Triggers

Several documents are intentionally not produced during the V1 development period because they would contain assumptions rather than data. Each has a specific trigger for when it will be created:

**Financial model with revenue projections:** Trigger is V1 launch, when real usage data (number of users, workflow volume, cost per workflow) provides a basis for revenue projections. Estimated timeline: month 7-8. Before this point, the unit economics paragraph in the GTM (80-90% gross margins, no inference cost passthrough) is sufficient for investor conversations.

**Team and hiring plan:** Trigger is when the first external hire becomes feasible, informed by V1 development velocity and the specific expertise gaps identified during development. Estimated timeline: month 6-9, depending on progress and funding. The priority hire order (systems engineer first, developer advocate second) is defined but the specific job descriptions, compensation, and sourcing strategy require more information than is available today.

**Hedge fund scope document:** Trigger is when Phase 3 enters active planning. Hedge fund development does not begin until V1 is launched and stable. The earliest this enters active scope is month 9-12, and only if the framework has demonstrated sufficient reliability through early adopter usage.

**Pitch deck for fundraising:** Trigger is when the demo is working reliably and customer discovery evidence is documented. The pitch deck should include: the demo video, 3-5 customer quotes quantifying pain, the governance positioning, the unit economics, and the team/founder narrative. Estimated timeline: month 5-7, overlapping with late V1 development.

---

## Success Checklist

This is the complete list of exit criteria for V1 launch, consolidated from the V1 Scope document with the specificity improvements from review feedback:

- [ ] **Demo reliability:** Two Claude Code instances (or Tier 1 fallback) collaborating through AgentOS with an approval gate, completing successfully across 10 consecutive runs. Success measured by orchestration correctness, not agent output quality.
- [ ] **Event log completeness:** Every agent action, state transition, gate resolution, and budget event can be reconstructed from events. Verified by replaying a completed workflow and confirming identical state reconstruction.
- [ ] **Budget enforcement:** Exceeding a budget halts execution cleanly, no exceptions. Verified by setting a budget below workflow requirements and confirming clean termination with appropriate events.
- [ ] **Security boundaries:** A Tier 1 agent cannot exceed its granted capabilities. Tested with adversarial tool calls that attempt to exceed permissions — all blocked and logged.
- [ ] **Workflow authoring:** YAML configuration documented with at least 3 example workflows (linear, parallel, fan-out with gate) that a developer can clone and modify in under 30 minutes.
- [ ] **External users:** At least 5 external users who have run at least 3 real workflows each (not just the demo) and provided structured feedback.
- [ ] **Test coverage:** 90%+ line coverage on core packages (kernel, platform orchestrator). All core features have both unit and integration tests.
- [ ] **Documentation:** Getting Started guide, Adapter Development guide, Workflow Authoring guide — all reviewed by at least one external user for clarity.
- [ ] **Demo video:** 3-minute recording of the public demo working end-to-end.
- [ ] **Customer discovery evidence:** 20-30 documented conversations with quantified pain points and willingness-to-pay signals.