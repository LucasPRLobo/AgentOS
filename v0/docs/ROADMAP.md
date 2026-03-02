# AgentOS Platform — Roadmap

> Long-term vision for evolving from an LLM pipeline builder into an agent orchestration platform.
> v0.0.1 is shipped. This document defines what comes next.

---

## Where We Are (v0.0.1 — Shipped)

An LLM pipeline builder: users create linear/DAG agent chains via a visual builder or templates, agents pass text to each other, results appear in the event log.

**What works:**
- Visual DAG workflow builder with 8 templates
- NL workflow generation ("describe your team")
- Multi-provider model layer (OpenAI, Anthropic, Ollama)
- 21 tools (file, web search, code execution, Google Workspace, Slack)
- Real-time event monitoring via WebSocket
- Agent output chaining between pipeline stages
- Settings, integrations, session history

**What's missing for a real orchestration tool:**
- Agents can't see each other's files — no shared workspace awareness
- No human checkpoints — workflows run start-to-finish unattended
- No iteration — agents can't revise based on feedback
- No structured tasks — agents get prompts, not deliverables
- Users can't access generated files from the UI
- No runtime variable input — templates use hardcoded defaults

**Unfinished v0.0.1 scope (tech debt):**
- Workspace artifact browser: lists files but can't view or download them (no API endpoint)
- Per-session cost display: token-to-cost calculation not implemented
- Context window manager: no token counting or auto-compression
- Data contract validation: schemas exist on edges but aren't enforced at runtime
- Agent detail panel: no per-agent conversation thread view (only flat event log)
- OllamaProvider lives in `labos/` instead of `agentos/lm/providers/` (architecture violation)

See `V0.0.1_SCOPE.md` delivery status addendum for the full accounting.

---

## The Vision

**AgentOS is a project manager for AI agents.** Users organize agents into teams, assign them specific tasks with clear deliverables, let them collaborate on a shared workspace, review their work at checkpoints, and iterate until the result is right.

Not a prompt chain. An orchestration layer where humans and AI agents collaborate on real work.

### Core Principles

1. **Task-oriented, not prompt-oriented** — Agents receive structured tasks (deliverable, acceptance criteria, inputs/outputs), not just text prompts.
2. **Shared workspace as ground truth** — All agents see the same files, data, and artifacts. The workspace is the collaboration surface.
3. **Human in the loop** — Users can review, approve, redirect, or contribute at any point. Agents work *with* humans, not in isolation.
4. **Iterative by default** — Review-revise loops are first-class. An agent can send work back for revision with specific feedback.
5. **Observable and controllable** — Users always see what's happening and can intervene. No black boxes.

---

## v0.0.2 — The Orchestration Release

### Phase A: Polish & v0.0.1 Debt

Fix the gaps that block basic usability. Includes unfinished v0.0.1 scope items.

**Workspace file access (v0.0.1 debt):**
- `GET /api/sessions/{id}/files` — list files in session workspace
- `GET /api/sessions/{id}/files/{path}` — download/preview a file
- Artifact browser upgrade: click a file → view contents (markdown rendered, code highlighted, images displayed)
- Download individual files or ZIP the whole workspace

**Per-session cost display (v0.0.1 debt):**
- Calculate cost from token usage × model pricing (data already in model registry)
- Display in session dashboard: total cost, per-agent breakdown
- Show estimated cost before running a workflow (based on template budget specs)

**Context window manager (v0.0.1 debt):**
- Token counting per model (tiktoken for OpenAI, approximate for others)
- Auto-compress predecessor output if it exceeds next agent's available context budget
- Priority-based prompt assembly: system prompt > tool schemas > upstream output > history

**Data contract enforcement (v0.0.1 debt):**
- Validate agent output against the edge's JSON Schema before passing to next agent
- On validation failure: retry agent with "your output didn't match the expected format" (up to 2 retries)
- Log validation results in the event log

**Runtime variable input:**
- When launching a workflow, prompt the user for variable values (topic, content_type, etc.)
- Pre-fill with defaults from the template
- Frontend: modal/form before workflow execution starts
- Variables injected into agent task descriptions at compile time

**Architecture fix:**
- Move `OllamaProvider` from `labos/` to `agentos/lm/providers/`
- Remove the `labos` import from the platform server

**Template hardening:**
- Apply "never ask for clarification" directives to all 8 templates
- Test each template end-to-end with GPT-4o-mini and GPT-5
- Ensure all templates produce usable output with default variables

---

### Phase B: Structured Tasks & Shared Workspace

Move from "prompt → run → text result" to "task → execute → deliverable."

**Structured task model:**

Each agent node gets a task definition, not just a prompt:

```
TaskDefinition:
  objective: str          # What to accomplish ("Write a detailed outline")
  deliverables: list[str] # Expected outputs ("outline.md saved to workspace")
  acceptance_criteria:     # When is this task "done"?
    - "Outline has at least 5 sections"
    - "Each section has 2+ key points"
    - "Total target word count is specified"
  inputs: dict            # What this agent receives from predecessors
  context_files: list     # Workspace files this agent should read first
```

