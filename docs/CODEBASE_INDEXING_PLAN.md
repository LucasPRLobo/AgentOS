# Codebase Indexing — Implementation Plan

**Goal:** Reduce token usage by 60-80% by giving agents a shared codebase
index instead of having each one independently explore the same files.

---

## The Problem

Every agent currently reads the same files independently:
- 3 agents × ~30 files each = ~90 file reads per workspace run
- Many files read by ALL agents (App.tsx, schemas.py, runtime.py, etc.)
- Average file: ~200 lines = ~800 tokens
- Total wasted: ~50K-70K tokens per run on duplicate reads

## The Solution: Three-Tier Context Architecture

### Tier 1: Repo Map (always loaded, ~1-2K tokens)

A structural overview generated once at workspace start. Every agent
gets this in their system prompt. Inspired by Aider's repo map.

**What it contains:**
```
# AgentOS Repository Map

## Structure
agentos/
├── kernel/         # Core infrastructure
├── adapters/       # Agent adapters (Tier 1/2/3)
├── comms/          # Communication (board, messaging, MCP)
├── workspace/      # Workspace runtime, supervisor, backlog
├── dashboard/      # FastAPI backend + React frontend
├── schemas/        # Pydantic v2 models
├── security/       # Capabilities, secrets
└── cli/            # Click CLI

## Key Classes & Functions
agentos/workspace/supervisor.py
  class WorkspaceSupervisor
    async def run()
    def _spawn_agent(agent_id, task)
    def _on_agent_completed(info)
  class PersistentAgent
    agent_id, session_name, state, pending_messages

agentos/workspace/runtime.py
  class WorkspaceRuntime
    async def run_concurrent(supervisor_config, on_event)
    async def run(coordinator_llm, max_cycles, interactive)

agentos/comms/board_manager.py
  class BoardManager
    def post(post) → str
    def get_state() → BoardState
    def render_compact(max_tokens) → str

agentos/workspace/backlog.py
  class BacklogManager
    def create_task(task) → str
    def claim_task(task_id, participant_id)
    def propose_task(task) → str
    def finalize_spec(task_id, spec, approach, expected_output)

agentos/comms/schemas.py
  class BoardPost: post_id, section, author_type, content, speech_act
  class DirectMessage: message_id, sender_id, recipient_id, content
  class AgentStatus: agent_id, state, current_task
  class BoardState: version, announcements, team_status, recent_posts

agentos/workspace/schemas.py
  class BacklogTask: task_id, title, status, assigned_to, spec
  class WorkspaceConfig: name, goal, team, budget, coordinator
  class SupervisorConfig: poll_interval, max_concurrent, agent_timeout

## API Surface (dashboard)
GET  /api/workspaces               → list workspaces
GET  /api/workspaces/:id           → workspace state
GET  /api/workspaces/:id/board     → board state
POST /api/workspaces/:id/board     → post to board
GET  /api/workspaces/:id/backlog   → task list
POST /api/workspaces/:id/messages  → send message
WS   /ws/workspace/:id             → real-time updates
```

**How to generate it:**
- Parse Python files with `ast` module (built-in, no tree-sitter needed)
- Extract: class names, method signatures, key imports
- Rank by importance (files that are imported most often = most relevant)
- Budget to ~1500 tokens
- Cache in `.agentos/repo-map.md`
- Refresh when files change (compare mtimes)

### Tier 2: Task-Scoped Context (assembled per task)

The `ContextCurator` (already exists) builds a focused context
package per task. Enhanced with:

- **Relevant modules only**: If the task is about "design the chat panel",
  include summaries of `ChatPanel.tsx`, `message_bus.py`, `schemas.py`
  but NOT `dag_executor.py` or `budget_manager.py`
- **Predecessor findings**: What did the research task find?
  (already implemented)
- **Decisions**: What did the human and coordinator agree on?
  (already implemented)

### Tier 3: On-Demand (agent reads when needed)

Agents can still read full files when they need implementation details.
But the repo map tells them WHERE to look — they don't need to explore.

---

## Implementation Tasks

### Task 1: Repo Map Generator

**New file:** `agentos/workspace/repo_map.py`

