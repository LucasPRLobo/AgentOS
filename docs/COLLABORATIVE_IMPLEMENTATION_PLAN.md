# AgentOS — Collaborative Workspace: Detailed Implementation Plan

**Companion to:** COLLABORATIVE_WORKSPACE_UPDATE.md
**Date:** March 2026
**Status:** Implementation plan — task-by-task

---

## Overview

Transform the workspace from a dispatch model (coordinator assigns, agents execute silently) to a discussion-driven collaboration model where the human thinks WITH the team through structured conversations at every decision point.

**Core change:** Every decision becomes a discussion thread. The coordinator facilitates, the human participates, and only after agreement does work proceed.

---

## Step 1: Discussion Thread Schema + Event Types

**Goal:** Define the data model for structured discussions.

### New file: `agentos/comms/discussions.py`

```python
class DiscussionType(StrEnum):
    KICKOFF = "kickoff"           # Project start — goals, priorities, constraints
    TASK_SPEC = "task_spec"       # Before execution — approach, scope, assignment
    CHECK_IN = "check_in"        # Mid-execution — progress, direction, issues
    REVIEW = "review"            # After completion — evaluate, accept, refine
    REPLAN = "replan"            # Plan needs changing — discuss new direction
    ESCALATION = "escalation"    # Agent stuck — discuss resolution

class DiscussionStatus(StrEnum):
    OPEN = "open"                 # Awaiting human response
    ACTIVE = "active"             # Back-and-forth in progress
    RESOLVED = "resolved"         # Agreement reached, decision recorded
    DEFERRED = "deferred"         # Parked for later

class DiscussionThread(BaseModel):
    thread_id: str                          # UUID
    discussion_type: DiscussionType
    status: DiscussionStatus
    title: str                              # Short summary of what's being discussed
    context: str                            # Why this discussion was opened
    participants: list[str]                 # IDs: coordinator, human, relevant agents
    messages: list[DirectMessage]           # The conversation
    decision: str | None                    # What was agreed (set on resolution)
    decision_rationale: str | None          # Why (for audit)
    related_task_id: str | None             # If about a specific task
    created_at: str
    resolved_at: str | None

    # Coordinator's initial question/proposal
    opening_message: str
    # Options/recommendations (if applicable)
    options: list[str] | None = None        # "a) Accept as-is  b) Refine  c) Go deeper"

class DiscussionManager:
    """Manages discussion threads for a workspace."""

    def open(self, discussion_type, title, context, opening_message,
             participants, options=None, related_task_id=None) -> str:
        """Open a new discussion. Returns thread_id. Posts to board."""

    def add_message(self, thread_id, sender_id, sender_type, content,
                     speech_act="inform") -> None:
        """Add a message to the discussion."""

    def resolve(self, thread_id, decision, rationale="") -> None:
        """Resolve a discussion with a decision. Posts decision to board."""

    def defer(self, thread_id, reason="") -> None:
        """Defer a discussion for later."""

    def get_open(self) -> list[DiscussionThread]:
        """Get all open/active discussions needing attention."""

    def get_for_task(self, task_id) -> list[DiscussionThread]:
        """Get discussions related to a specific task."""

    def get_thread(self, thread_id) -> DiscussionThread:
        """Get a specific discussion thread."""

    def has_open_discussions(self) -> bool:
        """Quick check: any discussions needing human input?"""
```

### Event types to add in `schemas/events.py`:

```python
DISCUSSION_OPENED = "discussion.opened"
DISCUSSION_MESSAGE = "discussion.message"
DISCUSSION_RESOLVED = "discussion.resolved"
DISCUSSION_DEFERRED = "discussion.deferred"
```

### Tests: `tests/unit/test_discussions.py`

- Open discussion, verify it appears in get_open()
- Add messages to discussion
- Resolve discussion, verify decision recorded
- Defer discussion
- Get discussions for a specific task
- has_open_discussions() accuracy
- Event logging for all mutations
- Thread with multiple participants

**Estimated: ~250 lines code, ~200 lines tests**

---

## Step 2: Coordinator Prompt Rewrite — Facilitator Mode

**Goal:** The coordinator asks questions and proposes with rationale instead of dispatching directly.

### Modify: `agentos/workspace/coordinator_prompts.py`

Replace all prompts with discussion-oriented versions:

**New prompt: `build_kickoff_discussion_prompt()`**
```
You are the workspace coordinator. Your job is to FACILITATE, not dictate.

A new workspace has been created with this goal:
{goal}

Before creating any tasks, you need to align with the human lead.
Open a discussion by:
1. Briefly reflecting back what you understand the goal to be
2. Asking 2-3 focused questions that would shape your approach:
   - What matters most (speed, depth, cost)?
   - Any specific angles or constraints?
   - Who is the output for?
3. Sharing your initial thinking: "Based on this, I'm considering [approach].
   Does that align, or should we go a different direction?"

Write your opening message to the human. Be conversational, not formal.
Do NOT create tasks yet — wait for the human's input.

Output as JSON:
{
  "opening_message": "your conversational message to the human",
  "questions": ["question 1", "question 2", "question 3"],
  "initial_thinking": "what you're considering and why",
  "options": ["option A description", "option B description"]
}
```

**New prompt: `build_plan_from_discussion_prompt()`**
```
Based on the kickoff discussion, the human and coordinator agreed:
{discussion_summary}

Now create the task plan. For each task, provide:
- A spec (what, why, expected output)
- Who should do it and why
- What context they need

But ALSO include a brief message asking the human:
"Here's the plan based on our discussion. [summary].
Does this capture what we agreed? Anything to adjust before we start?"

Output as JSON:
{
  "plan_summary": "...",
  "confirmation_message": "...",
  "tasks": [...]
}
```

**New prompt: `build_check_in_prompt()`**
```
A task has just completed / hit a milestone / encountered an issue.
Task: {task_title}
What happened: {event_summary}
Current state: {board_compact}

Decide if this warrants a discussion with the human.
Criteria for opening a discussion:
- Something unexpected was found
- A decision needs to be made about direction
- Quality or scope concern
- Task failed or is stuck

If YES, write a brief, conversational check-in message:
- Summarize what happened (2-3 sentences)
- Flag what matters
- Ask a specific question with a recommendation

If NO, just post a status update to the board (no discussion needed).

Output as JSON:
{
  "needs_discussion": true/false,
  "message": "...",
  "question": "..." or null,
  "recommendation": "..." or null
}
```

**New prompt: `build_review_discussion_prompt()`**
```
A task has been completed. Review the output and open a discussion.
Task: {task_title}
Original spec: {task_spec}
Output summary: {output_summary}

Your job:
1. Compare output against the original spec
2. Identify what was done well
3. Flag any gaps, surprises, or opportunities
4. Suggest next steps

Write a conversational review message:
"Here's what [agent] produced for [task]. [summary].
I noticed [observation]. [strength/gap].
Should we: (a) accept and move on, (b) ask for refinement, (c) dig deeper on [aspect]?"

Output as JSON:
{
  "review_message": "...",
  "spec_match": "full" / "partial" / "missed",
  "gaps": ["..."],
  "strengths": ["..."],
  "options": ["Accept as-is", "Refine: ...", "Go deeper on: ..."],
  "recommendation": "which option and why"
}
```

### Tests: `tests/unit/test_coordinator_prompts_v2.py`

- Each prompt template produces valid output
- Required fields present
- Question/option structure correct
- Prompts are conversational in tone (not formal/robotic)

**Estimated: ~300 lines prompts, ~100 lines tests**

---

## Step 3: Task Status + Spec Tracking

**Goal:** Tasks track their specification status and go through discussion before execution.

### Modify: `agentos/workspace/schemas.py`

Add new statuses and spec fields to BacklogTask:

```python
class BacklogTaskStatus(StrEnum):
    PROPOSED = "proposed"         # NEW: Coordinator proposed, not yet discussed
    SPECIFYING = "specifying"     # NEW: Spec discussion in progress
    OPEN = "open"                 # Spec agreed, ready to claim
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"       # NEW: Agent says done, awaiting review
    IN_REVIEW = "in_review"       # Review discussion in progress
    REVISION_NEEDED = "revision_needed"
    DONE = "done"                 # Review passed, accepted
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

# Add to BacklogTask:
class BacklogTask(BaseModel):
    # ... existing fields ...

    # NEW: Specification fields
    spec: str | None = None                  # Agreed specification from discussion
    spec_approach: str | None = None         # How the task should be done
    spec_expected_output: str | None = None  # What success looks like
    spec_discussion_id: str | None = None    # Discussion where spec was agreed

    # NEW: Review fields
    review_discussion_id: str | None = None  # Discussion where review happened
    review_verdict: str | None = None        # "accepted" / "revise" / "deeper"
```