The compiler translates this into a rich task description for the agent, including the structured deliverable expectations. Agents are instructed to self-check against acceptance criteria before finishing.

**Shared workspace awareness:**

Right now agents can use `file_read`/`file_write` but don't know what files exist. Add:

- Workspace manifest: auto-updated list of all files in the workspace with metadata (size, modified, created_by_agent)
- `workspace_status` tool: returns the current file list so agents know what's available
- Predecessor file context: when agent B depends on agent A, automatically include "Agent A produced these files: [outline.md (4.2KB)]" in B's task description
- Workspace change notifications in the event log: `FileCreated`, `FileModified` events

**Frontend workspace browser:**

Full workspace file browser in the session dashboard:
- Tree view of all files with metadata
- File preview: markdown rendered, code with syntax highlighting, images inline, CSV as table
- File diff: compare versions if a file was modified by multiple agents
- Download button per file + "Download All" ZIP

---

### Phase C: Human-in-the-Loop

Let users participate in the workflow, not just observe.

**Approval gates:**

Any edge in the DAG can be marked as "requires approval":

```
edges: [
  { source: "writer", target: "publisher", approval_required: true }
]
```

When the writer finishes:
1. Workflow pauses at that edge
2. User gets a notification (in-app, optional email/Slack)
3. User reviews the output (via workspace browser)
4. Actions: **Approve** (continue), **Reject + feedback** (re-run predecessor with notes), **Edit** (modify the output directly, then continue)

**User input nodes:**

A new node type: "Human Input" — a node that waits for user-provided content.

```
node: { type: "human_input", prompt: "Paste the meeting transcript here" }
```

The workflow pauses, the user provides input via the UI, and execution continues. This enables workflows like:
- Template collects user input → agents process it → human reviews → agents finalize

**Pause/resume:**

- Users can pause a running workflow at any point
- Paused workflows can be resumed later (state preserved in event log)
- Timeout handling: auto-pause if no user response within configurable window

**Session state transitions:**
```
CREATED → RUNNING → WAITING_FOR_INPUT → RUNNING → SUCCEEDED
                  → WAITING_FOR_APPROVAL → RUNNING → ...
                  → PAUSED → RUNNING → ...
```

---

### Phase D: Agent Collaboration & Iteration

Move beyond one-shot linear execution to real collaboration patterns.

**Review-revise loops:**

An agent can send work back to a predecessor with specific feedback:

```
edges: [
  { source: "writer", target: "reviewer" },
  { source: "reviewer", target: "writer", type: "feedback", max_iterations: 3 }
]
```

The reviewer can either approve (continue to next stage) or send feedback that triggers the writer to revise. The loop runs up to `max_iterations` times. This enables quality control without human intervention.

Implementation: the reviewer's "finish" action can include a `verdict` field:
```json
{"action": "finish", "verdict": "revise", "feedback": "Section 3 needs more data. Add statistics.", "result": "..."}
```

The compiler detects feedback edges and wires up the loop logic in the DAG executor.

**Conditional branching:**

Edges can have conditions based on predecessor output:

```
edges: [
  { source: "classifier", target: "technical_writer", condition: "output.category == 'technical'" },
  { source: "classifier", target: "marketing_writer", condition: "output.category == 'marketing'" }
]
```

Requires the classifier to produce structured output (JSON) that conditions can evaluate against.

**Parallel work with sync points:**

Already supported in the DAG (fan-out/fan-in), but needs better UX:
- Visual builder: easier parallel branch creation
- Sync node: waits for all parallel branches, merges their outputs
- Merge strategies: concatenate, summarize, pick best, human selects

**Direct agent-to-agent messaging:**

Agents can send targeted messages to each other outside the DAG edge flow:

- `AgentMessage` event type: `{from_agent, to_agent, topic, content}`
- Broadcast (to_agent = null) or directed messages
- Orchestrator routes messages between phases — agents see relevant messages in their context
- Use cases: "I found something relevant to your task", progress coordination, shared discoveries
- Message subscription model: agents declare which topics they listen to

**Agent-to-agent context:**

Beyond just passing the final result, agents can access:
- All workspace files (shared ground truth)
- Predecessor's event history (see what tools they used, what they tried)
- Structured metadata from predecessors (not just free text)

---

### Phase E: Project Management UX

The interface evolution from "pipeline monitor" to "project dashboard."

**Task board view:**

In addition to the DAG view, offer a Kanban-style task board:

