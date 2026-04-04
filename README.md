# AgentOS

**A collaborative workspace where humans and AI agents work together as a team.**

AgentOS is not another prompt-chaining framework. It's a workspace — like Slack meets Linear for human-AI teams. You describe a goal, a coordinator builds a team of AI agents, and they work concurrently: researching, designing, coding, reviewing — while communicating through a shared board and direct messages. You participate whenever you want, as a worker or a manager.

## What It Looks Like

```
 AgentOS │ Dashboard Design │ ● ACTIVE │ 5/9 tasks │ 2 running │ 45K tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 AGENTS                       COORDINATOR
 ● researcher                 coordinator: Research phase is done. Designer is
   📖 Reading ChatPanel.tsx    working on the layout spec now. Anything you
 ● designer                   want me to adjust?
   🔧 WebSearch: Linear UX
 ○ architect                  you: Focus the designer on the chat panel —
 ◉ lucas (you)                that's the highest priority component.

                              coordinator: Got it. I'll redirect the designer
                              to prioritize the chat panel. The researcher
                              just finished — their report is on the board.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 F1 Home  F2 Agents  F3 Board  F4 Tasks                          Ctrl+Q Quit
```

## Key Features

### Concurrent Agent Teams

Agents run simultaneously as Claude Code instances. They read each other's work, message teammates, and post findings to the shared board. The supervisor manages all of this — spawning agents, routing messages, detecting stalls.

### Human as Team Member

You're not an approver waiting at a gate. You're in the room:
- **Chat with the coordinator** — ask questions, give direction, adjust plans
- **DM any agent** — "researcher, also check Slack's UX patterns"
- **Claim tasks** — work alongside the agents as a contributor
- **Post to the board** — everyone (agents + human) sees your messages
- **Create tasks** — add work items on the fly

### Persistent Agent Sessions

Agents use `claude --continue` to maintain conversation history. When you DM an agent, they remember everything they've done. If they're busy, the supervisor interrupts them — they respond to your message, then resume their task.

### Shared Board (Blackboard Pattern)

A live, structured workspace board visible to all participants:
- **Announcements** — project goals, pinned decisions
- **Posts** — agent findings, human directives
- **Decisions** — recorded choices with rationale
- **Questions** — open items needing team input
- **Alerts** — stalls, failures, budget warnings

### Token-Efficient

A repo map (~1,400 tokens) gives agents the full project structure so they don't waste tokens exploring. Coordinator responses use Sonnet. DM responses use 3 turns max. Expected **75% token reduction** vs. naive multi-agent approaches.

## Quick Start

### Prerequisites

- Python 3.11+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- `ANTHROPIC_API_KEY` set

### Install

```bash
git clone https://github.com/LucasPRLobo/AgentOS.git
cd AgentOS
pip install -e ".[dev]"
pip install textual
```

### Run

```bash
# Start a blank workspace — coordinator asks what you want to work on
python examples/workspace_live.py

# Start from a workspace config
python examples/workspace_live.py examples/dashboard_design.yaml

# Skip coordinator decomposition (saves tokens)
python examples/workspace_live.py examples/dashboard_design.yaml --skip-coordinator

# Mock mode for testing the TUI (zero tokens)
python examples/workspace_live.py examples/dashboard_design.yaml --mock
```

### TUI Controls

| Key | Action |
|-----|--------|
| F1 | Home — chat with the coordinator |
| F2 | Agent DMs — ← → to cycle agents |
| F3 | Board — shared team board |
| F4 | Tasks — backlog view |
| Ctrl+Q | Quit |
| Ctrl+P | Pause/Resume |

### Commands

Type text to chat with the coordinator (home view) or DM the current agent (agent view).

| Command | What |
|---------|------|
| `/tasks` | Show task list |
| `/board` | Show full board |
| `/claim N` | Claim task N as a worker |
| `/task Title` | Create a new task |
| `/msg agent text` | Direct message an agent |
| `/files` | Show workspace files |
| `/status` | Agent status details |
| `/pause` | Pause the workspace |
| `/quit` | Stop and exit |

Commands autocomplete when you type `/`.

## Workspace YAML