### Modify: `agentos/workspace/backlog.py`

Add new lifecycle methods:

```python
def propose_task(self, task: BacklogTask) -> str:
    """Create a task in PROPOSED status (not yet discussed)."""
    task.status = BacklogTaskStatus.PROPOSED
    return self.create_task(task)

def start_specifying(self, task_id: str, discussion_id: str) -> None:
    """Move to SPECIFYING — discussion opened about this task."""

def finalize_spec(self, task_id: str, spec: str, approach: str,
                   expected_output: str) -> None:
    """Spec agreed — move to OPEN (ready to claim)."""

def mark_completed(self, task_id: str, output: dict) -> None:
    """Agent says done — move to COMPLETED (awaiting review)."""

def start_review(self, task_id: str, discussion_id: str) -> None:
    """Review discussion opened — move to IN_REVIEW."""

def accept_review(self, task_id: str, verdict: str) -> None:
    """Review passed — move to DONE."""
```

### Tests: `tests/unit/test_backlog_spec_flow.py`

- Full flow: PROPOSED → SPECIFYING → OPEN → CLAIMED → IN_PROGRESS → COMPLETED → IN_REVIEW → DONE
- Cannot claim a PROPOSED task (must be specified first)
- Cannot mark DONE without review
- Revision flow: IN_REVIEW → REVISION_NEEDED → IN_PROGRESS → COMPLETED → IN_REVIEW → DONE
- Spec fields preserved through lifecycle

**Estimated: ~150 lines schema changes, ~100 lines backlog changes, ~200 lines tests**

---

## Step 4: Discussion-Aware Runtime Loop

**Goal:** The runtime pauses for open discussions and resumes when they resolve.

### Modify: `agentos/workspace/runtime.py`

Rewrite `run()` to be discussion-aware:

```python
async def run(self, max_cycles=50):
    """Discussion-driven workspace execution loop."""

    # Phase 1: Kickoff discussion
    if not self._backlog.get_all_tasks():
        await self._kickoff_discussion()
        # Wait for human to respond and agree on plan
        await self._wait_for_discussion_resolution("kickoff")
        # Create tasks from agreed plan
        await self._create_tasks_from_plan()

    # Main loop
    for cycle in range(max_cycles):
        # Check for open discussions first — they block execution
        open_discussions = self._discussions.get_open()
        if open_discussions:
            # Don't execute — wait for human input
            # (In dashboard mode, this means checking periodically)
            # (In CLI mode, this means prompting the user)
            await self._wait_for_discussions(open_discussions)
            continue

        # Check completion
        result = self._completion.check()
        if result.complete:
            # Open final review discussion
            await self._final_review_discussion()
            break

        # Find tasks ready to execute (OPEN status, deps met)
        ready = self._backlog.get_open_tasks()
        if not ready:
            # Check if there are PROPOSED tasks needing spec discussion
            proposed = [t for t in self._backlog.get_all_tasks()
                       if t.status == "proposed"]
            if proposed:
                await self._spec_discussion(proposed[0])
                continue
            break

        # Execute one task
        task = ready[0]
        await self._execute_with_discussion(task)
```

New helper methods:

```python
async def _kickoff_discussion(self):
    """Open kickoff discussion with the human."""
    # Run coordinator to generate opening message
    # Post to board as a discussion thread
    # Register discussion in DiscussionManager

async def _spec_discussion(self, task):
    """Open spec discussion for a proposed task."""
    # Coordinator proposes spec
    # Opens discussion thread
    # Waits for human agreement

async def _execute_with_discussion(self, task):
    """Execute a task with check-in and review discussions."""
    # Claim and execute
    # After completion: coordinator reviews output
    # If meaningful: open review discussion
    # Wait for resolution
    # Mark DONE or REVISION_NEEDED

async def _wait_for_discussions(self, discussions):
    """Wait for all open discussions to be resolved."""
    # In CLI mode: print discussion, prompt user
    # In dashboard mode: poll for resolution
    # In async mode: yield until WebSocket delivers resolution

async def _wait_for_discussion_resolution(self, discussion_type):
    """Wait for a specific type of discussion to resolve."""
```

### Two execution modes:

**Interactive (CLI/dashboard):** The runtime pauses at discussions and waits for human input via CLI prompt or dashboard WebSocket.

**Async (background):** The runtime posts discussions to the board and continues with non-dependent work. When the human responds (via CLI, dashboard, or MCP), the runtime picks up the resolution.

```python
class ExecutionMode(StrEnum):
    INTERACTIVE = "interactive"    # Pause and wait at every discussion
    ASYNC = "async"                # Post and continue, pick up responses later
    AUTO = "auto"                  # Only pause for kickoff and review, auto-proceed for check-ins
```

### Tests: `tests/unit/test_runtime_discussions.py`

- Runtime opens kickoff discussion on start
- Runtime pauses when discussion is open
- Runtime resumes when discussion resolves
- Tasks execute only after spec is agreed
- Review discussion opens after task completion
- Execution mode affects pausing behavior

**Estimated: ~300 lines runtime changes, ~200 lines tests**

---

## Step 5: Context Curation Per Task

**Goal:** Each task gets a purpose-built context package, not the full workspace dump.

### New file: `agentos/workspace/context_curator.py`

```python
class ContextCurator:
    """Assembles curated context packages per task."""

    def curate_for_task(self, task: BacklogTask,
                         workspace_state) -> TaskContext:
        """Build a focused context package for this specific task."""

        return TaskContext(
            # From the spec discussion
            task_spec=task.spec,
            approach=task.spec_approach,
            expected_output=task.spec_expected_output,

            # Only relevant predecessors
            relevant_findings=self._find_relevant_findings(task, workspace_state),
            relevant_decisions=self._find_relevant_decisions(task, workspace_state),

            # Compact workspace awareness
            project_brief=self._build_project_brief(workspace_state),
            team_context=self._build_team_context(workspace_state),
        )

    def _find_relevant_findings(self, task, state) -> list[str]:
        """Find findings from predecessor tasks that are relevant."""
        # Only from tasks this task depends on
        # Plus any board posts tagged for this task's domain

    def _find_relevant_decisions(self, task, state) -> list[str]:
        """Find resolved discussions whose decisions affect this task."""
        # From DECISIONS.md or resolved discussion threads

    def _build_project_brief(self, state) -> str:
        """2-3 sentence project summary from PROJECT.md."""

    def _build_team_context(self, state) -> str:
        """One line per agent: name, role, current state."""

class TaskContext(BaseModel):
    task_spec: str = ""
    approach: str = ""
    expected_output: str = ""
    relevant_findings: list[str] = []
    relevant_decisions: list[str] = []
    project_brief: str = ""
    team_context: str = ""
```

### Modify: `agentos/workspace/runtime.py`

Use ContextCurator when building the prompt for agent execution instead of the current full-dump approach.

### Tests: `tests/unit/test_context_curator.py`

- Curated context includes only relevant predecessor findings
- Curated context includes spec from discussion
- Curated context doesn't include unrelated tasks' outputs
- Project brief is compact (<200 tokens)
- Team context is one line per agent

**Estimated: ~200 lines curator, ~150 lines tests**

---

## Step 6: Project Artifacts

**Goal:** Shared documents that both humans and agents read and update.

### New file: `agentos/workspace/artifacts.py`

```python
class ProjectArtifacts:
    """Manages shared project documents in the workspace."""

    def __init__(self, workspace_dir: Path):
        self._dir = workspace_dir

    def write_project(self, goal, description, constraints, criteria):
        """Write/update PROJECT.md from kickoff discussion."""

    def write_plan(self, plan_summary, tasks):
        """Write/update PLAN.md from agreed plan."""

    def add_decision(self, decision, rationale, discussion_id):
        """Append to DECISIONS.md."""

    def update_state(self, backlog, team_status):
        """Rewrite STATE.md with current progress."""

    def write_task_spec(self, task_id, title, spec, approach, expected_output):
        """Write tasks/{task_id}-spec.md."""

    def write_task_output(self, task_id, title, output_summary, findings):
        """Write tasks/{task_id}-output.md."""

    def get_project_brief(self) -> str:
        """Read PROJECT.md and return concise brief."""

    def get_decisions(self) -> list[str]:
        """Read DECISIONS.md and return list of decisions."""

    def get_state(self) -> str:
        """Read STATE.md."""
```

These files are the **collaboration surface** — the coordinator writes them after discussions, agents reference them for context, humans can read and edit them directly.