```python
class RepoMapGenerator:
    """Generates a structural map of the codebase.

    Uses Python's ast module to extract class/function signatures.
    Ranks files by import frequency (most-imported = most important).
    Produces a token-budgeted markdown overview.
    """

    def __init__(self, project_dir: Path, token_budget: int = 1500):
        self.project_dir = project_dir
        self.token_budget = token_budget

    def generate(self) -> str:
        """Generate the repo map. Returns markdown string."""
        # 1. Scan all .py files
        # 2. Parse each with ast, extract classes + functions
        # 3. Count imports to rank files
        # 4. Build markdown within token budget
        # 5. Cache to .agentos/repo-map.md

    def _extract_signatures(self, filepath: Path) -> list[dict]:
        """Extract class and function signatures from a Python file."""
        # ast.parse → walk → collect ClassDef, FunctionDef, AsyncFunctionDef
        # Return: [{name, type, args, decorators, line}]

    def _rank_files(self, all_files: dict) -> list[str]:
        """Rank files by how many other files import them."""
        # Count import statements referencing each module
        # Most-imported = most structurally important

    def _render(self, ranked_files: list, signatures: dict) -> str:
        """Render the map within token budget."""
        # Start with most important files
        # Add signatures until budget exhausted
        # ~4 chars per token estimate

    def is_stale(self) -> bool:
        """Check if the cached map needs regeneration."""
        # Compare file mtimes against cache timestamp
```

Also handle TypeScript/React files for the frontend:
```python
    def _extract_tsx_components(self, filepath: Path) -> list[dict]:
        """Extract React component names and props from .tsx files."""
        # Regex-based: export function ComponentName({ prop1, prop2 })
        # Simpler than full TS parsing, good enough for a map
```

**Estimated:** ~200 lines

### Task 2: Inject Repo Map into Agent Prompts

**Modify:** `agentos/workspace/supervisor.py`

In `_build_agent_cmd`, prepend the repo map to the agent prompt:

```python
# Load repo map (generated once, cached)
repo_map = self._get_repo_map()
prompt = (
    f"## Codebase Overview\n{repo_map}\n\n"
    f"You are {agent_id}. Your task:\n..."
)
```

The map is loaded once and shared — not regenerated per agent.

**Estimated:** ~30 lines

### Task 3: Frontend File Map

**New section in repo map generator:**

Handle `.tsx`, `.ts`, `.css` files for the frontend:
```
agentos/dashboard/frontend/src/
├── App.tsx                    Main router
├── pages/
│   ├── WorkspacePage.tsx      Three-panel workspace view
│   └── WorkspaceListPage.tsx  Workspace grid
├── components/workspace/
│   ├── BoardFeed.tsx          Live board post feed
│   ├── ChatPanel.tsx          Agent messaging
│   ├── KanbanBacklog.tsx      Task kanban board
│   └── TeamRoster.tsx         Agent status sidebar
├── hooks/
│   └── useWorkspace.ts        Real-time state via WebSocket
├── api/
│   └── workspace.ts           REST client for workspace API
└── types/
    └── workspace.ts           TypeScript interfaces
```

**Estimated:** ~50 lines added to generator

### Task 4: Smart Agent Prompting

**Modify:** `agentos/workspace/supervisor.py`

Instead of "read the codebase", agents get:

```
## Codebase Overview
[repo map — 1500 tokens]

## Your Task
Research dashboard UX patterns.

## Instructions
The repo map above shows the project structure. Use it to know
WHERE to look. Only read files you actually need for your task.
Do NOT explore the entire codebase — the map already tells you
what exists and where.
```

This transforms agent behavior from "explore everything" to
"look up what you need."

**Estimated:** ~20 lines

### Task 5: Workspace CLAUDE.md

**New:** Write a `CLAUDE.md` into each workspace directory so agents
launched with `--add-dir` automatically get project context.

```python
def write_workspace_claude_md(workspace: Path, config: WorkspaceConfig,
                                repo_map: str) -> None:
    """Write a CLAUDE.md that Claude Code auto-loads."""
    content = f"""# Workspace: {config.name}

## Goal
{config.goal}

## Team
{team_list}

## Codebase
{repo_map}

## Communication
Use MCP tools: read_board, post_to_board, check_messages, send_message.
Check the board and messages frequently. Respond to human messages immediately.
"""
    (workspace / "CLAUDE.md").write_text(content)
```

This means agents get context automatically without us injecting
it into the prompt. Claude Code reads CLAUDE.md before doing anything.

**Estimated:** ~40 lines

---

## Expected Token Savings

| Before | After | Savings |
|---|---|---|
| Each agent reads ~30 files (~24K tokens) | Repo map: ~1.5K tokens + 5 targeted reads (~4K tokens) | ~77% |
| 3 agents × 24K = 72K tokens on file reads | 3 × 5.5K = 16.5K tokens | 55.5K saved per run |
| Coordinator reads entire codebase (~50K tokens) | Repo map: 1.5K + targeted reads | ~90% |
| Total per workspace run: ~120K on file reads | ~20K on file reads | **83% reduction** |

---

## Implementation Order

```
Task 1 (Repo Map Generator) ──→ Task 2 (Inject into prompts)
                              ──→ Task 3 (Frontend map)
                              ──→ Task 5 (Workspace CLAUDE.md)
Task 4 (Smart prompting) ────→ (can do alongside any task)
```

Task 1 is the foundation. Tasks 2-5 are independent once Task 1 exists.

**Total estimated: ~340 lines of new code.**