```
┌─ Pending ──────┐ ┌─ In Progress ───┐ ┌─ Review ────────┐ ┌─ Done ──────────┐
│ [Editor]       │ │ [Drafter]       │ │ [Outline] ✓     │ │                 │
│                │ │  ██████░░ 60%   │ │  Awaiting human  │ │                 │
│                │ │  3/5 steps      │ │  approval        │ │                 │
└────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

Shows each agent as a card with progress, status, and quick actions.

**Session summary:**

After a session completes, generate a summary:
- What was accomplished
- Files produced (with links to preview)
- Total cost breakdown by agent and model
- Duration per agent
- Quality indicators (if review loops were used)

**Cost tracking:**

- Per-agent token usage and cost
- Per-model cost comparison within a session
- Historical cost trends across sessions
- Budget warnings: "This workflow typically costs $X"

**Agent test sandbox:**

Test individual agents in isolation before adding them to a workflow:
- Chat-with-agent UI: select a role template → open a standalone conversation
- Agent has access to its configured tools and workspace
- Useful for tuning system prompts, testing tool behavior, and validating role configs
- Results don't affect any session — purely exploratory
- Can save a tuned agent config back to the role template

**Workflow analytics:**

- Which templates are most used
- Average success rate per template
- Common failure points
- Model performance comparison (speed, cost, quality)

---

## v0.0.3 — The Intelligence Release

### Context Databases (Knowledge Base)

Users upload documents, data files, or notes → agents can search and query them during execution.

**Architecture:**
```
User uploads docs → chunking → embedding → vector store
                  → entity extraction → knowledge graph (optional)
                                    ↓
Agent gets "knowledge_search" tool → hybrid retrieval → relevant context
```

**Features:**
- Upload documents (PDF, markdown, text, CSV, JSON)
- Per-workspace or global knowledge bases
- `knowledge_search` tool available to any agent
- Automatic chunking and embedding (using configured model)
- Search results include source attribution
- Knowledge base management UI: upload, browse, delete, update

**Technology:** Vector search via SQLite + embeddings (lightweight, embedded). Optional Kuzu graph backend for relational queries (per IDEATION.md knowledge graph exploration).

### Agent Memory

Agents retain learnings across sessions.

- Key-value memory store: agents write facts they want to remember
- Memory injected into agent context at session start
- Users can view, edit, and delete agent memories
- Memory scoped per-role or per-workflow
- Follows the AriGraph episodic + semantic memory model (see IDEATION.md)

### Workflow Provenance

Track information lineage through the workflow:
- Every claim in the final output traces back to its source
- Click any statement → see the full chain (search result → agent → section → final doc)
- Derived from the event log — low cost, high value
- Compliance-friendly: full audit trail

---

## v0.0.4+ — Platform Growth

### Scheduled & Triggered Workflows
- Cron-style scheduling (daily/weekly/monthly)
- Webhook triggers (external events start workflows)
- Email triggers (new email matching rules → start workflow)
- File watcher triggers (new file in Drive → process it)

### Advanced Flow Control
- Sub-workflows (nest a workflow inside another as a single node)
- Dynamic agent spawning (workflow decides at runtime to create more agents)
- Map-reduce patterns (split work across N parallel agents, merge results)

### No-Code Tool Builder
- Point at any REST API → generate a tool definition
- Describe what the API does → system creates the Pydantic schema
- Test the tool in isolation before adding to workflows

### Collaboration & Sharing
- Team workspaces with role-based access
- Shareable session links (view-only monitoring)
- Session replay: step through past runs event by event
- Workflow export/import as JSON files

### Marketplace
- Publish and share workflows, templates, and custom tools
- Community ratings and usage metrics
- Free and premium listings

---

## Summary: Release Priorities

| Release | Theme | Key Features |
|---------|-------|-------------|
| **v0.0.1** (shipped) | Pipeline Builder | Visual builder, templates, NL creator, multi-provider, monitoring |
| **v0.0.2** | Orchestration | Structured tasks, shared workspace, human-in-loop, review loops, agent messaging, test sandbox, file viewer |
| **v0.0.3** | Intelligence | Context databases, agent memory, provenance tracking |
| **v0.0.4+** | Platform | Scheduling, triggers, advanced flow control, marketplace |

The biggest leap is v0.0.1 → v0.0.2. That's where we go from "chain of prompts" to "team of agents collaborating on real work with human oversight."

---

## Deployment Strategy

AgentOS is **local-first** today: the server and all agents run on the user's machine. This is intentional — it keeps the barrier to entry low, avoids cloud costs during development, and ensures full data privacy.

**Current (v0.0.1–v0.0.2):** Single-machine deployment. `python -m agentplatform` starts the API server, frontend served via Vite dev server or static build. All data stays local (SQLite event logs, local workspace directories).

**Future (v0.0.3+):** Evaluate cloud deployment when the product stabilizes:
- Containerized deployment (Docker Compose → single `docker compose up`)
- Optional hosted mode: API server in the cloud, agents run server-side
- Multi-user support requires auth, tenant isolation, and persistent storage migration
- LLM API keys managed per-user (never stored server-side in plaintext)

The local-first approach is not a limitation — it's a feature. Cloud is additive, not a replacement.

---

*This roadmap is a living document. Priorities may shift based on user feedback and testing.*
