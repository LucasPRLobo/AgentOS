# Workflow Authoring Guide

This guide covers how to write AgentOS workflow definitions in YAML.

## Workflow Structure

Every workflow YAML has these top-level sections:

```yaml
name: my-workflow           # Required: workflow name
version: "1.5"              # Optional: version string (default "1.0")
budget: { ... }             # Optional: workflow-level budget limits
agents: { ... }             # Required: agent configurations
tasks: { ... }              # Required: task definitions (the DAG)
channels: { ... }           # Optional: inter-agent message channels
```

## Tasks

Tasks are the nodes in your workflow DAG. Each task has a unique key:

```yaml
tasks:
  research:
    agent: researcher            # Which agent executes this task
    type: agent_task             # Default, can be omitted
    description: "Research the topic and produce findings"
    depends_on: []               # No dependencies — runs first
    workspace: shared            # Workspace scope (default: "shared")

  synthesize:
    agent: writer
    description: "Synthesize research into a report"
    depends_on: [research]       # Runs after research completes
```

### Task Types

| Type | Description | Requires Agent? |
|------|-------------|-----------------|
| `agent_task` | Executed by an AI agent (default) | Yes |
| `approval_gate` | Pauses for human approval | No |
| `input_gate` | Pauses for human-provided input | No |
| `consultation` | Asks another agent a question | No (uses `consult_agent`) |

### Task Fields Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | (required) | Task name, must match dict key |
| `agent` | string | null | Agent that executes this task |
| `type` | string | `agent_task` | Task type (see table above) |
| `description` | string | `""` | Task prompt / instructions |
| `depends_on` | list | `[]` | Prerequisite task names |
| `workspace` | string | `shared` | Workspace directory scope |
| `prompt` | string | `""` | Gate prompt (for gates only) |
| `conditions` | list | `[]` | Conditional outgoing edges |
| `retry_policy` | object | null | Revision loop config |
| `consult_agent` | string | null | Agent to consult (consultation type) |
| `consult_question` | string | null | Question to ask (consultation type) |
| `publishes_to` | list | `[]` | Channels to publish output to |
| `subscribes_to` | list | `[]` | Channels to subscribe to |

### Gates

Gates pause workflow execution until a human responds:

```yaml
tasks:
  research:
    agent: researcher
    description: "Research the topic"

  review:
    type: approval_gate
    prompt: "Review research findings before proceeding"
    depends_on: [research]

  implement:
    agent: implementer
    depends_on: [review]
    description: "Implement based on approved research"
```

When running with `--interactive`, gates prompt the user in the terminal. Without `--interactive`, gates are auto-approved.

To resolve gates from a paused workflow:

```bash
agentos gate approve <gate-id> --db <path>
agentos workflow resume <yaml> <workflow-id> --db <path>
```

### Consultation Tasks

Consultation tasks ask another agent a question without running a full task. The response is passed downstream as predecessor context:

```yaml
tasks:
  analysis:
    agent: analyst
    description: "Analyze the data"

  expert_review:
    type: consultation
    depends_on: [analysis]
    consult_agent: senior_analyst
    consult_question: >
      Review the analysis. What are the biggest risks
      that were missed or underweighted?

  final_report:
    agent: writer
    depends_on: [expert_review]
    description: "Write final report incorporating expert feedback"
```

### Conditional Branching

Tasks can have conditional outgoing edges. After a task completes, its conditions are evaluated against the task's output. Targets whose conditions are not met are skipped (along with their dependents):

```yaml
tasks:
  evaluate:
    agent: evaluator
    description: "Evaluate the situation and recommend: BULLISH, BEARISH, or NEUTRAL"
    conditions:
      - target: go_long
        expression: "'bullish' in summary.lower()"
      - target: go_short
        expression: "'bearish' in summary.lower()"
      - target: hold
        expression: "'neutral' in summary.lower()"

  go_long:
    agent: trader
    depends_on: [evaluate]
    description: "Execute long strategy"

  go_short:
    agent: trader
    depends_on: [evaluate]
    description: "Execute short strategy"

  hold:
    agent: trader
    depends_on: [evaluate]
    description: "Write hold memo"
```

**Condition expression variables** (evaluated against predecessor TaskOutput):

