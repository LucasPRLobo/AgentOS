# AgentOS — Collaborative Workspace: Architecture Update

**Companion to:** WORKSPACE_RUNTIME_DESIGN.md | COMMS_RESEARCH_AND_PLAN.md
**Date:** March 2026
**Status:** Design update — incorporating SDD research + discussion-driven collaboration

---

## The Problem

The current workspace implementation follows a **dispatch model**:

```
Coordinator produces plan → human approves/rejects → agents execute silently → results presented
```

This feels like managing, not collaborating. The human is an approver, not a thinker. Agents work in a black box. The human only sees outputs, not process. There's no conversation, no shared thinking, no "working together."

## The Insight

Two sources converge on the same fix:

**From SDD tools research** (GSD, Spec Kit, OpenSpec, Taskmaster AI):
- All converge on a **specify → plan → execute → verify** loop
- The specification phase is where human-AI alignment happens — it's the most valuable step
- Context isolation per task prevents degradation
- Structured artifacts create natural collaboration boundaries

**From our own discussion:**
- The coordinator should be a **conversational partner**, not a task dispatcher
- Every decision point should be a **discussion**, not a presentation
- The human should feel like they're **thinking with the team**, not managing it
- Questions with recommendations beat open-ended questions AND binary approve/reject

## The New Flow: Discussion-Driven Collaboration

### The Core Loop

```
DISCUSS → SPECIFY → EXECUTE → VERIFY → DISCUSS
```

At each stage, the coordinator opens a conversation with the human. Not "here's what I decided, approve?" but "here's what I'm thinking, what do you think?"

### Flow Detail

```
1. KICKOFF DISCUSSION
   Coordinator: "I've read your goal. Before I plan, some questions:
   - What's most important: speed, quality, or cost?
   - Any specific angle you want covered?
   - Who on the team should lead this?"
   Human: [responds naturally]
   Coordinator: "Got it. Based on that, here's what I'm thinking: [...]"
   Human: [adjusts, agrees, or asks more]
   → They AGREE on the approach together

2. SPECIFICATION
   Coordinator writes up what was agreed as structured specs
   For each task: title, approach, expected output, who does it
   Posted to board as "Proposed Plan"
   Human can still adjust

3. EXECUTION (with check-ins)
   Agents work on tasks
   Coordinator surfaces meaningful updates:
   - "Researcher found something unexpected: [X]. Should we adjust?"
   - "This task is taking longer than expected. Continue or pivot?"
   - "Agent B has a question: [Q]"
   Human responds when relevant (async, not blocking)

4. VERIFICATION
   When a task completes, coordinator doesn't just say "done"
   Opens a review discussion:
   - "Here's what was produced: [summary]"
   - "I noticed [gap/issue/opportunity]"
   - "Should we: (a) accept, (b) refine, (c) go deeper?"
   Human and coordinator discuss, then decide

5. NEXT CYCLE
   Based on what was learned, coordinator proposes next steps
   Discussion continues...
```

### The Key Principle

**The coordinator asks questions, not for permission, but for direction.**

Bad: "I plan to create 3 tasks. Approve?" (binary, no thinking)
Good: "I'm thinking 3 tasks. The research should focus on X because of Y. Does that match what you need, or should we prioritize Z instead?" (invites thinking)

Bad: "Task complete. Approve?" (rubber stamp)
Good: "Research is done. The key finding is [X]. Two things I want to flag: [gap A] and [strength B]. Should we build on this or address the gaps first?" (shared evaluation)

---

## Architectural Changes

### 1. Discussion Threads Replace Approve/Reject Gates

Current gates are binary: approve or reject. Replace with **discussion threads** — structured conversations between the coordinator and human at decision points.

