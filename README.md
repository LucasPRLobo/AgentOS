# AgentOS

**Governance and orchestration for autonomous AI agents.**

AgentOS coordinates multiple AI agents — Claude Code sessions, API-based models, custom adapters — working together in structured workflows. It enforces hard budget limits, capability-based security, human approval gates, and records every state change in an append-only event log.

This is not a prompt-chaining framework. The agents AgentOS manages are real autonomous processes with tool access, file systems, and independent decision-making. AgentOS doesn't replace them — it makes them work together safely.

## Why AgentOS?

Most "multi-agent" frameworks chain API calls. AgentOS orchestrates actual agent runtimes:

- **Budget enforcement**: Hard limits on tokens, cost, time, API calls, and concurrency. Exceeding any limit halts execution cleanly — no surprise bills.
- **Capability-based security**: Fine-grained tool allowlists, path scoping, and domain whitelists per agent. Agents only access what they're explicitly permitted to use.
- **Human-in-the-loop gates**: Pause workflows for human review, approval, or input before critical steps proceed. Gate feedback flows as context to downstream tasks.
- **Complete audit trail**: Every state change is an immutable event in SQLite. Replay any workflow from its event log. Generate compliance reports.
- **DAG-based workflows**: Define task dependencies, parallel execution, conditional branching, and fan-out/fan-in patterns in YAML.
- **Agent-agnostic**: Built-in adapters for Claude Code (Tier 2) and API-based models (Tier 1). Write custom adapters for any agent system.

## Installation

### 1. Install AgentOS

```bash
git clone https://github.com/LucasPRLobo/AgentOS.git
cd AgentOS
pip install -e ".[dev]"
```

**Requirements:**
- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable set
- No external databases or services needed — AgentOS uses SQLite with WAL mode

### 2. Install Claude Code (for Tier 2 agents)

AgentOS uses Claude Code as its primary Tier 2 agent runtime. Each agent in your workflow spawns a Claude Code instance with scoped tools, workspace isolation, and budget limits.

```bash
# Install Claude Code CLI globally
npm install -g @anthropic-ai/claude-code
```

Verify installation:

```bash
claude --version
```

> **Note**: Claude Code requires Node.js 18+. If you don't have Node.js installed: https://nodejs.org/

### 3. Set up your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Add to your shell profile (`~/.bashrc`, `~/.zshrc`) to persist across sessions.

### 4. Verify everything works

```bash
# Validate an example workflow (no API calls)
agentos workflow doctor examples/quick_research.yaml

# Run the demo with stub executors (no API calls, no cost)
agentos demo examples/linear_research.yaml --db demo.db
```

## How AgentOS Connects to Claude Code

AgentOS doesn't embed or replace Claude Code — it orchestrates it. When a workflow runs, AgentOS:

1. **Spawns** a Claude Code process for each task, in the task's isolated workspace directory
2. **Configures** it with the agent's role (system prompt), scoped tools, and any Claude Code-specific settings
3. **Monitors** execution — tracking token usage, cost, and time against budget limits
4. **Collects** the structured output (`manifest.json`) that the agent produces
5. **Passes** that output as context to downstream tasks in the DAG

Each Claude Code agent runs with `--print` mode (non-interactive) and only has access to the tools you explicitly allow in the YAML. AgentOS blocks tools like `Agent`, `TodoWrite`, and `ToolSearch` to prevent agents from spawning uncontrolled sub-agents.

### Agent configuration in YAML

A minimal Tier 2 agent:

```yaml
agents:
  researcher:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a financial researcher. Analyze market data and produce findings."
    tools: [file_read, file_write, web_search]
    budget:
      max_tokens: 30000
      max_cost_usd: 1.50
```

### Advanced Claude Code configuration

For fine-grained control over how Claude Code runs, use the `claude_code` block:

```yaml
agents:
  analyst:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a data analyst."
    tools: [file_read, file_write]
    claude_code:
      # Permission mode: plan (review before actions), default, auto
      # Note: bypassPermissions is blocked — governance platforms never bypass
      permission_mode: plan

      # Append extra instructions to the agent's role prompt
      append_system_prompt: "Always include confidence scores (1-10) with findings."

      # Override model for this specific agent
      model: claude-sonnet-4-6

      # Limit conversation turns to prevent runaway agents
      max_turns: 15

      # Give the agent access to additional directories beyond its workspace
      add_dirs: ["/data/shared-datasets"]

      # Block specific slash commands
      disabled_commands: [commit, push]

      # Connect MCP servers for extended capabilities
      mcp_config:
        - '{"mcpServers": {"finance-data": {"command": "npx", "args": ["-y", "finance-mcp-server"]}}}'
```

### Tool mapping

YAML tool names are human-readable shortcuts that expand to Claude Code's actual tool names:

| YAML name | Claude Code tools | What the agent can do |
|-----------|------------------|----------------------|
| `file_read` | Read, Glob, Grep | Read files, search by name/pattern, search content |
| `file_write` | Write, Edit | Create new files, modify existing files |
| `web_search` | WebSearch, WebFetch | Search the web, fetch specific URLs |
| `web_fetch` | WebFetch | Fetch specific URLs |
| `shell_exec` | Bash | Execute shell commands |

Agents **only** get the tools you list. An agent with `tools: [file_read]` cannot write files or access the web, even though Claude Code normally has those capabilities. This is how AgentOS enforces capability-based security at the orchestration layer.

### What happens at runtime

```
$ agentos workflow run examples/quick_research.yaml --db run.db --param topic="AI regulation"

  [12:00:01] START  quick_research (workflow_id: wf-abc123)
  [12:00:01] RUN    research → researcher (claude-sonnet-4-6)
                    Tools: Read, Glob, Grep, Write, Edit, WebSearch, WebFetch
                    Workspace: /tmp/agentos/wf-abc123/shared/research/
  [12:01:45] DONE   research → SUCCEEDED (tokens: 12,340 | cost: $0.04 | time: 104s)
  [12:01:45] END    quick_research — 1/1 tasks succeeded

  Results: /tmp/agentos/wf-abc123/shared/research/manifest.json
```

Behind the scenes, AgentOS ran:
```
claude --print --model claude-sonnet-4-6 \
  --allowedTools "Read,Glob,Grep,Write,Edit,WebSearch,WebFetch" \
  --disallowedTools "Agent,TodoWrite,ToolSearch" \
  --append-system-prompt "..." \
  -p "Research AI regulation and produce a summary..."
```

The agent worked autonomously in its scoped workspace, produced a `manifest.json` with structured findings, and AgentOS recorded every state change in the event log.

## Features

### Conditional Branching

Tasks can route execution based on their output. Conditions are evaluated safely (AST-based, no `eval()`) against the predecessor's manifest:

```yaml
tasks:
  run_tests:
    name: run_tests
    agent: developer
    description: "Run the test suite and report pass/fail."
    conditions:
      - target: deploy
        expression: "'passed' in summary.lower()"
      - target: fix_code
        expression: "'fail' in summary.lower()"

  deploy:
    name: deploy
    agent: deployer
    depends_on: [run_tests]

  fix_code:
    name: fix_code
    agent: fixer
    depends_on: [run_tests]
```

Only the branch whose condition matches will execute. This enables test-then-deploy, quality gates with fallback paths, and decision trees driven by agent findings.

### Manager Agents and Teams

Manager agents coordinate teams of specialist agents. A manager receives a task, produces an assignment plan, and AgentOS dispatches subtasks to the team members. Managers are restricted to planning — they cannot perform domain work themselves.

```yaml
teams:
  research_team:
    manager: research_director
    members:
      - fundamental_analyst
      - technical_analyst
      - macro_economist
    description: "Conducts comprehensive investment research."
    budget:
      max_tokens: 500000
      max_cost_usd: 8.00
    workspace: research

agents:
  research_director:
    adapter: manager
    model: claude-sonnet-4-6
    role: "Coordinate the research team. Assign work, do NOT research yourself."
    tools: [file_read, file_write]
    members:
      - fundamental_analyst
      - technical_analyst
      - macro_economist
```

The manager produces an `assignment_plan.json` specifying which members handle which subtasks. AgentOS enforces tool isolation per member — each member only gets the tools defined in their own agent config, not the manager's.