| Variable | Type | Description |
|----------|------|-------------|
| `summary` | str | Task summary text |
| `status` | str | Task status string |
| `findings` | list[str] | Finding strings from key_findings |
| `files` | list[str] | File paths from files_produced |
| `open_questions` | list[str] | Unresolved questions |
| `iteration` | int | Retry iteration count |
| `output` | TaskOutput | Full output object |

**Safe builtins**: `len`, `any`, `all`, `str`, `int`, `float`, `bool`, `list`, `abs`, `min`, `max`, `True`, `False`, `None`.

### Revision Loops (Retry Policy)

A task with a `retry_policy` can be re-executed when a downstream gate rejects it or when validation fails:

```yaml
tasks:
  draft_report:
    agent: writer
    description: "Draft the compliance report"
    retry_policy:
      max_retries: 2          # Max retry attempts (1-10)
      on: gate_rejected        # Trigger: "gate_rejected" or "validation_failed"

  compliance_gate:
    type: approval_gate
    prompt: "Does the report meet compliance standards?"
    depends_on: [draft_report]

  publish:
    agent: publisher
    depends_on: [compliance_gate]
    description: "Publish the approved report"
```

When the gate rejects, `draft_report` re-executes (up to 2 times) with the rejection feedback included. The `iteration` counter increments with each retry.

## DAG Patterns

### Linear (Sequential)

```yaml
tasks:
  step1:
    agent: ag1
    description: "First step"
  step2:
    agent: ag1
    description: "Second step"
    depends_on: [step1]
  step3:
    agent: ag1
    description: "Third step"
    depends_on: [step2]
```

### Parallel (Fan-out)

```yaml
tasks:
  analyze_a:
    agent: analyst_a
    description: "Analysis stream A"
  analyze_b:
    agent: analyst_b
    description: "Analysis stream B"
  # Both run in parallel — no dependencies between them
```

### Diamond (Fan-out + Fan-in)

```yaml
tasks:
  plan:
    agent: planner
    description: "Create the plan"
  analyze_a:
    agent: analyst_a
    description: "Analysis A"
    depends_on: [plan]
  analyze_b:
    agent: analyst_b
    description: "Analysis B"
    depends_on: [plan]
  synthesize:
    agent: writer
    description: "Synthesize both analyses"
    depends_on: [analyze_a, analyze_b]
```

### Fan-out with Gate

```yaml
tasks:
  plan:
    agent: planner
    description: "Create the plan"
  dev_a:
    agent: dev_a
    description: "Implement part A"
    depends_on: [plan]
  dev_b:
    agent: dev_b
    description: "Implement part B"
    depends_on: [plan]
  dev_c:
    agent: dev_c
    description: "Implement part C"
    depends_on: [plan]
  review:
    type: approval_gate
    prompt: "Review all implementations before integration"
    depends_on: [dev_a, dev_b, dev_c]
  integrate:
    agent: integrator
    description: "Integrate all parts"
    depends_on: [review]
```

### Conditional Branching with Fallthrough

```yaml
tasks:
  triage:
    agent: triager
    description: "Classify the issue as critical, normal, or low"
    conditions:
      - target: critical_path
        expression: "'critical' in summary.lower()"
      - target: normal_path
        expression: "'normal' in summary.lower()"
      - target: low_path
        expression: "'low' in summary.lower()"

  critical_path:
    agent: senior_dev
    depends_on: [triage]
    description: "Handle critical issue"

  normal_path:
    agent: dev
    depends_on: [triage]
    description: "Handle normal issue"

  low_path:
    agent: junior_dev
    depends_on: [triage]
    description: "Handle low-priority issue"

  close:
    agent: pm
    description: "Close the issue"
    depends_on: [critical_path, normal_path, low_path]
```

### Revision Loop with Gate

```yaml
tasks:
  write_code:
    agent: coder
    description: "Write the implementation"
    retry_policy:
      max_retries: 3
      on: gate_rejected

  code_review:
    type: approval_gate
    prompt: "Does this code meet quality standards?"
    depends_on: [write_code]

  deploy:
    agent: deployer
    description: "Deploy the approved code"
    depends_on: [code_review]
```

### Consultation + Decision