### Integration with runtime:

- After kickoff discussion resolves → write PROJECT.md
- After plan is agreed → write PLAN.md
- After any discussion resolves → append to DECISIONS.md
- After each task completes → update STATE.md
- Before each task executes → write task spec to tasks/

### Tests: `tests/unit/test_project_artifacts.py`

- Write and read PROJECT.md
- Append decisions correctly
- STATE.md reflects current backlog state
- Task specs written to correct paths
- All files are human-readable markdown

**Estimated: ~200 lines code, ~120 lines tests**

---

## Step 7: Verification Flow

**Goal:** After each task completes, verify output against spec before accepting.

### New file: `agentos/workspace/verifier.py`

```python
class TaskVerifier:
    """Verifies task output against specification."""

    def auto_verify(self, task: BacklogTask, output: dict) -> VerificationResult:
        """Quick automated checks:
        - Does output exist?
        - Does it have required files (from spec)?
        - Is output non-empty and well-formed?
        - Does summary address the task description?
        """

    def prepare_review(self, task, output, auto_result) -> dict:
        """Prepare review discussion context for the coordinator:
        - Auto-verification results
        - Output summary
        - Comparison against spec
        - Suggested discussion message
        """

class VerificationResult(BaseModel):
    passed: bool
    checks: list[dict]  # {"check": "name", "passed": bool, "detail": "..."}
    issues: list[str]
    recommendation: str  # "ready_for_review" / "auto_accept" / "failed"
```

### Integration with runtime:

After an agent completes a task:
1. `auto_verify()` runs immediately
2. If failed → open review discussion with issues flagged
3. If passed → coordinator evaluates and decides:
   - Simple task with clear spec match → auto-accept (post to board, no discussion)
   - Complex task or partial match → open review discussion
4. Review discussion resolves → task moves to DONE or REVISION_NEEDED

### Tests: `tests/unit/test_verifier.py`

- Auto-verify catches missing output
- Auto-verify checks for expected files
- Review preparation includes spec comparison
- Simple task with clean output → auto-accept recommendation
- Complex task → review recommendation

**Estimated: ~150 lines code, ~120 lines tests**

---

## Step 8: Frontend Updates

**Goal:** Dashboard supports discussion threads, spec tracking, and collaborative interaction.

### 8a: Discussion types and API

**New TypeScript types** in `types/workspace.ts`:
```typescript
interface DiscussionThread {
  thread_id: string
  discussion_type: 'kickoff' | 'task_spec' | 'check_in' | 'review' | 'replan' | 'escalation'
  status: 'open' | 'active' | 'resolved' | 'deferred'
  title: string
  opening_message: string
  options?: string[]
  decision?: string
  messages: DirectMessage[]
  related_task_id?: string
  created_at: string
  resolved_at?: string
}
```

**New API endpoints** (backend + frontend client):
```
GET  /api/workspaces/:id/discussions          → list discussions
POST /api/workspaces/:id/discussions/:threadId/reply   → reply to discussion
POST /api/workspaces/:id/discussions/:threadId/resolve → resolve with decision
```

**Estimated: ~80 lines types, ~100 lines API**

### 8b: Board becomes Discussion Feed

**Modify:** `BoardFeed.tsx`

- Discussion threads appear as expandable cards in the feed
- Open discussions pinned to top with attention indicator
- Click to expand → shows full conversation
- Inline reply box for quick response
- Resolution shows as highlighted decision card

**New component:** `DiscussionCard.tsx`
- Shows discussion type icon + title
- Status badge (open/active/resolved)
- Opening message
- Options as clickable buttons (if provided)
- Reply input
- Resolve button

**Estimated: ~200 lines DiscussionCard, ~100 lines BoardFeed changes**

### 8c: Kanban spec status indicators

**Modify:** `TaskCard.tsx`

Add spec status indicator to each card:
- ⬜ PROPOSED — "Needs discussion"
- 🟡 SPECIFYING — "In discussion"
- 🟢 OPEN — "Ready"
- 🔵 IN_PROGRESS — "Running"
- 🟠 COMPLETED — "Awaiting review"
- 🟣 IN_REVIEW — "Under review"
- ✅ DONE — "Accepted"

**Modify:** `KanbanBacklog.tsx`

Add PROPOSED column before OPEN.

**Estimated: ~60 lines changes**