```yaml
workspace:
  name: "Dashboard Design"
  goal: |
    Research and design a dashboard frontend with real-time board,
    kanban backlog, and chat interface for human-agent teams.

  team_mode: suggest
  budget:
    max_cost_usd: 8.00

  coordinator:
    model: opus
    auto_decompose: true

  team:
    - name: researcher
      type: agent
      specialization: "UX patterns and competitor analysis"

    - name: designer
      type: agent
      specialization: "Layout, components, interaction design"

    - name: architect
      type: agent
      specialization: "React architecture, state, WebSocket"

    - name: lucas
      type: human
      roles: [lead, reviewer]

  acceptance_criteria:
    - "UX research report produced"
    - "Design specification with wireframes"
    - "Technical architecture document"
```

## Architecture

### The Supervisor Model

AgentOS uses a **concurrent supervisor** — not a sequential executor. Every 2-3 seconds, the supervisor:

1. **Collects** — checks agent completions, reads outbox messages, reads human commands
2. **Reacts** — routes messages, processes events, invokes coordinator if needed
3. **Spawns** — launches agents for ready tasks (up to concurrency limit)
4. **Checks** — completion detection, budget, stall detection
5. **Writes** — updates shared state files (board.json, agent inboxes)

### Communication

Agents communicate through file-based MCP tools:
- `read_board` — read the shared workspace board
- `post_to_board` — share findings with the team
- `check_messages` — check for direct messages
- `send_message` — message a teammate or the human
- `report_progress` — report current activity

### Persistent Sessions

Each agent maintains a Claude Code session via `--continue`:
- First task: `claude --print --name "ws-researcher" -p "Task: ..."`
- New task: `claude --print --continue --name "ws-researcher" -p "New task: ..."`
- DM response: `claude --print --continue --name "ws-researcher" -p "Human says: ..."`

Full conversation history is preserved. Agents remember everything.

### Token Optimization

- **Repo map** — 1,400-token structural overview replaces 50K+ tokens of file exploration
- **Workspace CLAUDE.md** — auto-generated context file agents load automatically
- **Curated task context** — only relevant predecessor findings, not full dumps
- **Model routing** — Sonnet for DM responses and coordinator chat, Opus for complex tasks

## Project Structure

```
agentos/
├── workspace/        # Core: supervisor, runtime, backlog, coordinator
├── comms/            # Board, messaging, MCP server, discussions
├── kernel/           # Event log, DAG executor, budget, sequences
├── adapters/         # Tier 1 (API) + Tier 2 (Claude Code)
├── dashboard/        # FastAPI backend + React frontend
├── schemas/          # Pydantic v2 models
├── security/         # Capabilities, secrets, enforcer
├── intelligence/     # Knowledge graph, specialization
├── cli/              # Click CLI
└── validation/       # Workflow verification

examples/
├── workspace_live.py      # Textual TUI (primary interface)
├── dashboard_design.yaml  # Example workspace config
└── *.yaml                 # Workflow configs

tests/                     # 1297+ unit tests
docs/                      # Design documents + agent-produced specs
```

## Testing

```bash
# All unit tests
pytest tests/unit/ -x -q

# Run with mock agents (no tokens)
python examples/workspace_live.py examples/dashboard_design.yaml --mock
```

## How It Differs

| Feature | Typical Multi-Agent | AgentOS |
|---------|-------------------|---------|
| Execution | Sequential chain | Concurrent supervisor |
| Human role | Approver at gates | Team member (worker + manager) |
| Communication | Prompt injection | Shared board + DMs |
| Agent memory | None (fresh each time) | Persistent sessions (--continue) |
| Context | Full dump every time | Curated per-task + repo map |
| Cost control | Hope for the best | Budget enforcement + model routing |
| Observability | Logs | Live TUI + event stream |

## License

Business Source License 1.1. Converts to Apache 2.0 after 5 years.

## Status

AgentOS is in active development. The concurrent workspace, TUI, and communication layer are functional. The web dashboard, blank workspace flow, and advanced coordinator features are in progress.

For bugs and feature requests: [GitHub Issues](https://github.com/LucasPRLobo/AgentOS/issues)

**[Share feedback](https://forms.gle/ZBsbSapfr1Zv54mNA)** — 2 minutes, shapes what we build next.