### Adversarial Validation

Adversarial tasks challenge other agents' outputs to catch hallucinations, weak reasoning, and overlooked risks before they propagate downstream:

```yaml
tasks:
  adversarial_challenge:
    name: adversarial_challenge
    agent: adversarial_validator
    type: adversarial
    description: "Challenge the investment thesis. Find flaws, counter-arguments, and risks."
    depends_on: [thesis_formation]
```

The adversarial agent receives the predecessor's output and actively tries to disprove it. Its findings feed into downstream tasks alongside the original thesis, giving decision-makers both the argument and the counter-argument.

### Consultation Tasks

Consultation tasks bring in a specialist for input without transferring task ownership:

```yaml
tasks:
  cio_clarification:
    name: cio_clarification
    agent: cio
    type: consultation
    description: "CIO reviews the full picture and provides strategic guidance."
    depends_on: [full_compliance_review]
```

### Message Channels

Agents can communicate asynchronously through broker-mediated channels. Every message is logged as an event:

```yaml
channels:
  research_feed:
    name: research_feed
    mode: broadcast
    max_buffer: 100
  risk_alerts:
    name: risk_alerts
    mode: queue
    max_buffer: 50
```

Channels enable progressive collaboration — a research agent can publish partial findings while still working, and downstream agents start processing immediately.

### Dynamic Agent Spawning

Workflows can spawn specialist agents at runtime when the existing team lacks specific expertise:

```yaml
spawn_policy:
  allow_spawn: true
  require_approval: true      # Human must approve each spawn
  max_spawns_per_workflow: 3
  allowed_archetypes: [sector_specialist]

archetypes:
  sector_specialist:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "Deep expertise on a specific industry vertical."
    default_tools: [web_search, file_read, file_write]
```

### Cross-Run Memory

Agents can learn from previous workflow executions. Memory persists across runs with configurable decay:

```yaml
memory:
  enabled: true
  decay_rate: 0.05
  min_confidence: 0.1
  max_entries: 10000
```

### Workflow Resume

Partially completed workflows can be resumed from any point. Completed task outputs are replayed from workspace manifests — no need to re-execute successful tasks:

```bash
agentos workflow resume workflow.yaml <workflow-id> --db run.db \
  --start-from thesis_formation \
  --reuse-workspace <previous-run-id>
```

### Compliance Reports

Generate audit artifacts from any workflow's event log. Reports cover execution summary, agent actions, human oversight events, budget compliance, security checks, and anomaly flags:

```bash
agentos compliance-report <workflow-id> --db run.db --format html -o audit.html
```

## Quick Start

### 1. Validate a workflow

```bash
agentos workflow doctor examples/quick_research.yaml
```

The doctor checks for DAG issues, invalid tool names, missing capabilities, and budget problems before you run anything.

### 2. Run a workflow

```bash
# Simple single-agent research (parameterized)
agentos workflow run examples/quick_research.yaml \
  --db research.db \
  --param topic="autonomous vehicle regulation in 2026"

# Multi-agent analysis with parallel tasks and approval gate
agentos workflow run examples/hedge_fund_analysis.yaml \
  --db analysis.db \
  --param ticker=NVDA \
  --param sector=semiconductors
```

### 3. Manage gates

When a workflow hits an approval gate, it pauses and waits for human input:

```bash
# See pending gates
agentos gate list --db analysis.db

# Review and approve (with optional feedback that flows to downstream tasks)
agentos gate approve <gate-id> --db analysis.db

# Or reject with feedback
agentos gate reject <gate-id> --db analysis.db --feedback "Need more data on China exposure"

# Provide structured input to an input gate
agentos gate respond <gate-id> --db analysis.db -m "Focus on supply chain risks"
```

### 4. Resume after gate approval

```bash
agentos workflow resume examples/hedge_fund_analysis.yaml <workflow-id> --db analysis.db
```

### 5. Inspect results

```bash
# Workflow status overview
agentos status --db analysis.db

# Full event timeline
agentos events --db analysis.db

# Cost breakdown by agent
agentos cost --db analysis.db

# Replay the complete execution from event log
agentos replay --db analysis.db --workflow-id <id>

# Generate compliance report
agentos compliance-report <workflow-id> --db analysis.db --format html -o report.html
```