### 8d: Chat panel discussion integration

**Modify:** `ChatPanel.tsx`

When a discussion is open and involves the selected agent:
- Show the discussion thread in the chat panel
- Reply input sends to the discussion (not as a direct message)
- Resolution options appear as buttons

**Estimated: ~80 lines changes**

### 8e: Workspace header updates

**Modify:** `WorkspaceHeader.tsx`

- Active discussion count badge: "2 discussions need your input"
- Clicking the badge scrolls to the first open discussion on the board

**Estimated: ~30 lines changes**

---

## Step 9: End-to-End Integration

**Goal:** Wire everything together and test with real agents.

### Integration tasks:

1. **DiscussionManager ↔ Runtime**: Runtime opens discussions at kickoff, spec, check-in, review
2. **DiscussionManager ↔ Board**: Discussion openings and resolutions post to the board
3. **DiscussionManager ↔ WebSocket**: Open discussions push to frontend in real-time
4. **ContextCurator ↔ Agent execution**: Curated context replaces full dump in agent prompts
5. **ProjectArtifacts ↔ Discussions**: Decisions flow from resolved discussions to DECISIONS.md
6. **Verifier ↔ Runtime**: Auto-verify runs after each task, feeds into review discussion
7. **Coordinator ↔ Discussions**: Coordinator generates discussion-opening messages

### Update demo scripts:

**`examples/workspace_interactive.py`** — full discussion-driven flow:
1. Coordinator opens kickoff discussion
2. Human answers questions in terminal
3. Plan proposed and discussed
4. Tasks execute with check-ins
5. Reviews are conversations
6. Final acceptance

**`examples/start_dashboard.py`** — dashboard with pre-loaded discussions:
1. One open kickoff discussion (human can respond)
2. One task with spec discussion resolved
3. One task in review with discussion open
4. Shows the full discussion-driven UI

### Tests: `tests/integration/test_collaborative_flow.py`

- Full flow: kickoff → spec → execute → review → done (mock agents, mock human)
- Discussion resolution triggers correct state transitions
- Context curation produces correct packages
- Artifacts written at correct moments
- Verification catches issues and opens review discussion

**Estimated: ~200 lines integration test, ~150 lines demo updates**

---

## Summary

| Step | New/Modified Files | Lines (est.) | Dependencies |
|---|---|---|---|
| **1. Discussion schema** | `comms/discussions.py`, `schemas/events.py`, tests | ~450 | None |
| **2. Coordinator prompts** | `workspace/coordinator_prompts.py`, tests | ~400 | Step 1 |
| **3. Task status + spec** | `workspace/schemas.py`, `workspace/backlog.py`, tests | ~450 | Step 1 |
| **4. Runtime loop** | `workspace/runtime.py`, tests | ~500 | Steps 1-3 |
| **5. Context curation** | `workspace/context_curator.py`, tests | ~350 | Step 3 |
| **6. Project artifacts** | `workspace/artifacts.py`, tests | ~320 | Steps 1, 4 |
| **7. Verification** | `workspace/verifier.py`, tests | ~270 | Steps 3, 4 |
| **8. Frontend** | 5 modified + 1 new component, types, API | ~650 | Steps 1-7 (backend) |
| **9. Integration** | demos, integration tests | ~350 | Everything |
| **Total** | | **~3,740** | |

### Dependency graph:

```
Step 1 (Discussion schema) ──┐
                              ├── Step 2 (Coordinator prompts)
                              ├── Step 3 (Task status + spec) ──┐
                              │                                  ├── Step 4 (Runtime loop)
                              │                                  ├── Step 5 (Context curation)
                              │                                  └── Step 7 (Verification)
                              └── Step 6 (Project artifacts)

Steps 1-7 (all backend) ──── Step 8 (Frontend)
Steps 1-8 ──────────────── Step 9 (Integration + E2E)
```

### Parallel opportunities:

- Steps 2, 3, 6 are independent once Step 1 is done
- Step 5 is independent once Step 3 is done
- Step 7 is independent once Steps 3-4 are done
- Step 8 frontend types can start with Step 1

### What the human experiences after implementation:

```
[Workspace starts]
Coordinator: "I've read your goal. Before I plan, a few questions:
  1. What matters most — depth or speed?
  2. Any specific focus areas?
  Here's what I'm initially thinking: [approach].
  What do you think?"