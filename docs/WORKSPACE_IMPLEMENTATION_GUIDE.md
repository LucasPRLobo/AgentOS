# AgentOS — Workspace Runtime: Implementation Guide

**Companion to:** WORKSPACE_RUNTIME_DESIGN.md
**Date:** March 2026
**Status:** Implementation plan — task-by-task development guide

---

## Prerequisites

Everything in this guide builds on the comms layer (Phase 1-2), which is complete:
- Board + Direct Messaging (schemas, MessageBus, BoardManager, AmbientContextInjector)
- MCP Communication Server (7 tools via stdio)
- Communication Protocols (consultation, review, escalation)
- Board Auto-Update Hooks
- Tier 1 + Tier 2 comms integration
- 154 comms tests passing

All new code goes under `agentos/workspace/` (new package) unless modifying existing modules.

---

## Phase 3A: Workspace Foundation

Goal: A workspace can be created, tasks can be added to the backlog, workers can claim and complete tasks. No AI coordinator yet — this phase is pure infrastructure.

---

### Task 3A.1 — Workspace Schemas

**File:** `agentos/workspace/schemas.py`

Create all Pydantic v2 models for the workspace runtime:

```
TeamMode           — locked, suggest, auto_minor, auto_full
ParticipantType    — human, agent
ParticipantRole    — lead, worker, reviewer, observer
WorkspaceParticipant — name, type, roles, specialization, adapter, model, tools, budget
CoordinatorConfig  — enabled, type, model, authority, auto_decompose, replan_interval
WorkspaceConfig    — name, goal, description, team_mode, budget, coordinator, team,
                     acceptance_criteria, documents, persist

TaskStatus         — open, claimed, in_progress, in_review, revision_needed, done,
                     blocked, cancelled
BacklogTask        — task_id, title, description, created_by, assigned_to, suggested_for,
                     required_role, status, depends_on, blocks, acceptance_criteria,
                     output, budget, priority, computed_priority, estimated_minutes,
                     model_tier, next_task, created_at, claimed_at, completed_at,
                     review_count, stall_count

AgentContextSummary — agent_id, intent, changes_made, decisions, next_steps,
                      confidence, dependencies, entity_references, error_log,
                      tasks_completed, last_active, summary_version

WorkspaceContextSummary — goal, current_status, intent, key_decisions, key_artifacts,
                          open_questions, tasks_completed, tasks_remaining,
                          budget_consumed_pct, team_notes, facts, educated_guesses,
                          current_plan

WorkspaceState     — workspace_id, config, status (active/paused/completed),
                     created_at, last_active
```

**Also add to `agentos/schemas/events.py`:**
```
WORKSPACE_CREATED          = "workspace.created"
WORKSPACE_PAUSED           = "workspace.paused"
WORKSPACE_COMPLETED        = "workspace.completed"
WORKSPACE_TEAM_CHANGED     = "workspace.team_changed"
BACKLOG_TASK_CREATED       = "backlog.task_created"
BACKLOG_TASK_CLAIMED       = "backlog.task_claimed"
BACKLOG_TASK_STARTED       = "backlog.task_started"
BACKLOG_TASK_SUBMITTED     = "backlog.task_submitted"
BACKLOG_TASK_APPROVED      = "backlog.task_approved"
BACKLOG_TASK_REVISION      = "backlog.task_revision"
BACKLOG_TASK_CANCELLED     = "backlog.task_cancelled"
BACKLOG_TASK_UNBLOCKED     = "backlog.task_unblocked"
ASSISTANT_SPAWNED          = "assistant.spawned"
ASSISTANT_COMPLETED        = "assistant.completed"
```

**Tests:** `tests/unit/test_workspace_schemas.py`
- All models construct with required fields
- Defaults are correct
- Serialization round-trip
- Enum values
- WorkspaceConfig from YAML dict (simulates loading from file)

**Estimated: ~200 lines schema, ~120 lines tests**

---

### Task 3A.2 — YAML Loader

**File:** `agentos/workspace/loader.py`

Parse workspace YAML files into `WorkspaceConfig`:

```python
def load_workspace_config(path: Path) -> WorkspaceConfig: ...
def load_workspace_config_from_dict(data: dict) -> WorkspaceConfig: ...
```