### Demo mode (no LLM calls)

To explore the system without spending API credits:

```bash
agentos demo examples/fanout_with_gate.yaml --db demo.db --pause-at-gates
```

This runs workflows with stub executors that exercise the full kernel: DAG scheduling, budget tracking, workspace management, event logging, and structured handoffs.

## Workflow YAML Reference

Workflows are YAML files with four sections: agents, tasks, budget, and optional parameters.

### Minimal example

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
    role: "You are a thorough researcher. Investigate the given topic."
    tools: [file_read, file_write, web_search]
    budget:
      max_tokens: 25000

tasks:
  research:
    name: research
    description: "Research ${topic} and produce a summary with key findings."
    agent: researcher
    workspace: shared

parameters:
  topic:
    description: "Topic to research"
    required: true
```

### Parallel tasks with gate

```yaml
name: hedge_fund_analysis
version: "1.0"

budget:
  max_tokens: 100000
  max_cost_usd: 5.00
  max_concurrent_tasks: 3

agents:
  market_researcher:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a financial market researcher specializing in equity analysis."
    tools: [file_read, file_write, web_search]

  macro_analyst:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a macroeconomic analyst."
    tools: [file_read, file_write, web_search]

  strategist:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are an investment strategist."
    tools: [file_read, file_write]

tasks:
  market_research:
    name: market_research
    description: "Research current market conditions for ${ticker}."
    agent: market_researcher
    workspace: shared

  macro_analysis:
    name: macro_analysis
    description: "Analyze the macroeconomic environment for ${sector}."
    agent: macro_analyst
    workspace: shared

  risk_review:
    name: risk_review
    type: approval_gate
    prompt: "Review research and macro analysis before recommendation."
    depends_on: [market_research, macro_analysis]

  investment_recommendation:
    name: investment_recommendation
    description: "Synthesize research into an investment recommendation for ${ticker}."
    agent: strategist
    workspace: shared
    depends_on: [risk_review]

parameters:
  ticker:
    description: "Stock ticker symbol"
    default: "AAPL"
  sector:
    description: "Market sector"
    default: "technology"
```

### Available tools

| YAML name | Expands to | Description |
|-----------|-----------|-------------|
| `file_read` | Read, Glob, Grep | Read files, search by pattern, search content |
| `file_write` | Write, Edit | Create and modify files |
| `web_search` | WebSearch, WebFetch | Search the web, fetch URLs |
| `shell_exec` | Bash | Execute shell commands |
| `web_fetch` | WebFetch | Fetch specific URLs |

### Task types

- **Agent task** (default): Executed by an AI agent. Must specify `agent`.
- **Approval gate** (`type: approval_gate`): Pauses workflow until human approves or rejects.
- **Input gate** (`type: input_gate`): Pauses workflow until human provides input.

### Adapter tiers

| Adapter | YAML value | Control level |
|---------|-----------|---------------|
| Tier 1 — API | `tier1` | Full control. AgentOS runs the tool-calling loop. |
| Tier 2 — Claude Code | `tier2_claude_code` | Monitored. Claude Code runs autonomously; AgentOS enforces workspace, budget, and validates output. |
| Tier 2 — Aider | `tier2_aider` | Monitored. Aider handles code editing. |
| Manager | `manager` | Delegates subtasks to member agents. |

### Claude Code agent configuration

Tier 2 Claude Code agents support additional configuration for fine-grained control:

```yaml
agents:
  researcher:
    adapter: tier2_claude_code
    model: claude-sonnet-4-6
    role: "You are a financial researcher."
    tools: [file_read, file_write, web_search]
    claude_code:
      permission_mode: plan           # plan, default, auto (bypassPermissions blocked)
      append_system_prompt: "Always cite sources with URLs."
      model: claude-sonnet-4-6        # Override model per agent
      max_turns: 10                   # Limit conversation turns
      add_dirs: ["/data/datasets"]    # Additional readable directories
      disabled_commands: [commit, push]  # Block specific slash commands
      mcp_config:                     # MCP server configurations
        - '{"mcpServers": {"finance": {"command": "npx", "args": ["-y", "finance-mcp"]}}}'
