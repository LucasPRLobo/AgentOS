# AgentOS Dogfooding Startup Message

Copy and paste this when starting a blank AgentOS workspace:

---

I'm working on AgentOS itself — a collaborative workspace platform where humans and AI agents work together as a team. The project is at /home/lucas-lobo/Programing/AgentOS.

## What AgentOS Is

AgentOS is NOT a prompt-chaining framework. It's a workspace where you describe a goal, a coordinator builds a team of AI agents, and they work concurrently — communicating through a shared board and direct messages — while the human participates as a team member (worker or manager), not just an observer.

Think of it as Slack + Linear for human-AI teams. The core architecture:
- **Concurrent supervisor** — a polling loop that manages agent processes, routes messages, spawns/kills agents
- **Persistent agent sessions** — agents use `claude --continue` to maintain memory across tasks
- **Shared board** (blackboard pattern) — announcements, findings, decisions, questions, alerts visible to all
- **Direct messaging** — FIPA speech acts (inform, request, propose, directive) between agents and human
- **Textual TUI** — terminal interface with F1 Home (coordinator chat), F2 Agent DMs, F3 Board, F4 Tasks
- **Discussion-driven collaboration** — the coordinator asks questions and proposes with rationale, not just dispatches

## Current Status

The backend works: supervisor, board, messaging, backlog, coordinator, persistent sessions, repo map, context curation, verification. The Textual TUI is functional. 1297 tests passing.

## What We're Doing Now: Dogfooding

We're using AgentOS to improve AgentOS. The main problems to solve:

1. **Token efficiency** — workspace runs consume ~30% of Claude Code daily usage. Need to reduce to ~5-10%.
   - Persistent stream-json processes (built but not tested) should reduce cold starts
   - Agents produce stubs instead of working code — need output quality verification
   - Fewer bigger tasks (3-5 not 15) reduce overhead
   
2. **Agent output quality** — agents read 30 files then write a 10-line placeholder. Need:
   - AST-based stub detection (grep for "placeholder", "TODO", empty function bodies)
   - Specific task descriptions with measurable output requirements
   - Output size verification (if task says "build component", output must be >50 lines)

3. **Coordinator intelligence** — coordinator should proactively monitor, re-assign stalled agents, and report progress without being asked

4. **TUI improvements** — DM responses sometimes don't show, input handling needs work, markdown rendering

## Team Structure

I want two specific agents plus whatever the coordinator suggests:

1. **researcher** — searches the web for papers, strategies, approaches, and best practices relevant to the current problem. Analyzes them and proposes concrete solutions. This agent should use WebSearch and WebFetch tools heavily. When we're working on token efficiency, it should find papers on context compression, caching strategies, multi-agent optimization. When working on output quality, it should find research on code generation quality, verification approaches, etc.

2. **coder** — the main implementation agent. Reads the codebase, writes code, runs tests. This agent does the actual engineering work based on the researcher's findings and the coordinator's plan.

The coordinator can suggest additional agents if needed for specific tasks.

## Key Files

- `agentos/workspace/supervisor.py` — the concurrent supervisor (poll→react→write loop)
- `agentos/workspace/persistent_process.py` — stream-json persistent agent processes
- `agentos/workspace/runtime.py` — workspace runtime (state container + API)
- `agentos/workspace/repo_map.py` — codebase indexing for token reduction
- `agentos/workspace/verifier.py` — task output verification
- `agentos/comms/mcp_server.py` — MCP tools agents use (read_board, send_message, etc.)
- `examples/workspace_live.py` — Textual TUI
- `docs/TOKEN_EFFICIENCY_AND_QUALITY_PLAN.md` — detailed plan with research

## How to Start

Let's discuss the approach first. What do you think the most impactful first task should be? I'm leaning toward testing the persistent stream-json processes since that's the biggest token savings (~75% reduction), but I'm open to other priorities.