```python
class DiscussionThread:
    """A conversation at a decision point."""
    thread_id: str
    discussion_type: Literal[
        "kickoff",          # Project start — goals, priorities, constraints
        "task_spec",        # Before task execution — approach, scope, assignment
        "check_in",         # Mid-execution — progress, direction, issues
        "review",           # After task completion — evaluate, refine, accept
        "replan",           # When plan needs changing — discuss new direction
        "escalation",       # Agent stuck — discuss resolution
    ]
    status: Literal["open", "resolved", "deferred"]
    participants: list[str]              # coordinator + human + relevant agents
    messages: list[DirectMessage]
    decision: str | None = None          # What was agreed
    created_at: str
    resolved_at: str | None = None
```

Discussion threads live on the board and in the chat panel. The coordinator opens them, the human responds, and when they reach agreement, the coordinator records the decision and proceeds.

### 2. The Coordinator Becomes a Facilitator

The coordinator's prompt changes from "decompose this goal into tasks" to "facilitate a discussion about this goal, ask good questions, propose approaches, and reach agreement with the human."

**Coordinator behavior at each phase:**

**Kickoff:**
```
1. Read the goal and context
2. Identify 2-3 key questions that would shape the approach
3. Post to board with questions + initial thinking
4. Wait for human response
5. Incorporate response, refine approach
6. Repeat until alignment is clear
7. Write up the agreed plan
```

**Task specification:**
```
1. For each proposed task, post a brief spec:
   - What will be done (specific)
   - Why this approach (rationale)
   - What the output should look like
   - Who should do it (with reasoning)
2. Ask: "Does this capture it? Anything to adjust?"
3. Only assign when human confirms (or in auto mode, proceed with notification)
```

**Check-in (during execution):**
```
1. When something meaningful happens (finding, blocker, completion):
   - Summarize what happened in 2-3 sentences
   - Flag anything the human should know
   - Ask a specific question IF human input would help
2. Don't interrupt for routine progress — only for decisions
```

**Review:**
```
1. When task completes, don't just show output
   - Summarize what was accomplished
   - Compare against the original spec
   - Flag gaps, surprises, or opportunities
   - Suggest next steps
2. Ask: "Should we accept this and move on, refine it, or go deeper?"
```

### 3. Context Curation Per Task (from GSD)

Instead of giving every agent the full board + all predecessors + all summaries, assemble a **purpose-built context package** per task:

```python
class TaskContext:
    """Curated context for a specific task — not the full workspace dump."""

    # From the specification phase
    task_spec: str                       # What was agreed in the discussion
    approach: str                        # How it should be done
    expected_output: str                 # What success looks like

    # Curated predecessors (only relevant ones)
    relevant_findings: list[str]         # Specific findings this task needs
    relevant_decisions: list[str]        # Decisions that affect this task

    # Workspace awareness (compact, not full dump)
    project_brief: str                   # 2-3 sentence goal + constraints
    team_context: str                    # Who's doing what (one line per agent)

    # NOT included:
    # - Full board history (too noisy)
    # - Unrelated predecessor outputs
    # - Other agents' conversation histories
    # - Resolved discussions from other tasks
```

This addresses the "context rot" problem identified in the SDD research — agents degrade when their context fills with irrelevant accumulated history.

### 4. Verification Step (from SDD + Discussion)

After each task completes, before marking it DONE:

1. **Auto-verification**: Check output against spec (does it have the expected fields/files?)
2. **Coordinator review**: Coordinator evaluates quality, flags issues
3. **Human discussion**: Coordinator opens a review thread with findings

Only after the review discussion resolves does the task move to DONE.

```
OPEN → CLAIMED → IN_PROGRESS → COMPLETED → IN_REVIEW → DONE
                                     ↑                    ↓
                                     └── REVISION_NEEDED ←┘
```

