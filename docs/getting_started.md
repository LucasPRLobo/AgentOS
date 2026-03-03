# Getting Started with AgentOS

AgentOS is a governance and orchestration platform for autonomous AI agents. It coordinates multiple AI agents working together in structured workflows, with hard budget enforcement, capability-based security, approval gates, and a complete audit trail.

## Installation

```bash
# Clone the repository
git clone https://github.com/your-org/agentos.git
cd agentos

# Install in development mode
pip install -e ".[dev]"
```

### Requirements

- Python 3.11+
- No external services needed — AgentOS uses SQLite for persistence

## Quick Start: Run the Demo

The fastest way to see AgentOS in action:

```bash
# Run with the default linear research workflow
python -m agentos.cli.main demo

# Run with a specific example
python -m agentos.cli.main demo examples/parallel_analysis.yaml

# Persist to disk for later inspection
python -m agentos.cli.main demo examples/linear_research.yaml --db /tmp/demo.db
```

The demo runs workflows with stub executors (no real LLM calls). It exercises the full kernel: DAG scheduling, budget tracking, workspace management, event logging, and structured handoffs.

## Core Concepts

### Workflows

A workflow is a DAG (directed acyclic graph) of tasks defined in YAML:

```yaml
name: research-and-write
budget:
  max_tokens: 50000
  max_cost_usd: 2.00

tasks:
  research:
    agent: researcher
    description: Research the topic
  write:
    agent: writer
    depends_on: [research]
    description: Write the report

agents:
  researcher:
    adapter: tier1
    model: claude-sonnet-4-6
    tools: [web_search, file_write]
  writer:
    adapter: tier1
    model: claude-sonnet-4-6
    tools: [file_read, file_write]
```

### Tasks

Each task is a node in the DAG. Task types:

- **`agent_task`** (default) — executed by an AI agent
- **`approval_gate`** — pauses workflow until a human approves
- **`input_gate`** — pauses workflow until a human provides input

### Agents

Agents execute tasks. Each agent has:

- **Adapter tier**: How AgentOS controls the agent (Tier 1 = full control, Tier 2 = monitored)
- **Model**: Which LLM to use
- **Tools**: Allowed tool list
- **Budget**: Per-agent resource limits
- **Capabilities**: Fine-grained permissions (paths, domains, secrets)

### Budgets

AgentOS enforces hard limits on 5 dimensions:

| Dimension | Field | Description |
|-----------|-------|-------------|
| Tokens | `max_tokens` | Total tokens consumed |
| API calls | `max_api_calls` | Number of LLM API calls |
| Time | `max_time_seconds` | Wall-clock execution time |
| Cost | `max_cost_usd` | Estimated USD cost |
| Concurrency | `max_concurrent_tasks` | Parallel task limit |

Budgets are enforced at both the workflow level and per-agent level. Exceeding any limit halts execution cleanly.

### Event Log

Every state change is recorded as an immutable event in an append-only SQLite log. All state is derived from events — nothing mutates silently.

Event types include: workflow lifecycle, task state changes, agent lifecycle, gate resolutions, budget consumption, file operations, and capability checks.

## CLI Commands

```bash
# Demo mode
agentos demo [YAML_FILE] [--db PATH] [--pause-at-gates]

# Workflow management
agentos workflow run YAML_FILE --db PATH
agentos workflow resume YAML_FILE WORKFLOW_ID --db PATH
agentos workflow verify YAML_FILE

# Gate management
agentos gate list --db PATH
agentos gate approve GATE_ID --db PATH
agentos gate reject GATE_ID --db PATH [--feedback TEXT]

# Inspection
agentos status --db PATH
agentos events --db PATH [--type EVENT_TYPE] [--workflow-id ID]
agentos cost --db PATH [--agent AGENT_ID]
agentos replay --db PATH --workflow-id ID
```

## Example: Pause at Gates

```bash
# Run with gates that pause for manual approval
agentos demo examples/fanout_with_gate.yaml --db /tmp/gate-demo.db --pause-at-gates

# The workflow pauses at the gate. Approve it:
agentos gate approve <gate-id> --db /tmp/gate-demo.db

# Resume the workflow:
agentos workflow resume examples/fanout_with_gate.yaml <workflow-id> --db /tmp/gate-demo.db
```

## Example: Replay a Workflow

After running a workflow with `--db`, you can replay it to reconstruct the full execution state:

```bash
agentos replay --db /tmp/demo.db --workflow-id <id>
```

This shows task states, agent records, gate resolutions, budget usage, and the complete event timeline.

## Project Structure

```
agentos/
├── kernel/         # Core: event log, state machine, DAG executor, budget, workspace
├── adapters/       # Agent adapters: Tier 1 (API), Tier 2 (Claude Code CLI)
├── security/       # Capability enforcer, secret store
├── validation/     # Workflow verifier, adversarial validation
├── schemas/        # Pydantic v2 models for all data structures
├── cli/            # Click-based CLI commands
tests/
├── unit/           # Per-module unit tests
├── integration/    # Cross-module integration tests
├── e2e/            # End-to-end workflow tests
examples/           # Example workflow YAML files
```

## Next Steps

- [Workflow Authoring Guide](workflow_guide.md) — YAML syntax, DAG patterns, gates, budgets
- [Adapter Development Guide](adapter_guide.md) — Building custom agent adapters