Handle:
- `team_mode: dynamic` as alias for `suggest`
- Missing optional fields (defaults)
- Validation errors with clear messages
- Document path resolution (relative to YAML file)

**Tests:** `tests/unit/test_workspace_loader.py`
- Load the example YAML from the design doc
- Missing fields get defaults
- Invalid team_mode raises clear error
- Document paths resolved relative to YAML location

**Estimated: ~60 lines code, ~80 lines tests**

---

### Task 3A.3 — Backlog Manager

**File:** `agentos/workspace/backlog.py`

Core task backlog engine. Thread-safe, event-logged.

```python
class BacklogManager:
    def __init__(self, event_log, seq, workflow_id): ...

    # Lifecycle
    def create_task(self, task: BacklogTask) -> str: ...
    def claim_task(self, task_id, participant_id) -> None: ...
    def start_task(self, task_id) -> None: ...
    def submit_for_review(self, task_id, output: TaskOutput) -> None: ...
    def approve_task(self, task_id, reviewer_id) -> None: ...
    def request_revision(self, task_id, feedback) -> None: ...
    def cancel_task(self, task_id, reason) -> None: ...

    # Dependencies
    def check_dependencies(self, task_id) -> bool: ...
    def unblock_dependents(self, task_id) -> list[str]: ...

    # Chaining
    def chain_next(self, task_id) -> str | None: ...

    # Priority
    def recompute_priorities(self) -> None: ...

    # Querying
    def get_open_tasks(self, role=None) -> list[BacklogTask]: ...
    def get_ready_tasks(self) -> list[BacklogTask]: ...  # Open + dependencies met
    def get_tasks_for(self, participant_id) -> list[BacklogTask]: ...
    def get_blocked_tasks(self) -> list[BacklogTask]: ...
    def get_task(self, task_id) -> BacklogTask: ...
    def get_all_tasks(self) -> list[BacklogTask]: ...

    # Health
    def flag_long_tasks(self) -> list[str]: ...
    def flag_stalled_tasks(self, max_stall_cycles=2) -> list[str]: ...
    def increment_stall(self, task_id) -> None: ...
    def reset_stall(self, task_id) -> None: ...
```

Key behaviors:
- `claim_task` — atomic (thread-safe), fails if already claimed or not OPEN
- `approve_task` — transitions to DONE, triggers `unblock_dependents` + `chain_next`
- `recompute_priorities` — `P(task) = complexity / max(dep_weight + downstream_priority)`, or falls back to manual priority
- `chain_next` — reads `next_task` dict, creates new BacklogTask, returns its ID
- All mutations log events

**Tests:** `tests/unit/test_backlog_manager.py`
- Create, claim, start, submit, approve full lifecycle
- Claim already-claimed task fails
- Dependencies block task (status BLOCKED until deps met)
- `unblock_dependents` transitions BLOCKED → OPEN
- `chain_next` auto-creates follow-up task
- `recompute_priorities` orders tasks correctly
- `flag_long_tasks` catches >35 min estimates
- `flag_stalled_tasks` catches 2+ stall cycles
- Concurrent claiming (thread safety)
- All events logged correctly
- Cancel and revision flows

**Estimated: ~300 lines code, ~250 lines tests**

---

### Task 3A.4 — Workspace Runtime (Basic)

**File:** `agentos/workspace/runtime.py`

The main runtime loop. Phase 3A version is minimal — no AI coordinator, just the infrastructure that manages the backlog, activates workers, and handles lifecycle.

```python
class WorkspaceRuntime:
    def __init__(self, config: WorkspaceConfig, event_log, seq): ...

    # Lifecycle
    def start(self) -> None: ...           # Create workspace, init board, init backlog
    def pause(self) -> None: ...           # Gracefully pause all agents
    def resume(self) -> None: ...          # Resume from paused state
    def complete(self) -> None: ...        # Mark workspace as completed

    # Task management (used by CLI and coordinator)
    def add_task(self, task: BacklogTask) -> str: ...
    def claim_task(self, task_id, participant_id) -> None: ...

    # Worker activation
    def activate_worker(self, participant_id, task_id) -> TaskOutput: ...
    def collect_output(self, task_id, output: TaskOutput) -> None: ...

    # State
    def get_board_state(self) -> BoardState: ...
    def get_backlog(self) -> list[BacklogTask]: ...
    def get_workspace_state(self) -> WorkspaceState: ...
```

