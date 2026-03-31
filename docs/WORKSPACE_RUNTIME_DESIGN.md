# AgentOS — Workspace Runtime Design

**Companion to:** WORKSPACE_VISION.md | COMMS_RESEARCH_AND_PLAN.md | COMMS_PHASE2_PLAN.md
**Date:** March 2026
**Status:** Design — ready for review, not yet implemented
**Branch:** `feature/agent-comunitaion`

---

## 1. Overview

The workspace runtime replaces the static DAG executor with a collaborative environment where humans and AI agents work together as a team. Instead of "define a workflow, run it," the model is "describe a goal, assemble a team, work together until done."

**What changes:**
- DAG → living task backlog (kanban-style)
- Pre-defined workflow → coordinator decomposes goals dynamically
- Task assignment → workers claim from backlog
- Isolated agent execution → shared board + messaging
- Human as approver → human as team member

**What stays:**
- Event-sourced state (all actions are events)
- Budget enforcement (hierarchical: workspace → task → assistant)
- Capability-based security (per-agent scoping)
- Structured output protocol (manifests for handoffs)
- Full audit trail

---

## 2. Workspace Configuration

A workspace is defined by a goal, a team, and governance rules. It can be configured via YAML (technical users) or built conversationally (non-technical users). Both produce the same `WorkspaceConfig`.

### 2.1 Schema

```python
class TeamMode(StrEnum):
    LOCKED = "locked"          # Fixed team, no changes allowed
    SUGGEST = "suggest"        # Coordinator proposes, human approves every change
    AUTO_MINOR = "auto_minor"  # Coordinator can reassign tasks freely; team changes need approval
    AUTO_FULL = "auto_full"    # Coordinator can spawn/retire agents; posts to board but doesn't wait

class ParticipantType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"

class ParticipantRole(StrEnum):
    LEAD = "lead"              # Defines goals, final authority, can override anything
    WORKER = "worker"          # Claims and executes tasks
    REVIEWER = "reviewer"      # Evaluates output, approves/rejects
    OBSERVER = "observer"      # Monitors only, receives board updates

class WorkspaceParticipant(BaseModel):
    name: str
    type: ParticipantType
    roles: list[ParticipantRole]
    specialization: str = ""             # Natural language description of expertise
    adapter: str | None = None           # For agents: tier1, tier2_claude_code, etc.
    model: str | None = None             # Model override
    tools: list[str] | None = None       # Tool allowlist
    budget: BudgetSpec | None = None     # Per-participant budget override

class CoordinatorConfig(BaseModel):
    enabled: bool = True
    type: ParticipantType = ParticipantType.AGENT  # Can be "human" if a person coordinates
    model: str = "opus"                  # Strong model for planning/reasoning
    authority: TeamMode = TeamMode.SUGGEST
    auto_decompose: bool = True          # Automatically decompose goals into tasks
    replan_interval: int = 0             # Minutes between replanning checks (0 = after each task)

class WorkspaceConfig(BaseModel):
    name: str
    goal: str                            # Natural language project goal
    description: str = ""                # Extended context for the coordinator
    team_mode: TeamMode = TeamMode.SUGGEST
    budget: BudgetSpec = BudgetSpec()    # Workspace-level budget
    coordinator: CoordinatorConfig = CoordinatorConfig()
    team: list[WorkspaceParticipant] = []
    acceptance_criteria: list[str] = []  # How to know the goal is achieved
    documents: list[str] = []            # Paths to initial documents/data
    persist: bool = True                 # Save workspace state across sessions
```

### 2.2 YAML Example

```yaml
workspace:
  name: "Personal Investment Management"
  goal: "Manage and optimize my personal investment portfolio"
  description: |
    Analyze my current holdings, research market conditions,
    identify risks and opportunities, and produce actionable
    investment recommendations.

  team_mode: dynamic  # alias for "suggest"

  budget:
    cost_usd: 50.00
    tokens: 5_000_000

  coordinator:
    model: opus
    authority: suggest
    auto_decompose: true

  team:
    - name: lucas
      type: human
      roles: [lead, reviewer]

    - name: portfolio-analyst
      type: agent
      roles: [worker]
      specialization: "Portfolio analysis, risk assessment, holdings reports"
      adapter: tier2_claude_code

    - name: market-researcher
      type: agent
      roles: [worker]
      specialization: "Market research, monetary policy, opportunity identification"
      adapter: tier1

  acceptance_criteria:
    - "Portfolio analysis report produced with risk assessment"
    - "Market research findings with actionable recommendations"
    - "Human lead has reviewed and approved final output"

  documents:
    - "./portfolio/holdings.csv"
    - "./portfolio/transactions_2025.csv"
```

### 2.3 Conversational Creation

The CLI/dashboard guides non-technical users to produce the same config:

```
$ agentos workspace create

What's your project?
> Managing my personal investment portfolio

What do you need help with?
> Analyzing my holdings, researching markets, finding opportunities

I suggest starting with:
  • Portfolio Analyst — reads your documents, generates reports
  • Market Researcher — tracks conditions, finds opportunities
  • Me as coordinator — I'll manage the workflow and board

Team mode: dynamic (I can suggest adding agents as we learn more)

Does this look right? (yes/edit/add more)
> yes

Upload any documents? (paths or drag files)
> ./portfolio/holdings.csv, ./portfolio/transactions_2025.csv

Starting workspace "Personal Investment Management"...
Board created. Coordinator is decomposing your goal into tasks.
```

The conversation produces a `WorkspaceConfig` identical to the YAML above. The config can be exported at any time:
```
$ agentos workspace export > my_investment_workspace.yaml
```

---

## 3. The Three Agent Roles

### 3.1 Coordinator

One per workspace. Responsible for planning and team management, not task execution.

**Responsibilities:**
- Decompose the goal into tasks (initial planning)
- Post tasks to the board as a backlog
- Suggest task assignments based on capability matching
- Monitor progress, detect blockers, identify gaps
- Replan when new information emerges
- Propose team changes (spawn/retire agents) in dynamic mode
- Escalate to the human lead when decisions exceed its authority
- Report status continuously via the board

**What it sees:** Full workspace context — board state, all messages, all task outputs, team roster, budget consumption.

