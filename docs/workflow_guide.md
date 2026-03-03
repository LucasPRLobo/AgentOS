# Workflow Authoring Guide

This guide covers how to write AgentOS workflow definitions in YAML.

## Workflow Structure

Every workflow YAML has three top-level sections:

```yaml
name: my-workflow           # Required: workflow name
budget: { ... }             # Optional: workflow-level budget limits
tasks: { ... }              # Required: task definitions (the DAG)
agents: { ... }             # Required: agent configurations
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
    workspace: shared            # Workspace scope

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

When the workflow hits a gate, it enters `paused` status. Use the CLI to resolve:

```bash
agentos gate approve <gate-id> --db <path>
agentos workflow resume <yaml> <workflow-id> --db <path>
```

## DAG Patterns

### Linear (Sequential)

```yaml
tasks:
  step1:
    agent: ag1
  step2:
    agent: ag1
    depends_on: [step1]
  step3:
    agent: ag1
    depends_on: [step2]
```

### Parallel (Fan-out)

```yaml
tasks:
  analyze_a:
    agent: analyst_a
  analyze_b:
    agent: analyst_b
  # Both run in parallel — no dependencies between them
```

### Diamond (Fan-out + Fan-in)

```yaml
tasks:
  plan:
    agent: planner
  analyze_a:
    agent: analyst_a
    depends_on: [plan]
  analyze_b:
    agent: analyst_b
    depends_on: [plan]
  synthesize:
    agent: writer
    depends_on: [analyze_a, analyze_b]
```

### Fan-out with Gate

```yaml
tasks:
  plan:
    agent: planner
  dev_a:
    agent: dev_a
    depends_on: [plan]
  dev_b:
    agent: dev_b
    depends_on: [plan]
  dev_c:
    agent: dev_c
    depends_on: [plan]
  review:
    type: approval_gate
    prompt: "Review all implementations before integration"
    depends_on: [dev_a, dev_b, dev_c]
  integrate:
    agent: integrator
    depends_on: [review]
```

## Agents

Each agent referenced by tasks must be defined in the `agents` section:

```yaml
agents:
  researcher:
    adapter: tier1                    # tier1 | tier2_claude_code
    model: claude-sonnet-4-6         # LLM model
    role: "Senior research analyst"   # System prompt
    tools:                            # Allowed tools
      - web_search
      - file_read
      - file_write
    budget:                           # Per-agent limits
      max_tokens: 20000
      max_cost_usd: 1.00
```

### Adapter Tiers

| Tier | Control Level | Description |
|------|---------------|-------------|
| `tier1` | Full | AgentOS controls the tool-calling loop via LLM API |
| `tier2_claude_code` | Semi | AgentOS monitors Claude Code CLI from outside |

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

## Budgets

### Workflow-Level Budget

Applied across all agents combined:

```yaml
budget:
  max_tokens: 100000
  max_api_calls: 50
  max_time_seconds: 600
  max_cost_usd: 5.00
  max_concurrent_tasks: 3
```

### Per-Agent Budget

Each agent can also have individual limits:

```yaml
agents:
  researcher:
    budget:
      max_tokens: 20000
      max_cost_usd: 1.00
```

If either limit is exceeded, execution halts cleanly with a `budget.exceeded` event.

## Structured Handoffs

When a task completes, it produces a `TaskOutput` manifest with:

- **summary**: What was accomplished
- **key_findings**: Structured findings with confidence levels
- **files_produced**: Files created in the workspace
- **open_questions**: Unresolved questions for downstream tasks

Downstream tasks receive their predecessors' outputs as context. This enables structured inter-agent communication without unstructured file passing.

## Validation

Before running, verify your workflow YAML:

```bash
agentos workflow verify my_workflow.yaml
```

This checks for:
- DAG cycles
- Missing dependencies
- Undefined agents
- Unreachable tasks
- Budget allocation warnings
- Gate configuration issues

## Complete Example

```yaml
name: code-review-pipeline
budget:
  max_tokens: 80000
  max_cost_usd: 3.00
  max_concurrent_tasks: 2

tasks:
  analyze:
    agent: analyzer
    description: "Analyze the codebase for issues and patterns"

  review_security:
    agent: security_reviewer
    description: "Review code for security vulnerabilities"
    depends_on: [analyze]

  review_quality:
    agent: quality_reviewer
    description: "Review code quality and best practices"
    depends_on: [analyze]

  human_review:
    type: approval_gate
    prompt: "Review security and quality findings before generating report"
    depends_on: [review_security, review_quality]

  report:
    agent: report_writer
    description: "Generate final code review report"
    depends_on: [human_review]

agents:
  analyzer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Code analysis specialist"
    tools: [file_read]
    budget:
      max_tokens: 20000

  security_reviewer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Application security expert"
    tools: [file_read, web_search]
    budget:
      max_tokens: 20000

  quality_reviewer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Software quality engineer"
    tools: [file_read]
    budget:
      max_tokens: 20000

  report_writer:
    adapter: tier1
    model: claude-sonnet-4-6
    role: "Technical writer"
    tools: [file_read, file_write]
    budget:
      max_tokens: 15000
```