Phase 3A `activate_worker` is simple:
1. Build activation context (board state, task, predecessor outputs)
2. Write comms state to workspace
3. Launch agent via appropriate adapter (Tier 1 or Tier 2)
4. Collect output, route outbox messages
5. Update backlog (submit for review or mark done)
6. Update board (agent status, findings)

**No coordinator logic in 3A** — tasks are manually added and claimed via CLI. The runtime just manages the lifecycle.

**Tests:** `tests/unit/test_workspace_runtime.py`
- Start workspace, verify board created with announcement
- Add tasks, verify they appear on backlog
- Claim task, verify status changes
- Collect output, verify board updated
- Pause and resume
- Complete workspace

**Tests:** `tests/integration/test_workspace_basic.py`
- Full flow: create workspace → add tasks → claim → execute (mock adapter) → complete
- Verify event log has all expected events

**Estimated: ~250 lines code, ~200 lines tests**

---

### Task 3A.5 — CLI Workspace Commands

**File:** `agentos/cli/workspace_cli.py`

```
agentos workspace create <yaml-path>       # Create from YAML
agentos workspace create --interactive      # Conversational creation (Phase 3D, stub for now)
agentos workspace show [--workspace-id]     # Show workspace status
agentos workspace pause                     # Pause running workspace
agentos workspace resume                    # Resume paused workspace
agentos workspace complete                  # Mark workspace as completed
agentos workspace export > file.yaml        # Export config

agentos task add <title> [--description] [--depends-on] [--priority]
agentos task claim <task-id>                # Claim a task (as human worker)
agentos task start <task-id>                # Mark task as in-progress
agentos task complete <task-id> [--summary] # Mark task as done
agentos task list [--status open|claimed|done|all]
agentos task show <task-id>

agentos assistant spawn <description> [--tools] [--model]
```

Register in `agentos/cli/main.py`.

**Tests:** `tests/unit/test_cli_workspace.py`
- Each command produces correct output
- Workspace create from YAML
- Task lifecycle via CLI
- Error messages for invalid operations

**Estimated: ~200 lines code, ~150 lines tests**

---

### Phase 3A Checkpoint

At this point you can:
- Create a workspace from YAML
- Add tasks to the backlog manually
- Claim tasks as a human worker
- Mark tasks as complete
- See the board with backlog, status, findings
- Tasks auto-unblock when dependencies complete
- All actions are event-logged

**Not yet working:** AI coordinator, agent activation, context summaries, assistants, completion detection.

**Estimated total for Phase 3A: ~1,010 lines code, ~800 lines tests**

---

## Phase 3B: Coordinator Intelligence

Goal: An AI coordinator decomposes goals, manages the backlog, proposes team changes, and handles failure recovery.

---

### Task 3B.1 — Coordinator Prompt Templates

**File:** `agentos/workspace/coordinator_prompts.py`

Structured prompt templates for each coordinator action:

```python
def build_decomposition_prompt(goal, description, acceptance_criteria,
                                team, documents) -> str: ...

def build_replan_prompt(task_ledger, progress_ledger,
                         completed_tasks, failed_tasks, board_state) -> str: ...

def build_team_proposal_prompt(current_team, capability_gap,
                                task_ledger) -> str: ...

def build_completion_assessment_prompt(goal, acceptance_criteria,
                                        completed_tasks, artifacts) -> str: ...

def build_failure_recovery_prompt(failed_task, error, attempt_history,
                                   available_agents) -> str: ...
```

Each prompt includes:
- Clear role instruction ("You are a project coordinator, not a worker")
- Structured output format (JSON schema for tasks, proposals, assessments)
- Explicit constraints (non-overlapping tasks, 35-min rule, scope anchoring)
- Model routing guidance

**Tests:** `tests/unit/test_coordinator_prompts.py`
- Each template produces valid prompt strings
- All required fields are included
- Output format instructions are present
- Constraint instructions are present

**Estimated: ~200 lines code, ~80 lines tests**

---

### Task 3B.2 — Coordinator Agent