```

| Field | Description |
|-------|-------------|
| `permission_mode` | Claude Code permission mode. `bypassPermissions` is blocked — governance platforms never bypass. |
| `append_system_prompt` | Extra instructions appended to the agent's role prompt. |
| `mcp_config` | MCP server configs (JSON strings or file paths) for extending agent capabilities. |
| `disabled_commands` | Slash commands to disable (e.g., `commit`, `push`). |
| `model` | Override the default model for this specific agent. |
| `max_turns` | Cap the number of conversation turns. |
| `add_dirs` | Additional directories the agent can access beyond its workspace. |

### Parameters

Workflows support runtime parameters with `${param_name}` substitution in task descriptions and agent roles:

```bash
agentos workflow run workflow.yaml --param key1=value1 --param key2=value2
```

Parameters can have defaults and be marked as required:

```yaml
parameters:
  topic:
    description: "Research topic"
    required: true
  depth:
    description: "Research depth"
    default: "comprehensive"
```

## Core Concepts

### Event-Sourced State

All state is derived from an append-only event log in SQLite. Nothing mutates silently. Every task state change, budget consumption, gate resolution, file operation, and capability check is recorded as an immutable event. This means:

- Any workflow can be fully replayed from its event log
- Audit trails are tamper-evident
- Debugging is deterministic — replay the events to reproduce any state

### Budget Enforcement

Budgets are enforced at both workflow and per-agent levels across 5 dimensions:

| Dimension | Description |
|-----------|-------------|
| `max_tokens` | Total tokens consumed |
| `max_api_calls` | Number of LLM API calls |
| `max_time_seconds` | Wall-clock execution time |
| `max_cost_usd` | Estimated USD cost |
| `max_concurrent_tasks` | Parallel task limit |

These are hard limits. When any limit is reached, execution halts cleanly and the event log records exactly what happened and why.

### Task State Machine

```
PENDING → RUNNING → SUCCEEDED
                  → FAILED
                  → WAITING (gate) → RUNNING (after approval)
```

Every transition emits an event. Failed tasks trigger workspace garbage collection. The state machine rejects invalid transitions (e.g., SUCCEEDED → RUNNING).

### Structured Handoffs

Agents produce structured JSON manifests (`manifest.json`) with findings, confidence levels, sources, and file references. Downstream agents receive predecessor context automatically. If an agent fails to produce a valid manifest, AgentOS extracts findings from the raw output as a fallback.

### Workspace Isolation

Each task gets its own subdirectory within the workflow workspace. Agents receive a file index of predecessor outputs so they know what context is available without wasting turns searching.

## CLI Reference

```
agentos workflow run FILE --db PATH [--param KEY=VALUE]...
    Run a workflow from a YAML definition.

agentos workflow resume FILE WORKFLOW_ID --db PATH [--start-from TASK] [--reuse-workspace RUN_ID]
    Resume a paused or partially completed workflow.

agentos workflow verify FILE
    Validate workflow YAML structure and DAG.

agentos workflow doctor FILE
    Run comprehensive diagnostics: tool names, capabilities, budget sanity,
    workspace conflicts. Color-coded output with error codes.

agentos workflow schema
    Output JSON Schema for workflow YAML validation.

agentos gate list --db PATH
    List pending gates awaiting human action.

agentos gate approve GATE_ID --db PATH
    Approve a pending gate.

agentos gate reject GATE_ID --db PATH [--feedback TEXT]
    Reject a pending gate with optional feedback.

agentos gate respond GATE_ID --db PATH -m MESSAGE
    Provide input to an input gate.

agentos status --db PATH
    Show workflow and task status overview.

agentos events --db PATH [--type TYPE] [--workflow-id ID]
    Browse the event log with optional filters.

agentos cost --db PATH [--agent AGENT_ID]
    Show cost breakdown by agent and task.

agentos replay --db PATH --workflow-id ID
    Replay a workflow from its event log, reconstructing full state.

agentos compliance-report WORKFLOW_ID --db PATH [--format json|html] [-o FILE]
    Generate an audit/compliance report from the event log.

