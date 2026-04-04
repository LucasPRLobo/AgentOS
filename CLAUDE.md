# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentOS is a **collaborative workspace platform for human-AI teams**. You describe a goal, a coordinator builds a team of AI agents, and they work together — concurrently, communicating through a shared board and direct messages — while you participate as a team member, not just an observer.

Think of it as Slack + Linear for human-AI teams: agents post findings, discuss approaches, ask questions, and the human contributes when they want — as a worker (doing tasks) or as a manager (directing the team).

**Status**: Active development. Core workspace runtime, Textual TUI, concurrent supervisor, and communication layer are functional.

## Architecture

### How It Works

```
Human starts workspace → Coordinator discusses goal with human
→ Coordinator proposes team → Human approves
→ Agents spawn concurrently → Work simultaneously
→ Communicate via shared board + DMs → Human participates anytime
→ Coordinator monitors, adjusts, responds to human
→ Tasks complete → Workspace done
```

### Repository Layout

```
agentos/
├── workspace/        # Workspace runtime (the core)
│   ├── supervisor.py      # Concurrent supervisor (poll→react→write loop)
│   ├── runtime.py         # WorkspaceRuntime (state container + API)
│   ├── backlog.py         # Task backlog with spec/review lifecycle
│   ├── schemas.py         # WorkspaceConfig, BacklogTask, SupervisorConfig
│   ├── coordinator_runner.py  # Claude Code coordinator invocations
│   ├── repo_map.py        # Codebase indexing for token reduction
│   ├── completion.py      # Completion detection (4 layers)
│   ├── context_curator.py # Per-task curated context (not full dumps)
│   ├── artifacts.py       # PROJECT.md, PLAN.md, DECISIONS.md, STATE.md
│   ├── verifier.py        # Task output verification
│   ├── hooks.py           # Event-driven hook system (19 events)
│   └── cost_tracker.py    # Budget tracking with cache awareness
├── comms/            # Communication layer
│   ├── board_manager.py   # Shared board (blackboard pattern)
│   ├── message_bus.py     # Direct messaging with FIPA speech acts
│   ├── discussions.py     # Discussion threads at decision points
│   ├── mcp_server.py      # MCP tools for agents (read_board, send_message, etc.)
│   └── comms_state.py     # Per-agent file I/O (inbox, outbox, status)
├── kernel/           # Core infrastructure
│   ├── event_log.py       # EventLog ABC + SQLiteEventLog
│   ├── dag_executor.py    # DAG scheduler (legacy workflow mode)
│   ├── budget_manager.py  # 5-dimension budget tracking
│   └── seq.py             # Shared thread-safe sequence counter
├── adapters/         # Agent adapters
│   ├── tier1.py           # API-controlled tool-calling loop
│   └── tier2_claude_code.py  # Claude Code CLI integration
├── dashboard/        # Web dashboard
│   ├── app.py             # FastAPI with workspace API routes
│   ├── workspace_api.py   # REST + WebSocket for workspace
│   └── frontend/          # React + TypeScript + Vite
├── schemas/          # Pydantic v2 models
├── security/         # Capabilities, secrets, enforcer
├── intelligence/     # Knowledge graph, specialization
├── cli/              # Click-based CLI
└── validation/       # Workflow verification
tests/                # 1297+ unit tests
examples/
├── workspace_live.py      # Textual TUI (primary interface)
├── dashboard_design.yaml  # Example workspace config
└── *.yaml                 # Legacy workflow examples
docs/
├── CONCURRENT_WORKSPACE_PLAN.md
├── CODEBASE_INDEXING_PLAN.md
├── PERSISTENT_AGENTS_PLAN.md
└── workspace-output/      # Agent-produced design specs (206KB)
```

### Key Components

**WorkspaceSupervisor** (`workspace/supervisor.py`): The core runtime. An async polling loop (every 2-3s) that manages concurrent agent processes. Each tick: collect agent completions → route outbox messages → process human commands → spawn agents for ready tasks → check completion → write shared state.

**PersistentAgent**: Agents maintain sessions via `claude --continue`. They go IDLE after tasks (not killed) and can be woken for DMs or new work with full conversation history.

**BoardManager** (`comms/board_manager.py`): Shared blackboard. Sections: announcements, posts, decisions, questions, alerts. All agents and the human read/write to it.

**MessageBus** (`comms/message_bus.py`): Direct messaging with FIPA speech acts (inform, request, propose, directive, etc.). Threading support.

**DiscussionManager** (`comms/discussions.py`): Structured conversations at decision points (kickoff, task_spec, check_in, review, replan, escalation).

**RepoMapGenerator** (`workspace/repo_map.py`): Generates a ~1,400-token structural map of the codebase. Agents get this instead of independently exploring files. 75% token reduction.

### Communication Flow

Agents communicate via file-based I/O through MCP tools:
```
.agentos/
├── board.json              # Live board state (supervisor writes each tick)
├── agents/{id}/inbox.json  # Pending messages for each agent
├── agents/{id}/outbox/     # Messages from each agent
├── agents/{id}/status.json # Agent heartbeat + current activity
├── human/inbox.json        # Messages for the human
├── human/commands.json     # Human commands (claim task, post, message, etc.)
└── events/events.jsonl     # Append-only event stream
```

## Tech Stack

- Python 3.11+
- Pydantic v2 (all schemas)
- SQLite with WAL mode (event log)
- Textual (terminal UI)
- Claude Code CLI (agent runtime via `claude --print --continue`)
- FastAPI + React + TypeScript (web dashboard)
- MCP protocol (agent-to-workspace communication)

## Running

```bash
# Blank workspace (conversation with coordinator)
python examples/workspace_live.py

# From YAML config
python examples/workspace_live.py examples/dashboard_design.yaml

# Skip coordinator (pre-loaded tasks, saves tokens)
python examples/workspace_live.py examples/dashboard_design.yaml --skip-coordinator

# Mock mode (zero tokens, TUI testing)
python examples/workspace_live.py examples/dashboard_design.yaml --mock
```

### TUI Navigation

| Key | Action |
|-----|--------|
| F1 | Home (coordinator chat) |
| F2 | Agent DMs (← → to cycle) |
| F3 | Board |
| F4 | Tasks |
| Ctrl+Q | Quit |
| Ctrl+P | Pause/Resume |

### Commands

| Command | What |
|---------|------|
| (text) | Chat with coordinator (home) or DM agent (agent view) |
| /board | Show full board |
| /tasks | Show task list |
| /claim N | Claim task N as worker |
| /task Title | Create new task |
| /msg agent text | Direct message an agent |
| /files | Show workspace files |
| /status | Agent status details |

## Git Workflow

- `main` → production releases
- `feature/*` → development branches
- Conventional commits: `feat(workspace):`, `fix(comms):`, `test(supervisor):`

## Non-Negotiable Rules

- AgentOS contains zero domain-specific logic — generic orchestration kernel
- Never bypass budget checks or capability enforcement
- All state derivable from the event log (event-sourced)
- Agents communicate through the board and messaging — no side channels
- The human is a first-class participant, not a checkpoint gate
- Prefer clarity over cleverness