**File:** `agentos/workspace/coordinator.py`

The AI coordinator that uses Tier 1 API calls to reason about the workspace.

```python
class CoordinatorAgent:
    def __init__(self, config: CoordinatorConfig, backlog: BacklogManager,
                 board: BoardManager, bus: MessageBus, event_log, seq,
                 workflow_id, client: Anthropic): ...

    # --- Core actions ---
    async def decompose_goal(self, goal, description, acceptance_criteria,
                              team, documents) -> list[BacklogTask]: ...

    async def handle_task_completed(self, task_id) -> None: ...
    async def handle_task_failed(self, task_id, error) -> None: ...
    async def handle_message(self, message: DirectMessage) -> None: ...
    async def handle_timeout(self, task_id) -> None: ...

    # --- Replanning ---
    async def check_progress(self) -> None: ...
    async def replan(self) -> None: ...

    # --- Team management ---
    async def propose_team_change(self, reason) -> None: ...

    # --- Completion ---
    async def assess_completion(self) -> dict: ...

    # --- Internal state ---
    def update_task_ledger(self) -> None: ...
    def update_progress_ledger(self) -> None: ...
```

Key behaviors:
- `decompose_goal` — single LLM call, parses JSON response into BacklogTask list, posts to backlog + board
- `handle_task_completed` — updates ledgers, checks unblocked tasks, checks if goal is met
- `handle_task_failed` — follows escalation ladder: retry → reassign → replan → decompose → escalate
- `check_progress` — compares current progress_ledger to previous. If stalled 2+ cycles, trigger `replan`
- `replan` — rewrites both ledgers, may create new tasks or cancel stale ones
- `propose_team_change` — posts proposal to board. In suggest mode, waits. In auto_full, executes.
- `assess_completion` — evaluates acceptance criteria, returns recommendation
- All actions post to board and log events

**Tests:** `tests/unit/test_coordinator.py` (with mock LLM client)
- Decompose goal produces valid task list
- Task completion triggers progress check
- Failed task follows escalation ladder
- Stalled progress triggers replan
- Team proposal posted to board
- Completion assessment evaluates criteria
- Two-ledger state maintained correctly

**Estimated: ~400 lines code, ~250 lines tests**

---

### Task 3B.3 — Wire Coordinator into Runtime

**Modify:** `agentos/workspace/runtime.py`

Extend the basic runtime to:
- Create and manage the coordinator agent on workspace start
- Route events to coordinator: task completions, failures, timeouts, messages
- Implement the coordinator activation cycle (event-driven, not polling)
- Handle coordinator's outputs: new tasks, team proposals, completion recommendations

```python
# In WorkspaceRuntime:
def _on_task_completed(self, task_id): ...  # → coordinator.handle_task_completed
def _on_task_failed(self, task_id, error): ...  # → coordinator.handle_task_failed
def _on_message_for_coordinator(self, msg): ...  # → coordinator.handle_message
def _check_progress_cycle(self): ...  # → coordinator.check_progress (periodic)
```

**Tests:** `tests/integration/test_workspace_coordinator.py`
- Workspace starts → coordinator decomposes goal → tasks appear on backlog
- Task completes → coordinator checks progress → unblocks next tasks
- Task fails → coordinator follows escalation ladder
- Human sends directive → coordinator replans
- All events logged

**Estimated: ~150 lines code, ~150 lines tests**

---

### Task 3B.4 — Dynamic Team Mode

**Modify:** `agentos/workspace/runtime.py` + `coordinator.py`

Implement team evolution:
- Coordinator can propose spawning new agents (post proposal to board)
- In `suggest` mode: proposal waits for human approval via board resolve
- In `auto_full` mode: coordinator spawns immediately
- Coordinator can propose retiring idle agents
- Lock/unlock team mode via CLI

```python
# In WorkspaceRuntime:
def spawn_worker(self, participant: WorkspaceParticipant) -> None: ...
def retire_worker(self, participant_id: str) -> None: ...
def lock_team(self) -> None: ...
def unlock_team(self, mode: TeamMode) -> None: ...
```

**Tests:** `tests/unit/test_team_evolution.py`
- Suggest mode: proposal posted, not executed until approved
- Auto_full mode: proposal posted and executed
- Locked mode: spawn proposals rejected
- Retire removes agent from roster but preserves outputs
- Lock/unlock toggles