**What it can't do:**
- Execute domain work (it doesn't research, code, or analyze — it coordinates)
- Override the human lead
- Spawn agents without appropriate authority (governed by team_mode)
- Exceed the workspace budget

**Implementation:** A Tier 1 agent (API-controlled) running a specialized prompt that focuses on coordination, not domain work. Uses the board and messaging system for all communication. Has access to the backlog management tools. **Must use a frontier model (Opus-tier)** — research shows token usage on planning correlates directly with quality, and multi-agent Opus coordinator + Sonnet workers outperforms single-agent Opus by 90.2%.

**Lifecycle:** Persistent within a workspace session. Activated when the workspace starts, runs when events need processing (task completions, messages, timeouts), dormant otherwise.

**Two-Ledger Pattern (from Microsoft Magentic-One):**

The coordinator maintains two separate internal documents, both reflected on the board:

- **Task Ledger**: Facts about the project, educated guesses (structured speculation), and the current plan. Educated guesses give the coordinator space to hypothesize without poisoning downstream agents — they're clearly marked as unverified. Posted to the board's Announcements section.
- **Progress Ledger**: What's been assigned, what's completed, what's stalled, what's blocked. Updated after every event cycle. Posted to the board's In Progress section.

**Replan trigger:** If the Progress Ledger shows no forward progress for 2+ consecutive cycles, the coordinator rewrites both ledgers and replans. This prevents both premature replanning (expensive) and stuck-forever states.

### 3.2 Worker

Claims tasks and does the actual work. Can be human or AI agent.

**Responsibilities:**
- Claim tasks from the backlog
- Execute the work within their capability scope
- Communicate via board (share findings, ask questions)
- Communicate via direct messages (coordinate with specific teammates)
- Produce structured output (manifest) for each completed task
- Can spawn assistants for sub-tasks

**What they see:** Board state (ambient awareness), their inbox, their current task definition, relevant predecessor outputs.

**What they can't see:** Other workers' private assistant conversations, other workers' draft artifacts (unless shared on the board).

**AI Worker implementation:** Tier 1 or Tier 2 agent with the comms MCP tools. Activated when claiming a task, dormant between tasks. Context injected at activation: structured summary of prior work + board state + task definition.

**Human Worker implementation:** Uses the CLI, dashboard, or their own tools. Sees the board and messages through the UI. Claims tasks via `agentos task claim <id>` or dashboard. Posts to board and sends messages via the same interfaces. Can spawn AI assistants via `agentos assistant spawn "help me with X"`.

### 3.3 Assistant

Private helper for a specific worker. Ephemeral, task-scoped, invisible to the team.

**Responsibilities:**
- Help the worker with a sub-task (research, computation, drafting, fact-checking)
- Return results to the worker
- Shut down when the sub-task is done

**What it sees:** Only what the worker provides — the sub-task description, relevant files, scoped workspace access. No board, no team messages, no other tasks.

**What it can't do:**
- Post to the board
- Send messages to other team members
- Claim tasks from the backlog
- Exceed the worker's task budget

**Implementation:** A lightweight Tier 1 or Tier 2 agent spawned by the worker. Runs in a scoped sub-workspace. Budget deducted from the worker's task allocation. Tracked in the event log but not visible on the board. **Nesting depth limited to 1** — assistants cannot spawn other assistants. Both Claude Code and OpenAI Codex enforce this same limit in production.

**Spawn decision heuristic (from production research):**
Each sub-agent spawn carries ~2-3K tokens of overhead (session init, context assembly). Only spawn when:
1. **Isolation benefit** — the sub-task is risky, messy, or state-heavy (file mutations, config changes)
2. **Model specialization** — the sub-task benefits from a different model tier (Haiku for data extraction, Opus for synthesis)
3. **Token savings** — the sub-task would consume >5K tokens inline and can run in a fresh, smaller context

**Don't spawn when:**
- Sub-task takes <30 seconds or <2K tokens
- Sub-task is read-only with no side effects
- Sub-task requires the worker's current reasoning context
- Budget is tight — every spawn costs ~$0.01-0.03 in overhead

**Spawning:**
- AI worker spawns via MCP tool: `spawn_assistant(task="Summarize this PDF", tools="Read,Grep")`
- Human worker spawns via CLI: `agentos assistant spawn "Calculate GDP growth rates from data.csv"`

### 3.4 Role Comparison

| Property | Coordinator | Worker (AI) | Worker (Human) | Assistant |
|---|---|---|---|---|
| Visible on board | Yes (manages it) | Yes | Yes | No |
| Can message team | Yes | Yes | Yes | No |
| Claims tasks | No | Yes | Yes | No |
| Creates tasks | Yes (decomposes) | Can propose | Can create | No |
| Spawns assistants | No | Yes | Yes | No |
| Spawns workers | Yes (in dynamic mode) | No | No | No |
| Budget scope | Workspace-level | Task-level | Task-level | Sub-task from worker |
| Lifecycle | Persistent | Hybrid (per-task) | Continuous | Ephemeral |
| Context | Full workspace | Board + task + summaries | Full (dashboard) | Task-scoped only |
| Can be timed out | Yes (but replans) | Yes (reassigned) | Never | Yes |
| Can be overridden | By human lead | By coordinator/human | By human lead only | By its worker |

---

## 4. The Backlog (Replacing the DAG)

### 4.1 Task Model

Tasks live on the board as a backlog. They flow through statuses:

```
OPEN → CLAIMED → IN_PROGRESS → IN_REVIEW → DONE
                                    ↓
                              REVISION_NEEDED → IN_PROGRESS

OPEN → BLOCKED (waiting on dependency or input)
       BLOCKED → OPEN (dependency resolved)

Any state → CANCELLED (by coordinator or human)
```

```python
class BacklogTask(BaseModel):
    task_id: str
    title: str                              # Short description
    description: str                        # Full task description
    created_by: str                         # Coordinator, human, or agent who created it

    # Assignment
    assigned_to: str | None = None          # Who claimed it
    suggested_for: str | None = None        # Coordinator's suggestion
    required_role: str | None = None        # e.g., "researcher", "analyst"

    # Status
    status: TaskStatus                      # OPEN, CLAIMED, IN_PROGRESS, etc.

    # Dependencies
    depends_on: list[str] = []              # Task IDs that must complete first
    blocks: list[str] = []                  # Task IDs waiting on this

    # Acceptance
    acceptance_criteria: list[str] = []     # How to verify this task is done

    # Output
    output: TaskOutput | None = None        # Structured output when complete

    # Governance
    budget: BudgetSpec | None = None        # Per-task budget
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    computed_priority: float | None = None  # Dynamic priority from graph structure
    estimated_minutes: int | None = None    # For 35-min decomposition rule
    model_tier: Literal["haiku", "sonnet", "opus"] | None = None  # Coordinator's model recommendation

    # Chaining (lightweight alternative to full dependencies)
    next_task: dict | None = None           # Auto-create this task on completion

    # Tracking
    created_at: str
    claimed_at: str | None = None
    completed_at: str | None = None
    review_count: int = 0
    stall_count: int = 0                    # Consecutive cycles without progress
```

### 4.2 Backlog Manager

```python
class BacklogManager:
    """Manages the task backlog for a workspace.

    Tasks are created by the coordinator (via decomposition) or by
    participants (via proposals). Workers claim tasks. The coordinator
    monitors completion and handles reassignment.
    """

    # Task lifecycle
    def create_task(self, task: BacklogTask) -> str: ...
    def claim_task(self, task_id: str, participant_id: str) -> None: ...
    def start_task(self, task_id: str) -> None: ...
    def submit_for_review(self, task_id: str, output: TaskOutput) -> None: ...
    def approve_task(self, task_id: str, reviewer_id: str) -> None: ...
    def request_revision(self, task_id: str, feedback: str) -> None: ...
    def cancel_task(self, task_id: str, reason: str) -> None: ...

    # Querying
    def get_open_tasks(self, role: str = None) -> list[BacklogTask]: ...
    def get_tasks_for(self, participant_id: str) -> list[BacklogTask]: ...
    def get_blocked_tasks(self) -> list[BacklogTask]: ...
    def get_task(self, task_id: str) -> BacklogTask: ...

    # Dependencies
    def check_dependencies(self, task_id: str) -> bool: ...  # True if all deps met
    def unblock(self, task_id: str) -> list[str]: ...  # Returns newly unblocked tasks

    # Decomposition
    def decompose_task(self, task_id: str, sub_tasks: list[BacklogTask]) -> None: ...

    # Chaining
    def chain_next(self, task_id: str) -> str | None: ...  # Auto-create next_task on completion

    # Priority
    def recompute_priorities(self) -> None: ...  # Dynamic priority from dependency structure

    # Health
    def flag_long_tasks(self) -> list[str]: ...  # Tasks estimated > 35 min
    def flag_stalled_tasks(self, max_stall_cycles: int = 2) -> list[str]: ...  # Stuck tasks
```

### 4.3 How the Backlog Differs from a DAG

| DAG | Backlog |
|---|---|
| All tasks defined before execution | Tasks created during execution |
| Rigid dependencies | Flexible dependencies (can be added/removed) |
| Tasks assigned to specific agents | Tasks claimed by available workers |
| Linear execution path | Parallel, opportunistic execution |
| Completes when all nodes finish | Completes when goal is satisfied |
| No new tasks after start | New tasks can be proposed anytime |
| One execution run | Persistent across sessions |

The backlog still supports dependencies (task B needs task A's output), but they're constraints, not a rigid graph. The coordinator manages ordering, not a topological sort.

### 4.4 Dynamic Priority Computation

Instead of relying solely on manual priority assignment, the system computes priority from the dependency structure (inspired by DynTaskMAS):

```
computed_priority(task) = task_complexity / max(dependency_weight + downstream_priority)
```

Tasks that block the most downstream work get higher priority automatically. This means a research task that three analysis tasks depend on will surface to the top of the backlog without manual intervention. The coordinator can still override with manual priority for urgent human-directed work.

### 4.5 Task Chaining

For simple sequential workflows that don't need full dependency tracking, tasks support a `next_task` field. When a task completes, the system auto-creates the follow-up:

```python
# Example: research → analysis chain
research_task = BacklogTask(
    title="Research ECB policy",
    next_task={
        "title": "Analyze ECB impact on portfolio",
        "description": "Using the research findings, analyze impact...",
        "suggested_for": "portfolio-analyst",
    },
)
# When research completes, the analysis task is auto-created in the backlog
```

This is a lightweight alternative for predictable sequences. Complex workflows with parallel branches and convergence use the full dependency model.

---

## 5. Coordinator Behavior

### 5.1 Bootstrap: Goal Decomposition

When a workspace starts, the coordinator:
1. Reads the goal, description, acceptance criteria, and uploaded documents
2. Reviews the team roster and capabilities
3. Decomposes the goal into an initial set of tasks
4. Posts tasks to the backlog on the board
5. Suggests assignments based on capability matching
6. Announces the plan on the board

This is a single LLM call with a structured prompt. The coordinator must produce **explicit, non-overlapping task specifications** — research shows that vague instructions like "research topic X" cause workers to duplicate work. Each task needs: an objective, an output format, guidance on tools/sources, and clear boundaries.

```
You are a project coordinator. Given this goal, team, and context,
decompose the work into concrete tasks.

Goal: {goal}
Description: {description}
Acceptance criteria: {acceptance_criteria}
Documents available: {document_summaries}

Team:
{for each participant: name, type, roles, specialization}

For each task, provide:
- Title and description (specific and non-overlapping with other tasks)
- Required output format (report, data file, analysis, code, etc.)
- Which team member it's best suited for (and why)
- What this task needs before it can start (inputs from other tasks or humans)
- Acceptance criteria (how to verify this task is done)
- Estimated effort (minutes) — flag anything over 35 minutes for decomposition
- Priority

Also identify:
- What should be done first (critical path)
- What can be done in parallel
- Where human input will be needed
```

**Resource allocation heuristics (from Anthropic's multi-agent research):**
- Simple fact-finding: 1 worker, ~3-10 tool calls
- Direct comparisons: 2-4 workers in parallel, ~10-15 calls each
- Complex research/analysis: 5+ workers with clearly divided responsibilities

**Model routing for cost optimization:**
The coordinator should recommend model tiers per task. Default distribution targeting ~80% cost reduction:
- Simple/routine tasks (data formatting, file organization): Haiku (~60% of tasks)
- Moderate tasks (research, analysis, drafting): Sonnet (~25% of tasks)
- Complex tasks (synthesis, judgment, strategy): Opus (~15% of tasks)

This is a recommendation, not enforcement — the system respects the agent's configured model but the coordinator can suggest overrides for cost efficiency.

### 5.2 Ongoing: Monitoring and Replanning

After bootstrap, the coordinator activates when:
- A task is completed (check: what's unblocked? Is the goal closer to done?)
- A task fails (check: retry? reassign? decompose differently?)
- A message arrives for the coordinator (human directive, agent question)
- A timeout fires (agent hasn't made progress)
- A replan interval elapses (configurable)

On each activation, the coordinator:
1. Updates the Progress Ledger from current board/backlog state
2. Checks for stalled progress (2+ cycles without forward movement)
3. If stalled: rewrites both ledgers and replans
4. If progressing: checks for blockers, newly unblocked tasks, completion proximity
5. Posts updates, suggestions, or new tasks to the board

**Failure recovery escalation ladder:**
When a task fails or an agent is stuck, the coordinator follows this sequence:
1. **Retry** — same task, same agent (transient failure)
2. **Reassign** — same task, different agent (agent-specific problem)
3. **Replan** — same goal, different approach (approach was wrong)
4. **Decompose** — break the failing task into smaller pieces (task was too large)
5. **Escalate** — surface to human with context (coordinator can't resolve)

Each step is tried only once before moving to the next. The coordinator never retries the same approach more than once.

**Optimal team size:** Research shows coordination gains plateau beyond 4-5 agents. Below that, adding agents helps; above it, coordination overhead consumes the benefits. The coordinator should flag this when the team grows beyond 5 workers and suggest hierarchical sub-teams if the project demands more.

### 5.3 Team Evolution (Dynamic Mode)

When the coordinator identifies a capability gap:
1. Posts a proposal to the board: "I suggest adding a quant developer because..."
2. In `suggest` mode: waits for human approval
3. In `auto_minor` mode: waits for human approval (team change)
4. In `auto_full` mode: spawns the agent, posts notification to board
5. The new agent appears on the team roster and can claim tasks

When the coordinator identifies an unnecessary agent:
1. Posts: "The market-researcher has no remaining tasks. Suggest retiring."
2. Same approval flow based on team_mode
3. If approved, agent is removed from roster (but its outputs remain)

### 5.4 Scope Management

To prevent infinite expansion:
- New tasks must reference the original goal ("this task contributes to the goal because...")
- The coordinator tracks task count and flags if it's growing beyond the initial estimate
- Depth limit: tasks can be decomposed into sub-tasks, but sub-sub-tasks require human approval
- Replan budget: configurable max number of replanning cycles before the coordinator must ask the human for direction

---

## 6. Human Participation

### 6.1 Human Roles

A human can fill any combination of roles:

**Lead** — Defines the goal, has final authority, can override any decision. Every workspace has exactly one lead (always human).

**Worker** — Claims and executes tasks, just like an AI worker. Uses their own tools (IDE, spreadsheet, whatever). Reports completion via CLI/dashboard. Can spawn AI assistants.

**Reviewer** — Evaluates completed tasks. Can approve, request revision, or reject. The coordinator routes tasks to reviewers automatically (or the human claims review tasks).

**Observer** — Monitors the board and messages but doesn't do work. Useful for stakeholders who want visibility.

### 6.2 Human Interaction Points

| Action | CLI | Dashboard | Mobile (future) |
|---|---|---|---|
| See the board | `agentos board show` | Real-time panel | Push notifications |
| Post to board | `agentos board post "..."` | Text input | Quick reply |
| Claim a task | `agentos task claim <id>` | Click to claim | — |
| Complete a task | `agentos task complete <id>` | Submit button | — |
| Message an agent | `agentos message send <agent> "..."` | Chat panel | Quick message |
| Approve team change | `agentos board resolve <id>` | Approve button | Push + approve |
| Spawn assistant | `agentos assistant spawn "..."` | — | — |
| Lock/unlock team | `agentos workspace lock-team` | Toggle | — |
| Export config | `agentos workspace export` | Download button | — |

### 6.3 Human-AI Same-Task Collaboration

When a human and AI work on the same task:

**Lead-Support pattern:**
- One participant is "lead" (makes decisions, produces final output)
- One is "support" (drafts, researches, computes)
- They communicate via direct messages within the task context

**In practice:**
- Human claims "Write executive summary" as lead
- Human spawns an assistant: "Draft an executive summary based on the research findings on the board"
- Assistant produces draft
- Human edits, adds judgment, finalizes
- Human marks task complete

Or:
- AI worker claims "Analyze ECB policy" as lead
- AI spawns assistant for data computation
- Mid-task, AI posts question to board: "Need human input on risk tolerance assumptions"
- Human responds via message
- AI incorporates response, completes task

### 6.4 Rules for Human Workers

These are enforced by the system, not just conventions:

1. **Humans are never timed out.** An AI worker stuck for 30 minutes gets flagged. A human worker is never flagged — they work at their own pace.
2. **Humans are never forcibly reassigned.** The coordinator can suggest but never take a task away from a human.
3. **Human directives override everything.** A message with `speech_act: directive` from a human lead is the highest priority for any agent.
4. **Humans can claim any task**, even ones suggested for AI agents.
5. **Human work is not evaluated by AI.** Only other humans can review a human's work. AI can assist with review (fact-checking, consistency checking) but the verdict is always human.

---

## 7. Agent Lifecycle

### 7.1 States

```
DORMANT → ACTIVATING → ACTIVE → COMPLETING → DORMANT
                                     ↓
                               SUSPENDED (waiting on input/dependency)
                                     ↓
                               ACTIVATING → ACTIVE → ...
```

**DORMANT:** Agent has no running process. Its identity and context summary exist in the workspace state. It can be activated when needed.

**ACTIVATING:** Agent is being prepared — context injected, tools configured, comms state written. Transition to ACTIVE when ready.

**ACTIVE:** Agent is running (Tier 1 loop or Tier 2 subprocess). It has board awareness, can send/receive messages, and is working on a claimed task.

**COMPLETING:** Agent has finished its task. Output is being collected, outbox is being routed, status is being updated.

**SUSPENDED:** Agent is waiting for external input (human response, dependency completion). Process may or may not be running depending on implementation.

### 7.2 Context Injection on Activation

When an agent activates (transitions DORMANT → ACTIVE), it receives context assembled through **progressive delivery** — the system tracks what each agent has already seen and only injects new/changed information on subsequent activations. This achieves ~50% token reduction over naive full-context injection.

```python
class ActivationContext:
    # Identity
    agent_id: str
    role: str
    specialization: str

    # Current task
    task: BacklogTask
    predecessor_outputs: list[TaskOutput]  # From dependency tasks

    # Team awareness (from board — differential, only changes since last seen)
    board_state_compact: str               # ~200 tokens
    pending_messages: list[DirectMessage]

    # Accumulated knowledge (structured summary — anchored, incremental)
    agent_summary: AgentContextSummary | None     # This agent's prior work
    workspace_summary: WorkspaceContextSummary | None  # Project-level context

    # Tools and constraints
    allowed_tools: list[str]
    budget: BudgetSpec

    # Progressive delivery tracking
    last_seen_board_version: int | None = None
    last_seen_summary_version: int | None = None
```

**Context budget allocation** (research-backed targets):

| Component | % of Context | Notes |
|---|---|---|
| System instructions + identity | 10-15% | Agent role, specialization, workspace rules |
| Tool definitions | 10-15% | Pruned to relevant tools only (MCP tool search) |
| Agent summary + workspace summary | 15-20% | Anchored structured summaries, <2K tokens each |
| Task definition + predecessor outputs | 25-35% | The core work payload |
| Board state + messages | 10-15% | Differential — only changes since last activation |
| Working space for agent reasoning | 20-30% | Left free for the agent's tool calls and output |

**Target: under 50% context utilization before the agent starts working.** If over 60%, apply compression to summaries and prune older predecessor outputs.

**Staleness prevention:**
- All context items carry timestamps
- Agent system prompt instructs: "Prefer recent information. Flag conflicts between old and new data."
- Summaries older than 24 hours trigger a full refresh rather than incremental update
- Entity references (file paths, service names) are verified before injection — stale references are marked or removed

### 7.3 Structured Summaries (Warm Context)

Each agent maintains a structured summary that persists across activations. The format is based on **Factory AI's anchored iterative summarization** — proven across 36,000 production messages to outperform both OpenAI's and Anthropic's native compression on accuracy, completeness, and continuity.

The key principle: **structure forces preservation.** Dedicated sections act as a checklist — the summarizer cannot silently drop file paths or skip decisions. The summary is **never regenerated from scratch** — it is incrementally updated by merging new information into the existing structure, which resists information drift across compression cycles.

```python
class AgentContextSummary(BaseModel):
    """Anchored iterative summary — updated after each task, never regenerated."""
    agent_id: str

    # --- Factory's proven 4 core fields ---
    intent: str                             # What this agent is trying to accomplish (goal, not task)
    changes_made: list[str]                 # Concrete artifacts: files modified, outputs produced
    decisions: list[str]                    # Design choices, trade-offs, options rejected and why
    next_steps: list[str]                   # Pending work, blockers, what the next activation should do first

    # --- Extended fields ---
    confidence: list[str] = []              # What the agent is unsure about (flagged for human review)
    dependencies: dict[str, list[str]] = {} # {"consumed_from": [...], "produced_for": [...]}
    entity_references: list[str] = []       # Named files, services, people, PRs downstream tasks might need
    error_log: list[str] = []              # Failures encountered and their resolutions (or lack thereof)

    # --- Tracking ---
    tasks_completed: list[str] = []         # Task IDs
    last_active: str = ""
    summary_version: int = 0                # Increments on each update
```

Updated after each task completion via **incremental merge** — the system takes the existing summary + the task's output manifest and produces an updated summary. This costs ~500-800 tokens per update.

**Target size: under 2,000 tokens.** Research shows this is the sweet spot — enough to preserve critical context, small enough to leave working space in the context window.

The coordinator maintains a workspace-level summary using the same anchored pattern:

```python
class WorkspaceContextSummary(BaseModel):
    """Workspace-level summary maintained by the coordinator."""
    goal: str
    current_status: str                     # "Phase 2 of 3: analysis in progress"

    # --- Anchored fields ---
    intent: str                             # Current strategic direction
    key_decisions: list[str]                # Decisions made and rationale
    key_artifacts: list[str]                # Important outputs with paths
    open_questions: list[str]               # Unresolved issues

    # --- Progress ---
    tasks_completed: int = 0
    tasks_remaining: int = 0
    budget_consumed_pct: float = 0.0
    team_notes: str = ""                    # Coordinator's running assessment

    # --- Task Ledger (Magentic-One pattern) ---
    facts: list[str] = []                   # Verified information
    educated_guesses: list[str] = []        # Hypotheses (clearly marked as unverified)
    current_plan: list[str] = []            # Active plan steps
```

### 7.4 The 35-Minute Rule

Research shows agent performance degrades after ~35 minutes of continuous work. The system enforces this:

1. The coordinator estimates task duration during decomposition
2. Tasks estimated at >35 minutes are flagged for decomposition
3. If a running agent exceeds 35 minutes, the system emits a warning (but doesn't kill the agent)
4. The coordinator can suggest pausing and resuming with fresh context
5. Workers can always decompose their own task into sub-tasks by spawning assistants

---

## 8. Completion Detection

### 8.1 Layered Architecture

```
Layer 1: HARD LIMITS (always enforced, non-negotiable)
  ├── Workspace budget (tokens, cost, time)
  ├── Per-task budgets
  ├── Max task count (prevents infinite decomposition)
  └── Loop guards (duplicate detection, progress checks)

Layer 2: GOAL SATISFACTION (primary completion signal)
  ├── Acceptance criteria evaluated by coordinator
  ├── All required tasks in DONE status
  ├── Convergence detection (no meaningful progress in N cycles)
  └── External evaluation (reviewer agent or automated check)

Layer 3: HUMAN JUDGMENT (final authority)
  ├── Human lead reviews board and accumulated output
  ├── Coordinator surfaces completion recommendation
  ├── Human approves: workspace moves to COMPLETED
  └── Human requests more: coordinator replans

Layer 4: SCOPE MANAGEMENT (prevents infinite expansion)
  ├── New tasks must reference original goal
  ├── Depth limit on task decomposition
  ├── Replan budget (max N replanning cycles)
  └── Coordinator flags scope creep to human
```

### 8.2 Completion Flow

1. Coordinator detects all initial tasks are done
2. Coordinator evaluates acceptance criteria against produced artifacts
3. Coordinator posts to board: "All planned work complete. Here's a summary: [...]  Acceptance criteria status: [met/not met for each]. Recommend: [complete/continue with X]"
4. Human reviews the board and artifacts
5. Human either:
   - Approves: `agentos workspace complete` → workspace moves to COMPLETED
   - Extends: "Actually, I also want X" → coordinator replans
   - Pivots: "Change direction to Y" → coordinator re-decomposes

### 8.3 Budget as Safety Net

If the budget is exhausted before goal satisfaction:
1. All running agents are gracefully stopped
2. Coordinator produces a "best effort" summary: what was accomplished, what remains
3. Board shows: "Budget exhausted. Workspace paused. Resume with additional budget or complete as-is."
4. Human can: add budget and resume, or accept the partial output

---

## 9. Cost Awareness

Multi-agent coordination costs ~15x more tokens than a single chat interaction. This is justified when tasks genuinely require parallel specialization, but the system must be cost-aware.

### 9.1 Cost Multiplier Reality

| Configuration | Relative Token Cost | When Justified |
|---|---|---|
| Single chat completion | 1x | Simple questions |
| Single agent with tools | 3-10x | Single-domain varied queries |
| Multi-agent workspace | 10-15x | Cross-domain, parallel specialization, distinct security needs |

**Only use multi-agent when a single agent fails** due to prompt complexity, tool overload, or security requirements. The coordinator should prefer the simplest approach that works.

### 9.2 Cost Optimization Levers

| Technique | Savings | How It Works |
|---|---|---|
| **Model routing** (coordinator recommends tier) | Up to 80% | Haiku for simple, Sonnet for moderate, Opus for complex |
| **Prompt caching** (provider-level) | 40-90% input tokens | Reusable system context at top of every request |
| **Progressive context delivery** | ~50% | Only inject new/changed context per activation |
| **Anchored summaries** (vs regeneration) | 20-30% | Incremental update beats full reconstruction |
| **Spawn decision heuristic** | Variable | Don't spawn assistants for <5K token sub-tasks |
| **Team size limit** | Coordination overhead | Flag when team exceeds 5 agents |

### 9.3 Cost-of-Pass Metric

The most useful metric for evaluating workspace efficiency: **expected monetary cost to produce one correct solution.** This combines accuracy and cost:

```
cost_of_pass = cost_per_run / success_rate
```

An agent that is 90% accurate at $0.10/run costs $0.11 per correct result. An agent that is 60% accurate at $0.05/run costs $0.08 per correct result — cheaper despite lower accuracy. The coordinator should factor this into model routing decisions.

### 9.4 Budget Hierarchy

```
Workspace Budget ($50.00)
  ├── Coordinator (~10-15% of budget)
  ├── Worker A — Task 1 ($5.00 allocated)
  │   └── Assistant ($0.50 sub-allocated)
  ├── Worker B — Task 2 ($5.00 allocated)
  ├── Worker C — Task 3 ($5.00 allocated)
  └── Reserve (~30% unallocated for dynamic tasks/replanning)
```

The coordinator allocates budget per task. Workers can sub-allocate to assistants. A reserve ensures budget exists for replanning, new tasks, and unexpected work. Budget alerts fire at 60%, 80%, 95% via the board hooks (already implemented in Phase 2).

---

## 10. Connection to Communication Layer (Phase 1-2)

The workspace runtime is built ON TOP of the comms system, not beside it:

| Comms Component | Role in Workspace Runtime |
|---|---|
| **Board** | The workspace's primary interface — backlog, status, announcements, findings |
| **BoardManager** | Maintains workspace state visible to all participants |
| **MessageBus** | All participant communication — coordinator directives, worker questions, human input |
| **AmbientContextInjector** | Injects board state into AI workers at activation and tool boundaries |
| **MCP Comms Server** | Gives Tier 2 workers board/messaging access during execution |
| **BoardEventHooks** | Auto-updates board from task state changes, budget events, errors |
| **ProtocolManager** | Tracks structured exchanges (consultation, review, escalation) |
| **SpeechAct types** | Coordinator uses `directive` for assignments, workers use `inform`/`request`, humans use `directive` for overrides |

### Board Sections in Workspace Mode

```
Board
├── Announcements        # Coordinator's plan, human directives, locked/unlocked status
├── Backlog              # NEW: Open tasks available for claiming
├── In Progress          # NEW: Tasks currently being worked on (who, what, progress)
├── Team Status          # Agent states (active/dormant), human online status
├── Findings             # Worker posts: discoveries, partial results, data
├── Decisions            # Resolved questions, accepted proposals
├── Questions            # Open questions needing input
├── Alerts               # Budget warnings, blockers, errors
└── Reviews              # NEW: Tasks submitted for review, pending approval
```

---

## 11. What We Build vs. What We Have

### Already Built (Phase 1-2)

| Component | Status |
|---|---|
| Board + Direct Messaging schemas | Done |
| MessageBus (send, receive, reply, threading) | Done |
| BoardManager (post, pin, resolve, archive, render) | Done |
| AmbientContextInjector | Done |
| MCP Communication Server (7 tools) | Done |
| Communication Protocols (consult, review, escalate) | Done |
| Board Auto-Update Hooks | Done |
| Tier 1 message-aware loop | Done |
| Tier 2 workspace file comms | Done |
| CLI commands (board, message) | Done |
| Event types for all comms | Done |
| 154 tests | Done |

### Needs Refactoring

| Component | Current | Needed |
|---|---|---|
| DAG Executor | Static DAG walker | Backlog-aware workspace runtime |
| Task schema | DAG-oriented TaskConfig | BacklogTask with claiming, review status |
| Team system | Manager adapter pattern | Coordinator + worker + assistant roles |
| Agent spawning | TeamComposer (policy-gated) | Dynamic spawn via coordinator proposals |
| Budget | Per-agent flat | Hierarchical: workspace → task → assistant |

### New to Build

| Component | Description |
|---|---|
| `WorkspaceConfig` schema | Workspace definition (goal, team, mode, budget) |
| `BacklogManager` | Task backlog: create, claim, complete, review, chaining, dynamic priority |
| `WorkspaceRuntime` | The main runtime: manages coordinator, workers, backlog, lifecycle |
| `CoordinatorAgent` | Two-ledger goal decomposition, failure escalation ladder, model routing, replanning |
| `AgentContextSummary` | Factory 4-field anchored summaries with incremental merge |
| `ProgressiveContextDelivery` | Track what each agent has seen, inject only changes |
| `AssistantSpawner` | Lightweight spawning with depth-1 limit and spawn decision heuristic |
| `CompletionDetector` | Layered completion: hard limits → goal satisfaction → human sign-off |
| `CostTracker` | Cost-of-pass metrics, model routing recommendations, budget hierarchy |
| CLI workspace commands | `workspace create`, `task claim`, `assistant spawn`, etc. |
| Conversational workspace builder | Natural language → WorkspaceConfig |

### Implementation Phases

**Phase 3A: Workspace Foundation**
- WorkspaceConfig schema (team, coordinator, modes, budget)
- BacklogManager (task lifecycle, dependencies, chaining, dynamic priority)
- WorkspaceRuntime (basic: coordinator + workers + backlog, event-sourced)
- CLI: workspace create, task claim/complete, workspace export

**Phase 3B: Coordinator Intelligence**
- CoordinatorAgent with two-ledger pattern (Task Ledger + Progress Ledger)
- Goal decomposition with explicit non-overlapping task specs
- Failure recovery escalation ladder (retry → reassign → replan → decompose → escalate)
- Model routing recommendations per task
- Team evolution proposals (dynamic mode) with 5-agent team size awareness
- Scope management (goal anchoring, depth limits, replan budgets)

**Phase 3C: Context & Lifecycle**
- AgentContextSummary (Factory 4-field anchored summaries with incremental merge)
- WorkspaceContextSummary (coordinator-maintained, includes Task Ledger fields)
- Progressive context delivery (track last-seen versions, inject only changes)
- Context budget allocation (50% utilization target, staleness prevention)
- Assistant spawning with depth-1 limit and spawn decision heuristic
- 35-minute rule enforcement
- Dormant/active state management

**Phase 3D: Completion, Cost, and Polish**
- CompletionDetector (layered: hard limits → goal satisfaction → human sign-off)
- CostTracker (cost-of-pass metrics, model routing integration, budget hierarchy)
- Conversational workspace builder (natural language → WorkspaceConfig)
- Workspace persistence across sessions
- Integration tests with real agents
