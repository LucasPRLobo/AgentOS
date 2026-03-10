# Getting Started with AgentOS

AgentOS is a governance and orchestration platform for autonomous AI agents. It coordinates multiple AI agents working together in structured workflows, with hard budget enforcement, capability-based security, approval gates, and a complete audit trail.

## Installation

```bash
# Clone the repository
git clone https://github.com/LucasPRLobo/AgentOS.git
cd AgentOS

# Install in development mode
pip install -e ".[dev]"
```

### Requirements

- Python 3.11+
- Claude Code CLI (for Tier 2 workflows): `npm install -g @anthropic-ai/claude-code`
- `ANTHROPIC_API_KEY` environment variable set
- No external databases — AgentOS uses SQLite for persistence

## Quick Start

### 1. Validate a workflow before running

```bash
agentos workflow doctor examples/quick_research.yaml
```

The doctor catches tool name typos, missing capabilities, budget issues, and DAG problems before you spend API credits.

### 2. Run a simple workflow

```bash
# Single-agent research with a parameter
agentos workflow run examples/quick_research.yaml \
  --db research.db \
  --param topic="autonomous vehicle regulation"
```

### 3. Run a multi-agent workflow

```bash
# Parallel research + approval gate + synthesis
agentos workflow run examples/hedge_fund_analysis.yaml \
  --db analysis.db \
  --param ticker=NVDA \
  --param sector=semiconductors
```

This runs two agents in parallel (market researcher + macro analyst), pauses at an approval gate for your review, then runs a strategist to synthesize the recommendation.

### 4. Manage gates

When a workflow hits an approval gate, it pauses and waits:

```bash
# See pending gates
agentos gate list --db analysis.db

# Approve (with optional feedback that flows to downstream tasks)
agentos gate approve <gate-id> --db analysis.db

# Or reject
agentos gate reject <gate-id> --db analysis.db --feedback "Need more data"

# For input gates, provide freeform input
agentos gate respond <gate-id> --db analysis.db -m "Focus on supply chain risks"
```

### 5. Resume after gate approval

```bash
agentos workflow resume examples/hedge_fund_analysis.yaml <workflow-id> --db analysis.db
```

### 6. Inspect results

```bash
# Status overview
agentos status --db analysis.db

# Cost breakdown
agentos cost --db analysis.db

# Full event timeline
agentos events --db analysis.db

# Replay execution from event log
agentos replay --db analysis.db --workflow-id <id>

# Generate compliance report
agentos compliance-report <workflow-id> --db analysis.db --format html -o report.html
```

### Demo mode (no LLM calls)

To explore the system without API credits:

```bash
agentos demo examples/fanout_with_gate.yaml --db demo.db --pause-at-gates
```

Runs with stub executors that exercise the full kernel: DAG scheduling, budget tracking, workspace management, event logging, and structured handoffs.

## Core Concepts

### Workflows

A workflow is a DAG (directed acyclic graph) of tasks defined in YAML. Workflows support runtime parameters with `${param_name}` substitution:

```yaml
name: quick_research
version: "1.0"

budget:
  max_tokens: 30000
  max_cost_usd: 1.00

agents:
  researcher:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a thorough researcher."
    tools: [file_read, file_write, web_search]

tasks:
  research:
    name: research
    description: "Research ${topic} and produce a summary."
    agent: researcher
    workspace: shared

parameters:
  topic:
    description: "Topic to research"
    required: true
```

### Task Types

- **Agent task** (default) — executed by an AI agent
- **Approval gate** (`type: approval_gate`) — pauses until human approves or rejects
- **Input gate** (`type: input_gate`) — pauses until human provides freeform input
- **Adversarial** (`type: adversarial`) — challenges predecessor output
- **Consultation** (`type: consultation`) — brings in a specialist for input

### Agents

Each agent has an adapter tier, model, role, tools, budget, and optional Claude Code configuration:

```yaml
agents:
  researcher:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "Financial market researcher."
    tools: [file_read, file_write, web_search]
    budget:
      max_tokens: 30000
      max_cost_usd: 1.50
    claude_code:
      permission_mode: plan
      append_system_prompt: "Always cite sources."
      disabled_commands: [commit, push]
```

### Available Tools

| YAML name | Expands to | Description |
|-----------|-----------|-------------|
| `file_read` | Read, Glob, Grep | Read files, search by pattern |
| `file_write` | Write, Edit | Create and modify files |
| `web_search` | WebSearch, WebFetch | Search the web, fetch URLs |
| `shell_exec` | Bash | Execute shell commands |

### Budgets

Hard limits on 5 dimensions, enforced at workflow and per-agent level:

| Field | Description |
|-------|-------------|
| `max_tokens` | Total tokens consumed |
| `max_api_calls` | Number of LLM API calls |
| `max_time_seconds` | Wall-clock execution time |
| `max_cost_usd` | Estimated USD cost |
| `max_concurrent_tasks` | Parallel task limit |

### Event Log

Every state change is an immutable event in SQLite. All state is derived from events. Workflows can be fully replayed, and compliance reports generated from the audit trail.

## Next Steps

- See the [README](../README.md) for the full feature list, CLI reference, and roadmap
- [Workflow Authoring Guide](workflow_guide.md) — YAML syntax, DAG patterns, gates, budgets
- [Adapter Development Guide](adapter-guide.md) — Building custom agent adapters