**Estimated: ~120 lines code, ~100 lines tests**

---

### Phase 3B Checkpoint

At this point you can:
- Create a workspace with a goal → coordinator decomposes into tasks automatically
- Coordinator monitors progress, replans when stalled
- Failed tasks follow the escalation ladder
- Dynamic teams: coordinator proposes adding agents, human approves
- Lock team when structure is stable

**Estimated total for Phase 3B: ~870 lines code, ~580 lines tests**

---

## Phase 3C: Context & Lifecycle

Goal: Agents get warm context on activation, progressive delivery reduces token waste, assistants can be spawned.

---

### Task 3C.1 — Agent Context Summaries

**File:** `agentos/workspace/context_summary.py`

```python
class ContextSummaryManager:
    """Maintains per-agent and workspace-level structured summaries."""

    def __init__(self, event_log, seq, workflow_id): ...

    # Agent summaries
    def get_agent_summary(self, agent_id) -> AgentContextSummary | None: ...
    def update_agent_summary(self, agent_id, task_output: TaskOutput) -> None: ...

    # Workspace summary
    def get_workspace_summary(self) -> WorkspaceContextSummary: ...
    def update_workspace_summary(self, backlog: BacklogManager,
                                  board: BoardManager) -> None: ...
```

Key behaviors:
- `update_agent_summary` — incremental merge. Takes existing summary + new task output → produces updated summary. Never regenerates from scratch.
- Summaries stored as JSON files in workspace (`.agentos/summaries/{agent_id}.json`)
- Target: under 2,000 tokens per summary
- Workspace summary updated after every task completion

**Tests:** `tests/unit/test_context_summary.py`
- Create summary from first task output
- Incremental merge preserves prior fields
- Summary stays under 2K tokens with many updates
- Workspace summary reflects current state
- Serialization round-trip

**Estimated: ~180 lines code, ~120 lines tests**

---

### Task 3C.2 — Progressive Context Delivery

**Modify:** `agentos/comms/ambient_context.py` + new `agentos/workspace/context_delivery.py`

```python
class ProgressiveContextDelivery:
    """Tracks what each agent has seen, injects only changes."""

    def __init__(self, board: BoardManager, summary_mgr: ContextSummaryManager,
                 bus: MessageBus): ...

    # Track delivery state per agent
    def mark_delivered(self, agent_id, board_version, summary_version): ...

    # Build activation context
    def build_activation_context(self, agent_id, task: BacklogTask,
                                  predecessors: list[TaskOutput]) -> ActivationContext: ...

    # Build mid-task injection (for Tier 1 tool boundaries)
    def build_injection(self, agent_id) -> str | None: ...
```

Key behaviors:
- Tracks `last_seen_board_version` and `last_seen_summary_version` per agent
- `build_activation_context` assembles full context on first activation, differential on subsequent
- `build_injection` returns None if nothing changed (same as current AmbientContextInjector but with summary tracking)
- Context budget: warn if assembled context exceeds 50% of model's context window

**Tests:** `tests/unit/test_context_delivery.py`
- First activation gets full context
- Second activation gets only changes
- Nothing changed → returns None
- Context budget warning at >50%
- Staleness: 24-hour summaries trigger full refresh

**Estimated: ~150 lines code, ~100 lines tests**

---

### Task 3C.3 — Assistant Spawner

**File:** `agentos/workspace/assistant.py`

```python
class AssistantSpawner:
    """Spawns ephemeral assistant agents for workers."""

    def __init__(self, event_log, seq, workflow_id, budget_manager): ...

    async def spawn(self, worker_id: str, task_description: str,
                     tools: list[str] | None = None,
                     model: str | None = None,
                     budget: BudgetSpec | None = None,
                     workspace: Path = None) -> TaskOutput: ...

    def should_spawn(self, estimated_tokens: int) -> bool: ...
```

Key behaviors:
- `spawn` — creates a Tier 1 agent with scoped context (task description only, no board/team awareness)
- Budget deducted from the worker's allocation
- Nesting depth = 1 (assistants cannot call `spawn`)
- `should_spawn` — heuristic: only spawn if >5K estimated tokens and benefits from isolation
- Logs `ASSISTANT_SPAWNED` and `ASSISTANT_COMPLETED` events
- Tracks assistant count per worker per task