agentos demo [FILE] [--db PATH] [--pause-at-gates]
    Run a workflow with stub executors (no LLM calls).

agentos audit --db PATH
    Audit event log integrity.

agentos safety --db PATH
    Run safety checks on recorded agent behavior.
```

## Example Workflows

| File | Description | Agents | Pattern |
|------|-------------|--------|---------|
| `quick_research.yaml` | Single-agent topic research | 1 | Linear |
| `linear_research.yaml` | Research → gate → implement | 2 | Linear + gate |
| `code_review.yaml` | Review → gate → fix | 2 | Linear + gate |
| `news_digest.yaml` | News gathering → gate → analysis | 2 | Linear + gate |
| `hedge_fund_analysis.yaml` | Parallel market + macro research → gate → recommendation | 3 | Parallel + gate |
| `conditional_deploy.yaml` | Test → deploy if pass, fix if fail | 3 | Conditional branching |
| `fanout_with_gate.yaml` | Plan → 3 parallel devs → gate → integration | 5 | Fan-out/fan-in |
| `hedge_fund_full.yaml` | Full pipeline: managers, teams, adversarial, channels | 14 | Complex DAG |

## Project Structure

```
agentos/
├── kernel/           # Core infrastructure
│   ├── event_log.py       # Append-only SQLite event log
│   ├── state_machine.py   # Task state machine (event-derived)
│   ├── dag_executor.py    # DAG scheduler + parallel executor
│   ├── budget_manager.py  # 5-dimension budget tracking
│   ├── workspace.py       # Scoped dirs, file tracking, garbage collection
│   ├── gate_manager.py    # Approval + input gates
│   ├── lifecycle.py       # Agent spawn/stop/restart
│   └── replayer.py        # Full state reconstruction from events
├── adapters/         # Agent adapters
│   ├── base.py            # AgentAdapter ABC + validation
│   ├── tier1.py           # API-controlled tool-calling loop
│   └── tier2_claude_code.py  # Claude Code CLI integration
├── security/         # Governance layer
│   ├── capabilities.py    # Capability model + policy
│   ├── enforcer.py        # Tool call interception (Tier 1)
│   ├── secrets.py         # Credential store
│   └── compliance.py      # Audit report generation
├── validation/       # Pre-execution checks
│   ├── workflow_verifier.py  # Static DAG analysis + diagnostics
│   └── adversarial.py       # Adversarial validation nodes
├── schemas/          # Pydantic v2 models
│   ├── events.py, task.py, workflow.py, budget.py
│   ├── agent.py, gate.py, capability.py, workspace.py
│   └── tool_mapping.py    # Tool name → Claude Code tool expansion
├── intelligence/     # Learning layer (wired to live execution)
│   ├── specialization.py  # Cross-workflow agent specialization tracking
│   ├── fine_tuning.py     # Training data pipeline export
│   └── prompt_refiner.py  # Automatic prompt refinement from outcomes
└── cli/              # Click-based CLI
    ├── main.py, workflow.py, status.py, gate.py

tests/
├── unit/             # ~1200+ tests
├── integration/      # Cross-module + chaos tests
└── e2e/              # End-to-end workflow tests

examples/             # Ready-to-use workflow YAML files
docs/                 # Design documents and guides
```

## Writing Custom Adapters

Any agent system can integrate with AgentOS by implementing the `AgentAdapter` interface:

```python
from agentos.adapters.base import AgentAdapter
from agentos.schemas.task import TaskOutput, TaskStatus, TaskMetrics

class MyAdapter(AgentAdapter):
    async def execute_task(self, task_config, workspace_path, context) -> TaskOutput:
        # Run your agent, collect results
        return TaskOutput(
            task_name=task_config.name,
            status=TaskStatus.SUCCEEDED,
            summary="What the agent accomplished",
            findings=["Key finding 1", "Key finding 2"],
            metrics=TaskMetrics(tokens_used=500, cost_usd=0.01),
        )

    async def stop(self):
        # Clean shutdown
        pass
```

See `docs/adapter_guide.md` for the complete contract, a shell-script adapter example, and validation utilities.

## Testing

```bash
# Run all tests
pytest tests/ -x -q