```yaml
tasks:
  research:
    agent: researcher
    description: "Research the problem space"

  expert_consult:
    type: consultation
    depends_on: [research]
    consult_agent: domain_expert
    consult_question: "What risks did the research miss?"

  decision:
    agent: decision_maker
    description: "Make the final decision incorporating expert input"
    depends_on: [expert_consult]
```

## Agents

Each agent referenced by tasks must be defined in the `agents` section:

```yaml
agents:
  researcher:
    adapter: tier2_claude_code        # Adapter type
    model: claude-sonnet-4-6         # LLM model (used by tier1)
    role: "Senior research analyst"   # System prompt / role description
    tools:                            # Allowed tools
      - web_search
      - file_read
      - file_write
    budget:                           # Per-agent limits
      max_tokens: 100000
      max_cost_usd: 2.00
      max_time_seconds: 600
    capabilities:                     # Fine-grained permissions
      - type: "tool:web_search"
      - type: "domain:arxiv.org"
```

### Adapter Tiers

| Tier | Control Level | Description |
|------|---------------|-------------|
| `tier1` | Full | AgentOS controls the tool-calling loop via Anthropic API. Requires `ANTHROPIC_API_KEY`. |
| `tier2_claude_code` | Semi | AgentOS launches Claude Code CLI as a subprocess. Monitors from outside. |
| `tier2_aider` | Semi | AgentOS launches Aider CLI as a subprocess. For code editing workflows. |

**Tool name mapping for Tier 2 Claude Code**: YAML tool names are mapped to Claude Code tool names:

| YAML | Claude Code |
|------|-------------|
| `file_read` | `Read` |
| `file_write` | `Write` |
| `shell_exec` | `Bash` |
| `web_search` | `WebSearch` |

### Agent Capabilities

Fine-grained permissions restrict what an agent can do:

```yaml
agents:
  restricted_agent:
    adapter: tier1
    tools: [file_read, file_write]
    capabilities:
      - type: "tool:file_read"        # Only these tools allowed
      - type: "tool:file_write"
      - type: "path:src/**"           # Only these paths
      - type: "domain:docs.python.org" # Only these domains
      - type: "action:secret:API_KEY"  # Only this secret
```

Capability types:

| Prefix | Example | Description |
|--------|---------|-------------|
| `tool:` | `tool:file_read` | Tool allowlist |
| `path:` | `path:src/**` | File path scope (glob patterns) |
| `domain:` | `domain:api.example.com` | Network domain whitelist |
| `action:` | `action:secret:API_KEY` | Action permissions (e.g., secret access) |

Use `*` as a wildcard: `tool:*`, `path:*`, `domain:*`.

## Channels

Channels enable pub/sub communication between tasks. Define them at the workflow level:

```yaml
channels:
  research_feed:
    mode: broadcast         # All subscribers receive every message
    max_buffer: 50

  task_queue:
    mode: queue             # Round-robin delivery to one subscriber
    max_buffer: 100
```

Tasks publish to and subscribe from channels:

```yaml
tasks:
  researcher_a:
    agent: analyst
    description: "Research stream A"
    publishes_to: [research_feed]

  researcher_b:
    agent: analyst
    description: "Research stream B"
    publishes_to: [research_feed]

  synthesizer:
    agent: writer
    description: "Synthesize all research"
    subscribes_to: [research_feed]
```

| Mode | Behavior |
|------|----------|
| `broadcast` | Every subscriber receives every message |
| `queue` | Each message delivered to one subscriber (round-robin) |

## Budgets

### Workflow-Level Budget

Applied across all agents combined:

```yaml
budget:
  max_tokens: 800000        # Max total tokens across all API calls
  max_api_calls: 200        # Max LLM API calls
  max_time_seconds: 3600    # Max wall-clock time (seconds)
  max_cost_usd: 10.00       # Max total spend in USD
  max_concurrent_tasks: 4   # Max parallel tasks (default: 4, min: 1)
```

### Per-Agent Budget

Each agent can have individual limits:

```yaml
agents:
  researcher:
    budget:
      max_tokens: 100000
      max_cost_usd: 2.00
      max_time_seconds: 600
```

If either the workflow-level or agent-level limit is exceeded, execution halts cleanly with a `budget.exceeded` event.