The new state is `COMPLETED` (agent says it's done) → `IN_REVIEW` (coordinator + human discuss) → `DONE` (agreed to accept).

### 5. Project Artifacts as Shared Thinking Surface

Inspired by GSD's PROJECT.md / REQUIREMENTS.md / STATE.md pattern, the workspace should have structured documents that both humans and agents read and update:

```
workspace/
├── PROJECT.md           # Goal, constraints, success criteria (written during kickoff)
├── PLAN.md              # Current plan (updated after each discussion)
├── DECISIONS.md         # Key decisions with rationale (extracted from discussions)
├── STATE.md             # What's done, what's in progress, what's next
└── tasks/
    ├── task-1-spec.md   # Spec from the specification discussion
    ├── task-1-output.md # What the agent produced
    └── ...
```

These aren't just files — they're **collaboration surfaces**. The coordinator writes them, the human reads and edits them, agents reference them. They persist across sessions.

---

## How This Changes the Dashboard

The dashboard needs to support discussion-driven collaboration:

### Board → Discussion Feed

The board becomes a **discussion feed** where threads are opened, questions are asked, and decisions are made. Not just a status display.

- **Thread view**: Click a discussion to see the full conversation
- **Quick reply**: Respond to coordinator questions without leaving the board
- **Decision markers**: When a discussion resolves, the decision is highlighted
- **Active discussions** pinned to top — these need your attention

### Chat → Discussion Panel

The chat panel isn't just for messaging agents. It's where the human participates in discussions:

- **Discussion notifications**: "Coordinator wants to discuss task approach"
- **Inline responses**: Answer questions, provide direction, adjust plans
- **Discussion history**: See all decisions made in this workspace

### Backlog → Spec-Tracked Tasks

Each task card shows its specification status:

- ⬜ No spec (not yet discussed)
- 🟡 Spec in discussion (coordinator and human talking)
- 🟢 Spec agreed (ready to execute)
- 🔵 In execution
- 🟣 In review (output being discussed)
- ✅ Done (accepted)

---

## Implementation Plan

### What Changes in the Backend

| Component | Current | Change |
|---|---|---|
| **CoordinatorRunner** | Writes tasks.json directly | Opens discussion first, writes specs after agreement |
| **WorkspaceRuntime.run()** | Batch: find ready → execute → next | Discussion-aware: check for open discussions → wait for resolution → then execute |
| **BacklogManager** | OPEN → CLAIMED → IN_PROGRESS → DONE | Add SPECIFIED and IN_REVIEW states |
| **BoardManager** | Post-based feed | Add discussion threads with resolution tracking |
| **MessageBus** | Fire-and-forget messages | Add discussion-type messages with response tracking |
| **CompletionDetector** | Checks task status | Also checks that all reviews are resolved |
| **Context delivery** | Full board + all predecessors | Curated per-task context from specs + relevant findings |

### What Changes in the Frontend

| Component | Current | Change |
|---|---|---|
| **BoardFeed** | Flat post list | Discussion threads with collapse/expand, decision highlighting |
| **ChatPanel** | Direct messaging | Discussion participation — coordinator questions appear here |
| **KanbanBacklog** | Status columns | Spec status indicators on cards |
| **WorkspaceHeader** | Status + budget | Active discussion count badge |
| **New: DiscussionView** | N/A | Thread view for each discussion (messages + decision) |

### Implementation Order

```
Step 1: DiscussionThread schema + discussion types
Step 2: Coordinator prompt rewrite — facilitator, not dispatcher
Step 3: Runtime loop — discussion-aware (pause for open discussions)
Step 4: Context curation — task-specific context packages
Step 5: Verification flow — auto-check + coordinator review + human discussion
Step 6: Project artifacts — PROJECT.md, PLAN.md, DECISIONS.md, STATE.md
Step 7: Frontend — discussion feed, thread view, spec status on kanban
Step 8: End-to-end test with real workspace
```

---

## What This Feels Like for the Human

### Before (Current)

```
System: "Workspace started. Coordinator decomposing goal..."
[... 2 minutes of silence ...]
System: "3 tasks created. Executing..."
[... 5 minutes of silence ...]
System: "All done. Here are your files."
```

The human has no idea what happened. They got output but didn't participate.

### After (Discussion-Driven)

```
Coordinator: "I've read your goal — researching AI protocols.
  Before I plan, quick questions:
  1. Should we focus on technical architecture or ecosystem adoption?
  2. Any specific protocols besides A2A and MCP?
  3. Who's the audience for the final report?"