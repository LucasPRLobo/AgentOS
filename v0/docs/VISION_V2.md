# AgentOS — Vision v2

## What Is AgentOS

AgentOS is a framework for creating, running, orchestrating, and monitoring autonomous AI agents. It is the management plane that sits above agent instances — Claude Code sessions, Open Claw instances, custom agents — and gives a user full control over what each agent does, how agents collaborate, and what's happening at any moment.

Think of it as a **project manager for AI agents**.

A user with five Claude Code instances running shouldn't need five terminal windows and manual coordination. AgentOS lets them assign each instance a role, organize them into teams, define communication channels, set approval checkpoints, and watch everything from one place.

## The Problem

Today's autonomous agents (Claude Code, Open Claw, Devin, Codex, etc.) are powerful individually. Each one can read and write files, browse the web, call APIs, use MCP servers, and execute commands. But:

1. **No orchestration.** There's no way to make two Claude Code instances collaborate on the same project with different roles. Each runs in isolation.

2. **No team structure.** You can't say "these three agents are the research team, these two are the analysis team, and the research team feeds results to the analysis team."

3. **No unified monitoring.** When running multiple agents, you have no single view of what's happening, what's blocked, what's finished, and what it's costing.

4. **No human checkpoints.** Agents run to completion or you stop them. There's no built-in way to say "complete this step, then wait for my review before continuing."

5. **No role configuration without code.** Changing an agent's behavior, tools, or constraints requires editing config files or rewriting prompts. Non-technical users are locked out entirely.

AgentOS solves all of these.

## Core Concepts

### Agent

An autonomous AI system capable of operating on a user's machine. It can read/write files, execute commands, access the internet, connect to external services via APIs and MCP servers, and make decisions independently.

AgentOS does not replace these agents. It manages them.

Examples of agents AgentOS can manage:
- Claude Code sessions
- Open Claw instances
- Custom agents built with any framework
- Future autonomous agent tools as they appear

### Team

A named group of agents working toward a shared objective. Teams define:
- Which agents belong
- What role each agent plays
- How they communicate (shared workspace, direct messages, or both)
- What the team's deliverable is

Example: A "Research Team" with a Web Researcher agent, a Data Collector agent, and a Summarizer agent.

### Workflow

The dependency graph that defines execution order across agents and teams. Which agents run first, which wait for others to finish, where human approval is required, and how data flows between steps.

### Workspace

The shared environment where agents and teams operate. Files, data, and artifacts live here. All agents in a team can see the same workspace. AgentOS tracks what each agent creates, modifies, and reads.

### Gate

A human checkpoint in a workflow. When execution reaches a gate, it pauses and waits for the user to review, approve, reject, or provide input before continuing.

## How It Works

```
User
  |
  v
AgentOS (management plane)
  |
  ├── Team: Research
  |   ├── Claude Code #1 (role: web researcher)
  |   ├── Open Claw #2 (role: data collector)
  |   └── Shared workspace: /research/
  |
  ├── Team: Analysis
  |   ├── Claude Code #3 (role: quantitative analyst)
  |   ├── Claude Code #4 (role: report writer)
  |   └── Shared workspace: /analysis/
  |
  ├── Workflow: Research → [approval gate] → Analysis → [approval gate] → Final Report
  |
  └── Monitor: real-time status, costs, logs, artifacts
```

1. **Configure.** The user defines teams, assigns agents to roles, configures each agent's behavior (system prompt, tools, constraints, MCP servers), and builds the workflow.

2. **Launch.** AgentOS spawns agent instances (or connects to existing ones), assigns them their tasks, and starts execution according to the workflow.

3. **Orchestrate.** As agents complete tasks, AgentOS routes outputs between them, triggers downstream agents, enforces gates, and manages the overall flow.

4. **Monitor.** The user sees everything in real time: which agents are running, what they're producing, what's waiting for approval, and how much it's costing.

5. **Intervene.** At any gate (or any time), the user can review outputs, approve/reject, provide input, pause execution, redirect agents, or stop everything.

## Agent Adapter Model

AgentOS doesn't implement agents itself. It defines an **Agent Adapter** interface that any autonomous agent can implement:

```
AgentAdapter
  ├── launch(config) → agent_handle
  ├── assign_task(handle, task) → void
  ├── get_status(handle) → running | waiting | completed | failed
  ├── get_output(handle) → result
  ├── send_message(handle, message) → void
  ├── receive_messages(handle) → messages[]
  ├── stop(handle) → void
  └── get_workspace_changes(handle) → file_changes[]
```

Built-in adapters ship for common agents (Claude Code, Open Claw). Users and developers can build custom adapters for any agent system.

This means AgentOS is **agent-agnostic**. As new autonomous agent tools emerge, they just need an adapter.

### Model Flexibility

Agents in AgentOS are not locked to a specific LLM provider. The framework supports:

- **Autonomous agent tools** — Claude Code, Open Claw, Devin, etc. (via adapters)
- **Cloud API models** — OpenAI, Anthropic, Google, Mistral, etc. (via API keys)
- **Local models** — Ollama, llama.cpp, vLLM, etc. (runs on the user's machine)
- **Custom endpoints** — any OpenAI-compatible API, private deployments, enterprise proxies

Users choose what powers each agent based on their preferences, budget, privacy requirements, and performance needs. A research agent might use GPT-4o for speed, while a code-writing agent uses Claude Code for quality, and a data processing agent uses a local Llama model for privacy. AgentOS doesn't care — it orchestrates them all the same way.

## Two Audiences, One Framework

AgentOS serves both non-technical and technical users — not by dumbing things down, but by providing the right level of control for each.

### For Non-Technical Users

AgentOS facilitates. The experience is visual, guided, and opinionated:

- **Drag-and-drop workflow builder** — assemble teams by dragging agents onto a canvas and connecting them. No code, no config files.
- **Plain-English agent configuration** — describe what you want the agent to do in natural language. "Research the latest developments in AI regulation and summarize the key points." AgentOS translates this into the right system prompt, tools, and constraints.
- **Template gallery** — start from pre-built templates (e.g., "Research Team", "Content Pipeline", "Market Analysis") and customize from there.
- **One-click execution** — hit Run and watch. Approval gates pause execution and show you what the agent produced in a clear review panel. Approve or reject with a click.
- **Dashboard monitoring** — see agent status, outputs, files produced, and costs in a clean visual dashboard. No terminal required.

### For Technical Users

AgentOS allows full control and deep observability:

- **CLI interface** — `agentos team create`, `agentos workflow run`, `agentos status`, `agentos gate approve`. Scriptable, composable, automatable.
- **Agent configuration as code** — define agents, teams, and workflows in YAML/JSON. Version control your orchestration setup.
- **Custom agent adapters** — write an adapter for any agent system. Implement the AgentAdapter interface and plug it in.
- **Event log access** — every state change, agent action, and message is an event. Query the event log directly for debugging, auditing, or building custom analytics.
- **Custom tools** — register new tools that agents can use. Point at any REST API or MCP server.
- **Budget and constraint tuning** — set precise token limits, cost caps, time bounds, and tool restrictions per agent.
- **Programmatic API** — everything the web UI does is available via REST API. Build your own integrations, automations, and monitoring dashboards.

The key principle: **non-technical users never hit a wall, and technical users never feel constrained.** The same underlying framework powers both experiences.

## Interfaces

### Web Dashboard

Visual browser-based interface for:
- Building workflows (drag-and-drop DAG canvas)
- Configuring agents and teams
- Monitoring execution in real time
- Reviewing outputs at approval gates
- Managing workspaces and artifacts
- Viewing costs and analytics

### CLI

Terminal-based interface for power users:
- `agentos team create research --agents "claude-code:researcher, open-claw:collector"`
- `agentos workflow run hedge-fund-daily`
- `agentos status`
- `agentos gate approve <gate-id>`
- Scriptable, automatable, composable with other tools

Both interfaces talk to the same backend. Users can mix and match.

## Demo Product: Private Hedge Fund

The first product built on AgentOS is a **personal AI-powered hedge fund** — a system that researches markets, analyzes opportunities, manages risk, and generates reports. It demonstrates every AgentOS capability in a compelling, real-world domain.

### Teams

**Research Team**
- Market Scanner Agent — monitors news, SEC filings, earnings reports
- Macro Researcher Agent — analyzes economic indicators, central bank policies
- Sector Specialist Agent — deep dives on specific sectors/companies

**Analysis Team**
- Quantitative Analyst Agent — runs models, calculates metrics, backtests strategies
- Risk Manager Agent — assesses portfolio risk, drawdown scenarios, correlation analysis
- Strategy Agent — synthesizes research and analysis into actionable recommendations

**Operations Team**
- Report Writer Agent — generates daily/weekly investment reports
- Portfolio Tracker Agent — monitors current positions, P&L, rebalancing needs
- Compliance Agent — checks recommendations against rules and constraints

### Workflow

```
Market Scanner ──┐
Macro Researcher ─┤──→ [Review Gate] ──→ Quantitative Analyst ──┐
Sector Specialist ┘                      Risk Manager ──────────┤
                                         Strategy Agent ────────┘
                                              │
                                        [Approval Gate]
                                              │
                                    ┌─────────┼─────────┐
                                    v         v         v
                              Report Writer  Portfolio  Compliance
                                    │       Tracker        │
                                    └─────────┬────────────┘
                                              v
                                      Final Dashboard
```

### Why This Demo

1. **Multi-team collaboration** — research feeds analysis feeds operations
2. **Human oversight is natural** — you want to approve investment decisions before acting
3. **Real stakes** — makes the value proposition visceral ("this manages money")
4. **Complex enough** — 9+ agents, 3 teams, multiple gates, shared data
5. **Demonstrable** — produces tangible outputs (reports, charts, recommendations)
6. **Extensible** — easy to add agents (sentiment analyst, alternative data, etc.)

## Architecture Principles

1. **Agent-agnostic.** AgentOS works with any autonomous agent via adapters. No lock-in to a specific LLM or agent framework.

2. **Event-sourced.** Every state change, agent action, message, and decision is an append-only event. Full audit trail. Deterministic replay.

3. **Workspace as ground truth.** Agents collaborate through shared workspaces. Files are the universal interface. Every file change is tracked.

4. **Human-in-the-loop by default.** Gates are first-class. Users review and approve at defined checkpoints. Agents don't make irreversible decisions without oversight.

5. **Observable.** Real-time visibility into what every agent is doing, what they've produced, and what it's costing. No black boxes.

6. **Budget-constrained.** Hard limits on tokens, API calls, time, and cost. Agents operate within defined budgets. Exceeding a budget halts execution cleanly.

7. **Reliable above all else.** AgentOS must be extremely reliable and well-built. Agents managing real work (especially financial) cannot have silent failures, lost state, or undefined behavior.

## Development Strategy

### Phase 1: AgentOS Framework (redesign)

Build the core framework from scratch around the new agent model:
- Agent Adapter interface and lifecycle management
- Team primitives (creation, role assignment, communication)
- Workflow engine (DAG execution with gates, pause/resume)
- Event log (append-only, all state derived from events)
- Workspace management (shared filesystems, change tracking)
- Budget and governance
- CLI interface
- Web dashboard (monitoring, configuration, workflow builder)

### Phase 2: Hedge Fund Demo

Build the private hedge fund product on top of AgentOS:
- Finance-specific agent roles and prompts
- Market data tools and integrations
- Portfolio tracking and analysis tools
- Report generation templates
- Dashboard with financial visualizations

### Phase 3: Polish and Release

- Harden AgentOS framework for external use
- Documentation, tutorials, examples
- Open source the framework
- Continue developing the hedge fund as a real product

## What This Is Not

- **Not a chatbot framework.** Agents are autonomous workers, not conversational assistants.
- **Not a prompt chain tool.** Agents are full autonomous systems with tools, filesystem access, and decision-making capability. Not a sequence of LLM calls.
- **Not a single-agent tool.** The entire point is multi-agent orchestration. One agent is just a degenerate case.
- **Not a replacement for agents.** AgentOS doesn't compete with Claude Code or Open Claw. It makes them work together.