## Workspaces

Each task runs in a scoped workspace directory. Tasks in the same workspace share files:

```yaml
tasks:
  research:
    workspace: research      # Runs in /tmp/agentos-{id}/research/
  analysis:
    workspace: research      # Same directory — can see research files
  compliance:
    workspace: compliance    # Isolated from research files
  final:
    workspace: shared        # Default workspace
```

Agents operating in Tier 2 run with `cwd` set to their workspace directory. Files produced are tracked in the event log.

## Structured Handoffs

When a task completes, it produces a `TaskOutput` manifest with:

- **summary**: 1-3 sentence summary of what was accomplished
- **key_findings**: Structured findings with confidence levels (`high`/`medium`/`low`) and sources
- **files_produced**: Files created in the workspace (path, description, role)
- **open_questions**: Unresolved questions for downstream tasks
- **metrics**: Token usage, API calls, execution time, estimated cost
- **iteration**: Retry count (starts at 1)
- **revision_feedback**: Feedback from reviewer on retry (if applicable)

Downstream tasks receive their predecessors' outputs as context in the prompt. For Tier 2 agents, predecessor manifests are also written as JSON files to `.agentos_context/` in the workspace.

## Running Workflows

### CLI Commands

```bash
# Verify YAML without executing
agentos workflow verify my_workflow.yaml

# Run with stub executors (for testing)
agentos workflow run my_workflow.yaml

# Run with real agents (Tier 1 API / Tier 2 Claude Code CLI)
agentos workflow run my_workflow.yaml --live

# Run live with manual gate approval
agentos workflow run my_workflow.yaml --live --interactive

# Persist event log to a database file
agentos workflow run my_workflow.yaml --live --db ./workflow.db

# Resume a paused workflow
agentos workflow resume my_workflow.yaml <workflow-id> --db ./workflow.db
```

### Execution Modes

| Flag | Behavior |
|------|----------|
| (none) | Stub mode — tasks log but don't execute real agents |
| `--live` | Real adapters — Tier 1 uses Anthropic API, Tier 2 launches Claude Code CLI |
| `--interactive` | Manual gate approval — prompts user in terminal |
| `--db <path>` | Persist events to SQLite file (default: in-memory) |

### What Happens During Execution

1. YAML is parsed and validated against the schema
2. DAG is checked for cycles and missing dependencies
3. Ready tasks (no unmet dependencies) are dispatched to a thread pool
4. Each task runs its assigned agent with the task description + predecessor context
5. On completion, the agent's structured output is recorded as an event
6. Conditional branches are evaluated; unmet targets are skipped
7. New ready tasks are dispatched until the DAG is exhausted
8. Gates pause execution until resolved (auto or manual)

### Task State Machine

```
PENDING → RUNNING → SUCCEEDED
                  → FAILED
                  → WAITING (gate) → RUNNING (after resolution)
                  → SKIPPED (condition not met)
```

## Validation

Before running, verify your workflow YAML:

```bash
agentos workflow verify my_workflow.yaml
```

This checks for:
- Valid YAML syntax and schema compliance
- DAG cycles
- Missing dependencies (referenced tasks must exist)
- Undefined agents (task agents must be in agents section)
- Unreachable tasks
- Budget allocation warnings
- Gate configuration issues
- Condition expression syntax

## Complete Example

A full workflow using all features — parallel research, conditional branching, revision loops, consultation, and gates:

```yaml
name: investment-analysis
version: "1.5"

budget:
  max_tokens: 800000
  max_cost_usd: 10.00
  max_time_seconds: 3600
  max_concurrent_tasks: 4

agents:
  researcher:
    adapter: tier2_claude_code
    role: >
      You are a senior equity research analyst. Produce detailed,
      data-driven analysis with sources cited. Write findings in markdown.
    tools: [web_search, file_read, file_write]
    budget:
      max_tokens: 100000
      max_cost_usd: 2.00
      max_time_seconds: 600

  risk_analyst:
    adapter: tier2_claude_code
    role: >
      You are a risk analyst. Identify contradictions, flag tail risks,
      and assign conviction scores. Be the skeptic — challenge every assumption.
    tools: [file_read, file_write]
    budget:
      max_tokens: 100000
      max_cost_usd: 2.00

  portfolio_manager:
    adapter: tier2_claude_code
    role: >
      You are a portfolio manager. Translate research into actionable
      recommendations with specific entry/exit levels and position sizes.
    tools: [file_read, file_write]
    budget:
      max_tokens: 80000
      max_cost_usd: 1.50

  compliance_officer:
    adapter: tier2_claude_code
    role: >
      You are the compliance officer. Check proposed trades against
      regulatory limits. If ANY rule is violated, clearly state REJECTED.
    tools: [file_read]
    budget:
      max_tokens: 40000
      max_cost_usd: 0.50
    capabilities:
      - type: "tool:file_read"
      - type: "path:compliance/**"
      - type: "path:shared/**"

  cio:
    adapter: tier2_claude_code
    role: >
      You are the Chief Investment Officer. Ask pointed questions about
      anything that looks too good to be true. Protect capital first.
    tools: [file_read]
    budget:
      max_tokens: 60000
      max_cost_usd: 1.00

tasks:
  # Phase 1: Parallel research
  fundamental:
    agent: researcher
    description: "Analyze NVDA fundamentals: revenue, margins, valuation vs peers"
    workspace: research

  technical:
    agent: researcher
    description: "Analyze NVDA technicals: price action, momentum, support/resistance"
    workspace: research

  macro:
    agent: researcher
    description: "Analyze macro environment: AI capex cycle, trade policy, rate impact"
    workspace: research

  # Phase 2: Risk synthesis (fan-in from all research)
  risk_synthesis:
    agent: risk_analyst
    description: >
      Synthesize all research. Produce: agreement matrix, contradiction log,
      top 5 risks, top 5 catalysts, conviction score (1-10), and
      thesis direction: BULLISH / BEARISH / NEUTRAL.
    depends_on: [fundamental, technical, macro]
    workspace: synthesis

  # Phase 3: Human gate
  risk_gate:
    type: approval_gate
    prompt: "Risk Committee: Is the synthesis well-supported? Approve to proceed."
    depends_on: [risk_synthesis]

  # Phase 4: Conditional branching based on thesis
  thesis:
    agent: portfolio_manager
    description: >
      Declare the investment thesis. State clearly whether it is
      BULLISH, BEARISH, or NEUTRAL with conviction score and justification.
    depends_on: [risk_gate]
    workspace: synthesis
    conditions:
      - target: position_sizing
        expression: "'bullish' in summary.lower()"
      - target: hedge_strategy
        expression: "'bearish' in summary.lower()"
      - target: hold_memo
        expression: "'neutral' in summary.lower()"

  position_sizing:
    agent: portfolio_manager
    description: "Design the long position: size, entry tranches, stop-losses"
    depends_on: [thesis]
    workspace: execution

  hedge_strategy:
    agent: portfolio_manager
    description: "Design the hedge: put spreads, collar, correlated shorts"
    depends_on: [thesis]
    workspace: execution

  hold_memo:
    agent: portfolio_manager
    description: "Write a hold memo: why no action, what to monitor, next review date"
    depends_on: [thesis]
    workspace: synthesis

  # Phase 5: Compliance with revision loop
  compliance_review:
    agent: compliance_officer
    description: >
      Review the proposed trade against: position size limits,
      blackout windows, ESG screens, leverage constraints, concentration limits.
      State APPROVED or REJECTED with specific findings.
    depends_on: [thesis]
    workspace: compliance
    retry_policy:
      max_retries: 2
      on: gate_rejected

  compliance_gate:
    type: approval_gate
    prompt: "Compliance sign-off: Has the officer approved the proposed trade?"
    depends_on: [compliance_review]

  # Phase 6: CIO consultation + final recommendation
  cio_review:
    type: consultation
    depends_on: [compliance_gate]
    consult_agent: cio
    consult_question: >
      What is your biggest concern about this thesis?
      Are there assumptions that need double-checking?

  final_recommendation:
    agent: portfolio_manager
    description: >
      Produce the final investment committee memo incorporating
      CIO feedback. Include: executive summary, thesis, position details,
      risk management, compliance status, and monitoring triggers.
    depends_on: [cio_review]
    workspace: synthesis
```