# Unit tests only
pytest tests/unit/ -x -q

# Integration tests (includes chaos/fault tests)
pytest tests/integration/ -m integration -x -q

# End-to-end tests
pytest tests/e2e/ -m e2e -x -q
```

## Security Model

AgentOS treats security as a core feature, not an afterthought:

- **Tool allowlists**: Agents can only use explicitly permitted tools. Unknown tools are blocked.
- **Path scoping**: File access is restricted to designated workspace directories.
- **Subprocess environment whitelisting**: Only safe environment variables are passed to child agent processes. Secrets like `AWS_SECRET_ACCESS_KEY` are never leaked.
- **Safe expression evaluation**: Conditional workflow expressions use AST-based evaluation — no `eval()`.
- **Post-hoc tool verification**: Agent tool usage is verified against policy after execution. Violations are recorded as events.
- **Gate enforcement**: Workflows can require human approval before critical steps. Gates cannot be bypassed programmatically.

## Roadmap

Features under active development or planned for upcoming releases.

### Human-Agent Interaction

- **Confidence-triggered escalation**: Agents automatically request human input when their confidence drops below a configurable threshold, rather than only at predefined gates.
- **Collaborative revision loops**: Human and agent iterate on a task output together — each revision is tracked as an event, building a full edit history.
- **Delegation handoff**: Human takes over a task mid-execution, completes it manually, and the workflow resumes from that point.
- **Live observation mode**: Watch agent work in real-time via the dashboard and inject suggestions without pausing execution.
- **Structured output editing**: Instead of binary approve/reject, humans edit an agent's TaskOutput directly (adjust findings, confidence scores, add context) before it flows to downstream tasks.

### Workflow Orchestration

- **`dependency_mode: any`**: Native "wait for whichever dependency ran" semantic for conditional convergence — currently all dependencies must complete, but branching workflows need fan-in from whichever branch executed.
- **Three delegation modes**: `managed` (AI manager decides assignments — current), `static` (YAML pre-assigns subtasks to members), `direct` (manager does the work itself). Make `static` the default, `managed` opt-in.
- **Retry policies**: Configurable per-task retry with backoff, max attempts, and fallback tasks on exhaustion.
- **Streaming progress**: Real-time token-level output streaming from Tier 2 agents to the dashboard and CLI.

### Observability

- **Structured JSON logging**: Machine-readable logs alongside human-readable CLI output, compatible with log aggregation tools.
- **OpenTelemetry integration**: Trace spans for workflow execution, task dispatch, and agent calls — plug into Grafana, Datadog, or any OTLP-compatible backend.
- **Cost forecasting**: Predict workflow cost before execution based on historical data from similar workflows.

### Security and Compliance

- **Rootless sandboxing**: Bubblewrap (`bwrap`) integration for filesystem and network isolation without requiring root privileges.
- **Signed event logs**: Cryptographic signatures on events for tamper-evident audit trails in regulated environments.
- **Policy-as-code**: Define security policies in YAML/OPA that are enforced at runtime — allowed domains, file path patterns, cost thresholds.

### Platform

- **Visual workflow builder**: Drag-and-drop DAG editor for non-technical users — define agents, connect tasks, configure gates, and run workflows without writing YAML.
- **Workflow marketplace**: Share and discover community workflow templates.
- **Tier 3 adapters**: Best-effort integrations for additional agent runtimes (Devin, Codex, local models via Ollama/vLLM).
- **Multi-machine execution**: Distribute agent tasks across multiple machines with centralized event log coordination.

## License

AgentOS is licensed under the [Business Source License 1.1](LICENSE). The source code is available for non-production use, evaluation, and testing. After 5 years from each release, the code converts to Apache License 2.0.

For commercial licensing inquiries, contact the maintainers.

## Feedback

AgentOS is in early access. We're actively looking for feedback from technical users building real workflows.

**[Share your feedback](https://forms.gle/ZBsbSapfr1Zv54mNA)** — Takes 2 minutes. Covers installation experience, workflow usability, and feature priorities. Your input directly shapes what we build next.

For bugs and feature requests, [open an issue on GitHub](https://github.com/LucasPRLobo/AgentOS/issues).