Add MCP tool to `agentos/comms/mcp_server.py`:
```python
@mcp.tool()
def spawn_assistant(task: str, tools: str = "Read,Write,Grep",
                     model: str = "sonnet") -> str: ...
```

Add CLI command:
```
agentos assistant spawn "description" [--tools Read,Grep] [--model haiku]
```

**Tests:** `tests/unit/test_assistant_spawner.py`
- Spawn produces TaskOutput
- Budget deducted from worker allocation
- Nesting prevented (assistant can't spawn)
- `should_spawn` returns False for <5K token tasks
- Events logged

**Estimated: ~150 lines code, ~100 lines tests**

---

### Task 3C.4 — Agent Lifecycle Manager

**File:** `agentos/workspace/lifecycle.py`

Manages dormant/active/suspended states for workspace agents.

```python
class AgentLifecycleManager:
    """Manages agent states within a workspace."""

    def __init__(self, event_log, seq, workflow_id): ...

    def activate(self, agent_id, task_id, context: ActivationContext) -> None: ...
    def deactivate(self, agent_id) -> None: ...
    def suspend(self, agent_id, reason) -> None: ...
    def resume(self, agent_id) -> None: ...

    def get_state(self, agent_id) -> str: ...  # dormant, active, suspended
    def get_active_agents(self) -> list[str]: ...
    def get_dormant_agents(self) -> list[str]: ...

    # 35-minute rule
    def check_duration(self, agent_id) -> bool: ...  # True if exceeded
    def get_activation_duration(self, agent_id) -> float: ...  # seconds
```

Key behaviors:
- Tracks activation timestamps for 35-minute rule
- `check_duration` emits warning event if exceeded but doesn't kill agent
- State transitions logged as events
- Thread-safe

**Tests:** `tests/unit/test_agent_lifecycle.py`
- Activate/deactivate cycle
- Suspend/resume
- Duration tracking
- 35-minute warning
- Concurrent state changes

**Estimated: ~120 lines code, ~80 lines tests**

---

### Phase 3C Checkpoint

At this point:
- Agents get warm context (structured summaries) on activation
- Progressive delivery reduces token waste (~50%)
- Workers can spawn assistants (depth-1, budget-scoped)
- Agent lifecycle is managed (dormant/active/suspended)
- 35-minute warnings fire

**Estimated total for Phase 3C: ~600 lines code, ~400 lines tests**

---

## Phase 3D: Completion, Cost, and Polish

Goal: The workspace can detect when work is done, track costs meaningfully, persist across sessions, and be created conversationally.

---

### Task 3D.1 — Completion Detector

**File:** `agentos/workspace/completion.py`

```python
class CompletionDetector:
    """Layered completion detection for workspaces."""

    def __init__(self, config: WorkspaceConfig, backlog: BacklogManager,
                 budget_manager, coordinator: CoordinatorAgent | None): ...

    def check(self) -> CompletionResult: ...

class CompletionResult(BaseModel):
    complete: bool
    reason: str                          # "goal_satisfied", "budget_exhausted", "human_approved", etc.
    layer: int                           # Which layer triggered (1-4)
    details: dict = {}                   # Layer-specific info
    recommendation: str = ""             # What the coordinator suggests
```

Layers checked in order:
1. Hard limits (budget, max tasks, loop guards)
2. Goal satisfaction (acceptance criteria + all tasks done + coordinator assessment)
3. Human judgment (only if layer 2 passes — surfaces recommendation)
4. Scope management (flags creep if layer 2 fails because of new tasks)

**Tests:** `tests/unit/test_completion.py`
- Budget exhausted triggers layer 1
- All tasks done + criteria met → layer 2 satisfied
- Partial completion → recommendation to continue
- Scope creep detection

**Estimated: ~130 lines code, ~100 lines tests**

---

### Task 3D.2 — Cost Tracker

**File:** `agentos/workspace/cost_tracker.py`

```python
class CostTracker:
    """Tracks workspace costs and provides optimization insights."""

    def __init__(self, budget: BudgetSpec): ...

    def record(self, agent_id: str, task_id: str, delta: BudgetDelta): ...
    def get_total(self) -> BudgetUsage: ...
    def get_per_agent(self, agent_id) -> BudgetUsage: ...
    def get_per_task(self, task_id) -> BudgetUsage: ...

    # Budget hierarchy
    def allocate_for_task(self, task_id, budget: BudgetSpec) -> None: ...
    def get_remaining_for_task(self, task_id) -> BudgetSpec: ...
    def get_reserve(self) -> float: ...  # Unallocated budget (USD)

    # Cost-of-pass
    def cost_of_pass(self, task_id) -> float | None: ...  # cost / success_rate

    # Model routing suggestion
    def suggest_model_tier(self, estimated_complexity: str) -> str: ...
```

**Tests:** `tests/unit/test_cost_tracker.py`
- Record costs, get totals
- Per-agent and per-task breakdown
- Budget allocation and remaining
- Reserve calculation (30% default)
- Cost-of-pass computation
- Model tier suggestion based on complexity

**Estimated: ~120 lines code, ~80 lines tests**

---

### Task 3D.3 — Workspace Persistence

**File:** `agentos/workspace/persistence.py`

Save and restore workspace state across sessions.

```python
def save_workspace(runtime: WorkspaceRuntime, path: Path) -> None: ...
def load_workspace(path: Path, event_log) -> WorkspaceRuntime: ...
```

Persisted state:
- WorkspaceConfig (the original config)
- Backlog state (all tasks with current status)
- Agent context summaries
- Workspace context summary
- Board state snapshot
- Progressive delivery watermarks
- Cost tracker state

Format: directory with JSON files:
```
.agentos-workspace/
├── config.json              # WorkspaceConfig
├── backlog.json             # All BacklogTasks
├── summaries/               # Per-agent context summaries
│   ├── research-agent.json
│   └── analyst.json
├── workspace_summary.json   # WorkspaceContextSummary
├── board_snapshot.json      # BoardState
├── delivery_state.json      # Progressive delivery watermarks
└── cost_state.json          # CostTracker state
```

**Tests:** `tests/unit/test_workspace_persistence.py`
- Save and load round-trip
- Resume from persisted state
- Missing files handled gracefully
- Corrupted files produce clear errors

**Estimated: ~150 lines code, ~100 lines tests**

---

### Task 3D.4 — Conversational Workspace Builder

**File:** `agentos/workspace/builder.py`

Uses an LLM to convert natural language project description into WorkspaceConfig.

```python
class WorkspaceBuilder:
    """Conversational workspace creation."""

    def __init__(self, client: Anthropic): ...

    async def build_from_description(self, description: str,
                                      human_name: str = "human") -> WorkspaceConfig: ...
```

The builder:
1. Takes a natural language description
2. Uses a single LLM call to generate a WorkspaceConfig JSON
3. Presents the config to the human for approval/editing
4. Returns the final WorkspaceConfig

Prompt includes:
- Available adapter types and model tiers
- Budget guidelines
- Team mode options
- Example configs

**CLI integration:**
```
agentos workspace create --interactive
> Describe your project: "Managing my personal investments"
> [Builder proposes config]
> Approve? (yes/edit) ...
```

**Tests:** `tests/unit/test_workspace_builder.py` (mock LLM)
- Natural language produces valid WorkspaceConfig
- Config includes all required fields
- Budget and team mode are sensible defaults

**Estimated: ~120 lines code, ~60 lines tests**

---

### Task 3D.5 — Integration Tests with Real Agents

**File:** `tests/e2e/test_workspace_live.py`

End-to-end test: create a workspace with a goal, let the coordinator decompose, agents execute, human reviews.

```python
class TestWorkspaceLiveE2E:
    def test_full_workspace_flow(self, tmp_path):
        # 1. Create workspace from YAML
        # 2. Coordinator decomposes goal into tasks
        # 3. AI workers claim and execute tasks (real Claude Code)
        # 4. Coordinator monitors, unblocks, checks completion
        # 5. Human reviews and approves
        # 6. Verify: board state, event log, artifacts, cost tracker
```

**Also:** `tests/integration/test_workspace_full.py` (mock agents, tests the full runtime flow without API calls)

**Estimated: ~200 lines tests**

---

### Phase 3D Checkpoint

At this point:
- Workspace detects when work is complete (layered)
- Costs are tracked per-agent, per-task, with cost-of-pass metrics
- Workspaces persist across sessions
- Non-technical users can create workspaces conversationally
- Full e2e flow tested with real agents

**Estimated total for Phase 3D: ~520 lines code, ~540 lines tests**

---

## Summary

| Phase | Code | Tests | Key Deliverable |
|---|---|---|---|
| **3A: Foundation** | ~1,010 | ~800 | Workspace + backlog + CLI |
| **3B: Coordinator** | ~870 | ~580 | AI coordinator with two-ledger, escalation, dynamic teams |
| **3C: Context & Lifecycle** | ~600 | ~400 | Warm context, progressive delivery, assistants |
| **3D: Completion & Polish** | ~520 | ~540 | Completion detection, cost tracking, persistence, conversational builder |
| **Total** | **~3,000** | **~2,320** | |

### New files (estimated 17):
```
agentos/workspace/__init__.py
agentos/workspace/schemas.py
agentos/workspace/loader.py
agentos/workspace/backlog.py
agentos/workspace/runtime.py
agentos/workspace/coordinator_prompts.py
agentos/workspace/coordinator.py
agentos/workspace/context_summary.py
agentos/workspace/context_delivery.py
agentos/workspace/assistant.py
agentos/workspace/lifecycle.py
agentos/workspace/completion.py
agentos/workspace/cost_tracker.py
agentos/workspace/persistence.py
agentos/workspace/builder.py
agentos/cli/workspace_cli.py
```

### Modified files (estimated 4):
```
agentos/schemas/events.py              # Workspace + backlog event types
agentos/cli/main.py                    # Register workspace CLI group
agentos/comms/mcp_server.py            # Add spawn_assistant tool
pyproject.toml                         # If new dependencies needed
```

### Test files (estimated 14):
```
tests/unit/test_workspace_schemas.py
tests/unit/test_workspace_loader.py
tests/unit/test_backlog_manager.py
tests/unit/test_workspace_runtime.py
tests/unit/test_coordinator_prompts.py
tests/unit/test_coordinator.py
tests/unit/test_team_evolution.py
tests/unit/test_context_summary.py
tests/unit/test_context_delivery.py
tests/unit/test_assistant_spawner.py
tests/unit/test_agent_lifecycle.py
tests/unit/test_completion.py
tests/unit/test_cost_tracker.py
tests/unit/test_workspace_persistence.py
tests/unit/test_workspace_builder.py
tests/unit/test_cli_workspace.py
tests/integration/test_workspace_basic.py
tests/integration/test_workspace_coordinator.py
tests/integration/test_workspace_full.py
tests/e2e/test_workspace_live.py
```

### Dependency graph:
```
3A.1 (schemas) ──┐
3A.2 (loader)  ──┤
                  ├── 3A.3 (backlog) ──┐
                  │                     ├── 3A.4 (runtime) ── 3A.5 (CLI)
                  │                     │         │
                  │                     │    ┌────┘
                  │                     │    │
                  ├── 3B.1 (prompts) ──┤    │
                  │                     ├── 3B.2 (coordinator) ── 3B.3 (wire into runtime)
                  │                     │         │
                  │                     │         └── 3B.4 (dynamic teams)
                  │                     │
                  ├── 3C.1 (summaries) ┤
                  ├── 3C.2 (delivery)  ├── 3C.4 (lifecycle)
                  └── 3C.3 (assistant) ┘
                                            │
                                       3D.1 (completion)
                                       3D.2 (cost tracker)
                                       3D.3 (persistence)
                                       3D.4 (conversational builder)
                                       3D.5 (integration tests)
```

Tasks within each phase can be partially parallelized:
- **3A:** 3A.1 + 3A.2 parallel → 3A.3 → 3A.4 → 3A.5
- **3B:** 3B.1 parallel with 3A → 3B.2 → 3B.3 → 3B.4
- **3C:** 3C.1 + 3C.2 + 3C.3 all parallel → 3C.4
- **3D:** 3D.1 + 3D.2 + 3D.3 all parallel → 3D.4 → 3D.5
