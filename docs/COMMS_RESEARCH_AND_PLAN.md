# AgentOS — Communication System: Research, Design, and Implementation Plan

**Companion to:** WORKSPACE_VISION.md | COMMUNICATION_ARCHITECTURE.md | PROJECT_OVERVIEW.md
**Date:** March 2026
**Status:** Research complete. Implementation plan for Phase 1 (Board + Direct Messaging).
**Branch:** `feature/agent-comunitaion`

---

## Table of Contents

1. [Research: The Landscape](#1-research-the-landscape)
2. [The Hard Constraint](#2-the-hard-constraint)
3. [The Office Metaphor](#3-the-office-metaphor)
4. [Research Mapped to Metaphor](#4-research-mapped-to-metaphor)
5. [Design: The Board](#5-design-the-board)
6. [Design: Direct Messaging](#6-design-direct-messaging)
7. [Implementation Plan: Phase 1](#7-implementation-plan-phase-1)

---

## 1. Research: The Landscape

### 1.1 Protocols and Standards

#### Google A2A (Agent-to-Agent Protocol)

- **Released:** April 2025, now v0.3 under Linux Foundation (Apache 2.0)
- **What it solves:** Agents built on different frameworks discover each other and collaborate via a standard wire protocol.
- **Architecture:** JSON-RPC 2.0 over HTTPS. Three layers: data model (Protocol Buffers), abstract operations, concrete bindings (JSON-RPC, gRPC, HTTP/REST).
- **Discovery:** Agent Cards at `/.well-known/agent.json` — identity, capabilities, skills, auth requirements.
- **Task lifecycle:** `submitted → working → input-required → completed / failed / canceled / rejected`. Tasks carry messages with roles ("user" or "agent") and typed Parts (text, file, structured data).
- **Streaming:** SSE-based `SendStreamingMessage` with `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`.
- **Threading:** `contextId` groups messages into conversations. `taskId` identifies individual requests.
- **Auth:** API keys, OAuth2, OpenID Connect, mutual TLS — declared in Agent Cards.
- **Relevance to AgentOS:** A2A defines agent-to-agent communication at the network level. AgentOS operates at the same-machine level today, but A2A's task lifecycle, Agent Card discovery, and message structure are worth adopting conceptually.

#### Anthropic MCP (Model Context Protocol)

- **Released:** November 2024 (97M+ monthly SDK downloads)
- **What it solves:** Standardizes how agents connect to tools, data sources, and services. "USB-C for AI."
- **Architecture:** JSON-RPC 2.0 over stdio or SSE/HTTP. Servers expose `tools`, `resources`, and `prompts`.
- **Agent communication:** MCP is agent-to-tool, not agent-to-agent. However, agents CAN be wrapped as MCP tool servers, allowing one agent to "call" another as a tool. This lacks the rich task lifecycle of A2A.
- **Relevance to AgentOS:** MCP is already used for Tier 2 adapter tool extension. An AgentOS Communication MCP Server could expose messaging tools (`check_team_messages`, `send_team_message`) to agents that run as subprocesses.

#### FIPA ACL (Foundation for Intelligent Physical Agents)

- **Released:** Early 2000s (IEEE standard)
- **What it solves:** Formal specification for agent communication using speech acts (communicative intentions).
- **Speech acts (performatives):** `inform`, `request`, `agree`, `refuse`, `propose`, `accept-proposal`, `reject-proposal`, `cfp` (call for proposals), `confirm`, `disconfirm`, `query`, `subscribe`.
- **Message fields:** `performative`, `sender`, `receiver`, `content`, `language`, `ontology`, `protocol`, `conversation-id`, `reply-with`, `in-reply-to`, `reply-by`.
- **Interaction protocols:** Contract Net (task delegation via bidding), Request (ask + respond), Query (question + answer), Propose (suggest + accept/reject).
- **Relevance to AgentOS:** FIPA's speech acts map directly to how office workers communicate. The `conversation-id`, `reply-with`, `in-reply-to` fields are exactly what we need for message threading. The interaction protocols formalize common patterns (delegation, consultation, review). These concepts are 25 years old but being reinvented by every modern framework — we should adopt them explicitly.

#### Agentic AI Foundation (AAIF)

- **Formed:** December 2025 under Linux Foundation
- **Members:** AWS, Anthropic, Block, Bloomberg, Cloudflare, Google, Microsoft, OpenAI
- **Projects:** MCP (Anthropic), Goose (Block), AGENTS.md (OpenAI)
- **Relevance:** The industry is converging on A2A for agent-to-agent and MCP for agent-to-tool. AgentOS should align with these standards where possible.

### 1.2 Frameworks and Implementations

#### OpenAI Agents SDK (successor to Swarm)

- **Communication:** Handoffs as tool calls. `transfer_to_<agent>` tools are auto-generated. Agent-as-tool pattern for bounded subtasks.
- **State:** Full conversation history passed on handoff. `HandoffInputData` carries `input_history`, `pre_handoff_items`, `new_items`. Input filters can prune history.
- **Execution:** Single-threaded within a `run()` call. Supports `asyncio.gather` for parallel code-orchestrated patterns.
- **Human integration:** None built-in. Human must write code to intercept.
- **Limitation:** One agent active at a time. No persistent message bus. No peer-to-peer negotiation.

#### Microsoft AutoGen v0.4

- **Communication:** Publish-subscribe event system with topic-based routing. Three message types: `GroupChatMessage`, `RequestToSpeak`, topic subscriptions.
- **Execution:** Event-driven but sequential. `SingleThreadedAgentRuntime`. GroupChatManager uses LLM to select next speaker (excluding last speaker to prevent domination).
- **State:** Each agent maintains own `List[LLMMessage]`. Shared topic means all agents see all messages.
- **Human integration:** `UserProxyAgent` — human types in terminal. Blocks entire execution.
- **Limitation:** Sequential despite event-driven infrastructure. Speaker selection via LLM adds cost per turn.

#### CrewAI

- **Communication:** Delegation as tool call (`Delegate work to coworker`). `allowed_agents` parameter restricts delegation targets.
- **Execution:** Sequential or hierarchical. Manager decomposes and delegates.
- **State:** Task outputs flow as context between agents. No shared memory.
- **Human integration:** `human_input=True` on tasks. Blocks and waits for terminal input.
- **Limitation:** No peer-to-peer. Delegation is strictly hierarchical.

#### LangGraph

- **Communication:** Shared state graph. Agents are nodes; they communicate by reading/writing a shared `TypedDict` or Pydantic model. No direct message passing.
- **Execution:** Graph traversal with "super-steps" (Pregel-inspired). Supports parallel fan-out via `asyncio.gather`.
- **State:** Immutable updates (copy-on-write). Reducer functions handle merge conflicts. Checkpointing for pause/resume and time-travel debugging.
- **Human integration:** "Human-in-the-loop" interrupts. Pauses graph, resumes on API call. Closest to useful among competitors.
- **Limitation:** Graph defined statically at compile time. State object must fit in memory.

#### Google ADK (Agent Development Kit)

- **Communication:** Yield-based coroutine pattern. Agents yield `Event` objects to a `Runner`, which processes them, commits state, and resumes the agent.
- **Execution:** Cooperative, async-first. Agent yields → Runner processes → Agent resumes. State changes only guaranteed persistent after yield.
- **State:** `InvocationContext` with `state_delta` and `artifact_delta`. `temp:` prefixed variables scoped to single invocation.
- **Streaming:** Partial events (`partial=True`) forwarded to UI, skip action processing. Final events trigger full commits.
- **Relevance to AgentOS:** The yield/resume model maps directly to our Tier 1 tool-call boundaries. The Runner injecting state at yield points is exactly the "glancing at the board" mechanism.

#### Claude Code Agent Teams

- **Communication:** File-based mailbox at `~/.claude/teams/{name}/messages/{session-id}/`. `write()` for direct, `broadcast()` for team-wide.
- **Execution:** Each teammate is an independent Claude Code process with own context window and optional Git worktree. Lead spawns teammates.
- **Task coordination:** Shared task list at `~/.claude/tasks/{name}/`. Task claiming via file locking. 5-minute heartbeat timeout releases abandoned tasks.
- **Context:** Teammates load project context (CLAUDE.md, MCP servers, skills) but NOT the lead's conversation history.
- **Human integration:** Lead agent IS the human. Human is orchestrator, not team member.
- **Limitation:** Experimental. No nested teams. One team per session. No governance or audit trail.

#### Blackboard Pattern (LbMAS Research, arxiv 2507.01701)

- **Communication:** Shared write-space. Control unit posts requests. Agents autonomously decide whether to contribute based on capabilities.
- **Specialized agents:** Conflict resolution agent detects contradictions and triggers focused discussions. Cleaning agent removes redundant messages.
- **Results:** 4-5% accuracy improvement over chain-of-thought baselines on MMLU and GPQA while consuming fewer tokens.
- **Relevance to AgentOS:** This IS the Board concept. Agents contribute to a shared space, conflicts are detected, stale content is cleaned. The most direct mapping to the office metaphor.

#### MCP Agent Mail

- **Communication:** HTTP + Git-backed file storage + SQLite FTS5. Tools: `send_message`, `fetch_inbox`, `acknowledge_message`. Resources: `resource://inbox/{Agent}`, `resource://thread/{id}`.
- **Persistence:** Dual model — Git for human-auditable canonical storage (`messages/YYYY/MM/id.md` with YAML frontmatter), SQLite FTS5 for querying.
- **Execution:** Pull-based. Agents call `fetch_inbox()` when activated.
- **Relevance:** The Git-backed persistence with human-readable markdown messages is an interesting pattern for audit trail.

### 1.3 Coordination Patterns Summary

| Pattern | Used By | How It Works | Agents + Humans? |
|---------|---------|--------------|------------------|
| **Handoff (tool call)** | OpenAI, CrewAI | Agent calls `transfer_to_X`, control passes | No human integration |
| **Shared state** | LangGraph | All agents read/write typed state object | Human-in-the-loop interrupt |
| **Pub-sub topics** | AutoGen | Agents publish/subscribe, manager selects speaker | Human as terminal input |
| **File mailbox** | Claude Code Teams | Messages in filesystem, file-lock task claiming | Human IS the lead agent |
| **HTTP/JSON-RPC** | Google A2A | Agents as HTTP servers, SSE streaming | `input-required` task state |
| **Yield/resume** | Google ADK | Agent yields events, Runner injects state at resume | Partial event streaming to UI |
| **Blackboard** | LbMAS research | Shared write-space, autonomous contribution | Not addressed |
| **Speech acts** | FIPA ACL | Typed performatives with interaction protocols | Not addressed |

### 1.4 Key Findings

1. **Agent-to-agent communication is well-solved** at the infrastructure level. Multiple working patterns exist. The choice is about which tradeoffs to accept.

2. **Agent-to-human communication is poorly solved everywhere.** Every framework treats humans as either terminal-sitters (AutoGen, CrewAI), checkpoint approvers (LangGraph, AgentOS gates), or the orchestrator (Claude Code Teams). Nobody treats humans as continuous team participants.

3. **Agent awareness ("noticing") is unsolved.** Every framework either ignores it or defers it to turn/activation boundaries. No framework provides true real-time awareness because LLMs fundamentally cannot listen.

4. **FIPA ACL's speech acts are being reinvented** by every modern framework without credit. The vocabulary (inform, request, propose, accept, reject) and threading model (conversation-id, reply-to) are exactly what's needed.

5. **The blackboard pattern is the most promising for shared awareness.** Recent research shows it improves accuracy while reducing token consumption — the opposite of what you'd expect from adding a communication layer.

6. **Google ADK's yield/resume is the right execution model** for injecting awareness. It maps directly to Tier 1 tool-call boundaries and Tier 2 session-turn boundaries.

---

## 2. The Hard Constraint

LLMs are request-response systems. They cannot listen, notice, or maintain event loops. This constraint shapes everything.

### What We Control

| Adapter Tier | Execution Loop | Injection Points | Awareness Latency |
|---|---|---|---|
| **Tier 1** (API) | AgentOS controls tool-calling loop | Between every tool call | Seconds |
| **Tier 2** (Claude Code subprocess) | Claude Code controls its own loop | None mid-execution | Task completion only |
| **Tier 2** (Claude Code SDK sessions) | AgentOS controls session turns | Between session turns | Minutes |
| **Tier 2** (Claude Code + MCP tool) | Agent chooses to call tool | When agent decides to check | Unreliable |

### Three Awareness Strategies

1. **Injection (guaranteed):** Framework pushes messages/state at controlled boundaries. Works for Tier 1 (every tool call) and SDK-based Tier 2 (every turn). Primary channel.

2. **Polling (best-effort):** Agent checks an inbox via MCP tool or file read. Works for any tier but unreliable — agent may not check. Supplement only.

3. **Environmental (passive):** Information written to workspace files. Agent discovers it during normal work. Works for non-urgent context. No delivery guarantee.

### Honest Tier Assessment

- **Tier 1 agents can fully participate in real-time communication.** Injection at every tool call = seconds of latency. This is where we prototype.
- **Tier 2 agents have limited participation today.** MCP polling is unreliable. SDK session migration enables turn-based communication but is a larger effort.
- **The Board concept works for both tiers** because it's injected/read at activation, not mid-execution. An agent starting a task or a new turn gets the board state regardless of tier.

---

## 3. The Office Metaphor

We use an office metaphor to reason about the communication system design. This is not a visual — it's an architectural mapping.

### The Room

A shared workspace where all team members (agents and humans) work on the same project. The room has boundaries — you must be invited to enter (workspace scope, workflow_id, permissions). Everyone in the room is part of the same project.

**Maps to:** Workspace + workflow scope. Already exists.

### The Desks

Each worker has their own desk — their private working context. The papers on their desk (current task, notes, drafts) are private by default. Others see only what is shared explicitly.

**Maps to:** Agent context windows (system prompt, task description, conversation history, tool results). For humans, their screen/dashboard. Already exists.

### The Board

A shared display visible from every desk. Key properties:
- **Always visible** — everyone can glance at it without receiving a message
- **Anyone can post** — agents, humans, or the system
- **Persistent** — posts stay up until removed or archived
- **Structured** — organized sections (announcements, status, decisions, alerts), not random text
- **Passive awareness** — you don't need to be "sent" the board; you see it by looking up

The board is NOT a message. It's a continuously maintained state that gets included in every agent's context at activation/turn boundaries. Humans see it as a dashboard panel in real-time.

**Maps to:** Board State Manager (new component) + Ambient Context Injector. Does not exist yet.

### Direct Chat

Two workers turn to each other and talk privately. Nobody else hears. The conversation is a back-and-forth exchange with threading (replies linked to original messages).

Properties:
- **Point-to-point** — between any two participants (agent↔agent, agent↔human, human↔human)
- **Asynchronous but fast** — message queued, delivered at next boundary (seconds for Tier 1)
- **Threaded** — replies link to original messages, forming conversations
- **Private by default** — only participants see the conversation

**Maps to:** Message Bus with per-participant inboxes and threading. Based on Claude Code Teams mailbox pattern + FIPA threading. Does not exist yet.

### Posting to the Board

A worker has a private conversation, then decides the team should see the conclusion. They walk to the board and pin a summary. This is **visibility promotion** — a private exchange or finding gets elevated to team-wide awareness.

Three triggers for board posts:
- **Explicit:** Agent or human manually posts ("the team should know this")
- **Automatic:** System detects significant events (task completed, finding discovered, decision made)
- **Curated:** Manager/coordinator pins or removes items

**Maps to:** Board post API with promotion from direct messages. Does not exist yet.

### Subgroup Conversations

Three workers pull chairs together for a focused discussion. Others see they're meeting (metadata visible) but don't hear details (content private to subgroup).

**Maps to:** Channels with membership — extends existing ChannelRouter. Channel existence and activity visible on board as metadata.

### The Manager

A privileged human who can:
- See everything (all desks, all chats, the board)
- Direct anyone (high-priority directive messages)
- Post announcements (board pins)
- Override decisions
- Approve/reject work (existing gate system)

**Maps to:** Human participant with elevated capabilities. Dashboard with full visibility. Directive message type with priority injection.

### Ambient Awareness

In a real office, you passively absorb information without explicit communication:
- You hear the general buzz (team is busy vs quiet)
- You see body language (someone is stuck)
- You glance at the board (team state changes)
- You overhear relevant snippets (adjacent conversations)

This ambient awareness is what makes real teamwork fluid. It translates to a compact, always-present summary injected into every agent's context at every turn/tool boundary:

```
[BOARD — last updated 30s ago]
 Manager pinned: "Focus on Germany, not all EU" (2 min ago)
 Research Agent: working on ECB rate analysis (70% complete)
 Analysis Agent: waiting for research data (idle 3 min)
 Board post from Research: "Found conflicting GDP data — using IMF for developed markets"
 Budget: 45% consumed, 1.5 hours elapsed
 Alert: Analysis Agent's predecessor data may be outdated (Research found new ECB policy)
```

~150 tokens. Injected automatically. The agent doesn't ask for it — it's in their field of vision.

---

## 4. Research Mapped to Metaphor

### FIPA ACL → The Language People Speak in the Office

In a real office, every utterance is a speech act with an intent:

| Office Action | FIPA Performative | System Message Type |
|---|---|---|
| "The ECB changed rates" | `inform` | `inform` |
| "Can you check the GDP data?" | `request` | `request` |
| "I think we should use IMF data" | `propose` | `propose` |
| "Agreed, let's go with IMF" | `accept-proposal` | `accept` |
| "No, World Bank is more current" | `reject-proposal` | `reject` |
| "I can't do this alone, help?" | `cfp` (call for proposals) | `request_help` |
| "I'll take that" | `agree` | `claim` |
| "Focus on Germany only" (manager) | N/A — authority act | `directive` |
| "Budget at 80%" (system) | `inform` — system alert | `alert` |

FIPA's threading fields (`conversation-id`, `reply-with`, `in-reply-to`) map directly to our message threading needs.

FIPA's interaction protocols map to common office patterns:
- **Contract Net** → Task delegation: manager posts task, agents bid, best agent wins
- **Request** → Direct ask: "can you do X?" → "yes/no"
- **Query** → Information request: "what did you find about Y?" → structured answer
- **Propose** → Suggestion: "I think we should Z" → accept/reject with rationale

### Blackboard (LbMAS) → The Board

The research blackboard maps directly to the office board:

| Blackboard Concept | Office Board Element |
|---|---|
| Control unit posts work requests | Manager posts tasks/questions to board |
| Agents autonomously decide to contribute | Workers see something relevant, add their input |
| Conflict resolution agent | System detects contradictions between posts |
| Cleaning agent | System archives stale/redundant posts |
| Shared write-space | The board itself |

Key insight from research: agents contribute based on capability matching, not explicit assignment. The board enables emergent collaboration — someone sees a question they can answer and answers it.

### Google ADK Yield/Resume → "Looking Up from the Desk"

Every time an agent pauses (tool call, turn boundary), it's like a worker pausing to grab a file and glancing at the board:

| ADK Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| Agent yields Event | Worker pauses to do something | Tool call / turn boundary |
| Runner processes event | Action gets done (file read, API call) | Tool execution |
| Runner injects state at resume | Worker glances at board while paused | Board state injection |
| Agent resumes with updated context | Worker continues with new awareness | Next LLM call includes board |

Tier mapping:
- Tier 1 = worker facing the board (glances every few seconds at tool boundaries)
- Tier 2 SDK = worker checking the board between tasks (glances every few minutes at turn boundaries)
- Tier 2 subprocess = worker with headphones on (only sees board when they finish and look up)

### A2A Agent Cards → Name Plates on Desks

| A2A Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| Agent Card | Name plate + role description on desk | Agent config with role, capabilities, tools |
| `/.well-known/agent.json` | Visible from anywhere in the room | Board section: team roster |
| Skills/capabilities declaration | "Ask me about European markets" | Agent specialization tracker |
| Status (working/idle) | Whether the person is at their desk | Agent state (RUNNING/PENDING/WAITING) |

When an agent needs help ("I need someone who can validate financial data"), the system matches against agent cards. The board displays the team roster.

### AutoGen GroupChatManager → The Meeting Facilitator

When a subgroup has a discussion, a facilitator manages turn-taking:

| AutoGen Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| GroupChatManager | Meeting facilitator | Channel coordinator (optional per channel) |
| LLM-based speaker selection | "Analysis Agent, your thoughts?" | Coordinator selects next speaker |
| Excluding last speaker | "Let someone else talk" | Anti-domination rule |
| Termination detection | "Are we done here?" | Consensus/resolution detection |

Not every conversation needs facilitation. Two agents chatting directly is fine. Facilitation is for 4+ participant channels.

### OpenAI Handoffs → Walking Work to Someone's Desk

| OpenAI Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| `transfer_to_X` tool | Walk the task to someone's desk | Spontaneous handoff (not in original DAG) |
| Full history passed | "Here's everything I've done so far" | TaskOutput + conversation context |
| Agent-as-tool | "Hey, quick question for the expert" | Consultation (already exists) |

The new piece: handoffs can happen spontaneously (agent decides mid-task), creating new tasks via mutable DAG.

### LangGraph Shared State → The Shared Filing Cabinet

| LangGraph Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| Shared TypedDict | Filing cabinet with labeled sections | Typed project state document |
| Reducer functions | Filing policy (how to merge concurrent updates) | Merge semantics for state fields |
| Checkpointing | Snapshot of the cabinet at a point in time | Event log replay (already exists) |
| Time-travel debugging | "What was in the cabinet at 3pm?" | Replayer (already exists) |

### Claude Code Teams Mailbox → Physical Inbox on Each Desk

| CC Teams Concept | Office Metaphor | AgentOS Mapping |
|---|---|---|
| `~/.claude/teams/{name}/messages/` | Inbox tray on each desk | Per-participant inbox in MessageBus |
| `write()` | Drop a note in someone's inbox | `send()` direct message |
| `broadcast()` | Post to team channel | `broadcast()` to channel |
| File-lock task claiming | Put your name on a task | Work claiming via message bus |
| Heartbeat timeout | Reassign if worker is gone | Stale task detection (already exists) |

### MCP → Tools on the Desk

MCP is not about communication. It's the phone, printer, database terminal on each desk. But we add one MCP tool: a **walkie-talkie** — `check_team_messages`, `send_team_message`, `get_board_state`. This lets Tier 2 subprocess agents participate in communication even without injection.

### Synthesis: Components from Research

| Office Element | Primary Source | Secondary Source | New Component |
|---|---|---|---|
| **The Board** | Blackboard (LbMAS) | LangGraph shared state | `BoardManager` |
| **Board language** | FIPA speech acts | A2A message Parts | Message type vocabulary |
| **Board injection** | Google ADK yield/resume | Tier 1 tool loop | `AmbientContextInjector` |
| **Name plates** | A2A Agent Cards | Specialization tracker | Board team roster section |
| **Direct chat** | CC Teams mailbox | FIPA threading | `MessageBus` |
| **Subgroup meetings** | AutoGen GroupChatManager | Existing ChannelRouter | Extended channels |
| **Spontaneous handoffs** | OpenAI handoffs | Mutable DAG | Dynamic task creation |
| **Shared filing** | LangGraph shared state | Workspace file tracking | Typed project state |
| **Communication tools** | MCP | MCP Agent Mail | `AgentOSCommsMCP` server |
| **Office archive** | Event log | MCP Agent Mail (Git) | All messages as events |
| **Manager view** | Dashboard backend | A2A agent status | Full-visibility dashboard |

---

## 5. Design: The Board

### 5.1 What the Board Contains

The board is a structured, living document with defined sections:

```
Board
├── Announcements          # Pinned by manager or system. High visibility.
│   └── "Focus on Germany, not all EU" (pinned by Manager, 14:32)
│
├── Team Status            # Auto-generated from agent states.
│   ├── Research Agent: RUNNING — ECB rate analysis (70%)
│   ├── Analysis Agent: WAITING — blocked on research data
│   └── Writer Agent: PENDING — not yet started
│
├── Recent Posts           # Posted by agents or humans. Newest first.
│   ├── [Research, 14:28, inform] "Found conflicting GDP data — using IMF for developed markets"
│   ├── [Analysis, 14:25, request] "Need clarification on time horizon for projections"
│   └── [System, 14:20, alert] "Budget at 45%, 1.5 hours elapsed"
│
├── Key Decisions          # Extracted from resolved discussions.
│   └── "Use IMF for developed markets, World Bank for emerging" (decided 14:30)
│
├── Open Questions         # Unresolved items needing attention.
│   └── "Time horizon for projections — 1yr or 5yr?" (asked by Analysis, 14:25)
│
└── Alerts                 # System-generated warnings.
    └── "Analysis Agent's predecessor data may be outdated" (14:29)
```

### 5.2 Board State Schema

```python
class BoardPost(BaseModel):
    """A single post on the board."""
    post_id: str                                        # UUID
    section: Literal["announcement", "status", "post",
                      "decision", "question", "alert"]
    author_type: Literal["agent", "human", "system"]
    author_id: str
    content: str                                        # Natural language
    speech_act: Literal["inform", "request", "propose",
                         "accept", "reject", "alert",
                         "directive", "status"] = "inform"
    structured_data: dict | None = None                 # Optional payload
    pinned: bool = False
    resolved: bool = False                              # For questions/proposals
    resolved_by: str | None = None
    timestamp: str                                      # ISO datetime
    expires_at: str | None = None                       # Auto-archive after this time
    source_message_id: str | None = None                # If promoted from direct message
    source_thread_id: str | None = None                 # If promoted from thread

class AgentStatus(BaseModel):
    """Status of an agent on the board roster."""
    agent_id: str
    agent_name: str
    role: str
    state: Literal["running", "waiting", "pending",
                    "succeeded", "failed", "idle"]
    current_task: str | None = None
    progress_summary: str | None = None                 # e.g., "70% complete"
    last_active: str                                    # ISO datetime

class BoardState(BaseModel):
    """Complete board state at a point in time."""
    workflow_id: str
    version: int                                        # Increments on every change
    announcements: list[BoardPost] = []
    team_status: list[AgentStatus] = []
    recent_posts: list[BoardPost] = []                  # Newest first, max 20
    decisions: list[BoardPost] = []
    open_questions: list[BoardPost] = []
    alerts: list[BoardPost] = []
    last_updated: str                                   # ISO datetime
```

### 5.3 Board Manager (Kernel Component)

```python
class BoardManager:
    """Maintains the shared board state for a workspace.

    Responsibilities:
    - Accept posts from agents, humans, and system
    - Auto-generate team status from agent states
    - Auto-generate alerts from budget/error events
    - Archive stale posts (conflict with decisions, expired)
    - Render compact summaries for agent injection
    - Render full state for human dashboard
    - Log all board changes as events
    """

    def __init__(self, event_log, seq, workflow_id, agents): ...

    # --- Posting ---
    def post(self, post: BoardPost) -> str: ...
    def pin(self, post_id: str) -> None: ...
    def unpin(self, post_id: str) -> None: ...
    def resolve(self, post_id: str, resolved_by: str) -> None: ...
    def archive(self, post_id: str) -> None: ...

    # --- Promotion (from direct message to board) ---
    def promote(self, message_id: str, section: str) -> str: ...

    # --- Auto-updates ---
    def update_agent_status(self, agent_id: str, status: AgentStatus) -> None: ...
    def add_system_alert(self, content: str, structured_data: dict = None) -> str: ...

    # --- Reading ---
    def get_state(self) -> BoardState: ...
    def render_compact(self, max_tokens: int = 200) -> str: ...
    def render_full(self) -> dict: ...

    # --- Maintenance ---
    def cleanup_expired(self) -> int: ...
    def cleanup_resolved(self, older_than_minutes: int = 30) -> int: ...
```

### 5.4 Ambient Context Injector

The injector formats board state for inclusion in agent context:

```python
class AmbientContextInjector:
    """Formats board state for injection into agent context at turn/tool boundaries.

    Design principles:
    - Compact: ~100-200 tokens max
    - Structured: consistent format agents learn to parse
    - Prioritized: critical items first, low-priority items omitted if over budget
    - Differential: can show "what changed since last injection" to reduce redundancy
    """

    def __init__(self, board_manager: BoardManager): ...

    def render_for_agent(self, agent_id: str,
                          last_seen_version: int | None = None,
                          token_budget: int = 200) -> str | None:
        """Render board state for injection into an agent's context.

        Returns None if nothing has changed since last_seen_version.
        Prioritizes: pinned announcements > alerts > messages for this agent >
                     recent posts > status changes.
        """
        ...
```

### 5.5 Board Event Types

New event types for the board:

```python
# In EventType enum:
BOARD_POST_CREATED = "board.post_created"
BOARD_POST_PINNED = "board.post_pinned"
BOARD_POST_RESOLVED = "board.post_resolved"
BOARD_POST_ARCHIVED = "board.post_archived"
BOARD_POST_PROMOTED = "board.post_promoted"      # From direct message
BOARD_STATE_INJECTED = "board.state_injected"    # Logged when agent receives board
```

---

## 6. Design: Direct Messaging

### 6.1 Message Schema

Based on FIPA ACL threading + Claude Code Teams mailbox pattern:

```python
class SpeechAct(StrEnum):
    """Communication intent, based on FIPA ACL performatives."""
    INFORM = "inform"               # Sharing a fact, no response expected
    REQUEST = "request"             # Asking for action/information, response expected
    PROPOSE = "propose"             # Suggesting a direction, accept/reject expected
    ACCEPT = "accept"               # Accepting a proposal/request
    REJECT = "reject"               # Rejecting with rationale
    CONFIRM = "confirm"             # Confirming a previous inform
    ALERT = "alert"                 # System warning
    DIRECTIVE = "directive"         # Human authority instruction, must follow
    STATUS = "status"               # Progress update

class MessagePriority(StrEnum):
    LOW = "low"                     # Batch-deliverable, not time-sensitive
    NORMAL = "normal"               # Deliver at next boundary
    HIGH = "high"                   # Deliver at next boundary, highlight
    CRITICAL = "critical"           # Deliver immediately, may interrupt

class DirectMessage(BaseModel):
    """A message between participants in the workspace."""
    message_id: str                                 # UUID
    thread_id: str | None = None                    # Conversation thread
    reply_to: str | None = None                     # FIPA in-reply-to
    reply_by: str | None = None                     # FIPA reply-by (deadline)

    # Addressing
    sender_type: Literal["agent", "human", "system"]
    sender_id: str
    recipient_type: Literal["agent", "human"]
    recipient_id: str

    # Content
    content: str                                    # Natural language
    speech_act: SpeechAct = SpeechAct.INFORM
    structured_data: dict | None = None             # Optional typed payload
    attachments: list[str] | None = None            # Workspace file paths

    # Metadata
    priority: MessagePriority = MessagePriority.NORMAL
    workflow_id: str
    timestamp: str                                  # ISO datetime

    # Delivery tracking
    delivered: bool = False
    delivered_at: str | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None
```

### 6.2 Message Bus (Kernel Component)

```python
class MessageBus:
    """Central message routing for workspace communication.

    Handles direct messages between any participants (agent↔agent,
    agent↔human, human↔agent). All messages are logged as events.

    Extends (does not replace) the existing ChannelRouter, which
    continues to handle broadcast/queue channel patterns.
    """

    def __init__(self, event_log, seq, workflow_id): ...

    # --- Sending ---
    def send(self, message: DirectMessage) -> str:
        """Send a direct message. Returns message_id. Logs MESSAGE_SENT event."""
        ...

    def reply(self, reply_to_id: str, content: str,
              speech_act: SpeechAct = SpeechAct.INFORM,
              **kwargs) -> str:
        """Reply to a message. Auto-sets thread_id and reply_to."""
        ...

    # --- Receiving ---
    def receive(self, recipient_id: str,
                priority_min: MessagePriority = MessagePriority.LOW,
                mark_delivered: bool = True) -> list[DirectMessage]:
        """Get pending messages for a recipient. Marks as delivered."""
        ...

    def get_pending_count(self, recipient_id: str) -> int:
        """Cheap check: how many undelivered messages? (No content loaded.)"""
        ...

    # --- Threading ---
    def get_thread(self, thread_id: str) -> list[DirectMessage]:
        """Get all messages in a conversation thread, ordered by timestamp."""
        ...

    # --- Board promotion ---
    def promote_to_board(self, message_id: str,
                          board_manager: BoardManager,
                          section: str = "post") -> str:
        """Promote a direct message to a board post. Returns post_id."""
        ...

    # --- Acknowledgment ---
    def acknowledge(self, message_id: str) -> None:
        """Mark a message as acknowledged by recipient."""
        ...

    # --- Governance ---
    def get_conversation_log(self, participant_id: str) -> list[DirectMessage]:
        """Full message history for a participant (for audit)."""
        ...
```

### 6.3 Message Event Types

```python
# Extending EventType enum (MESSAGE_SENT and MESSAGE_RECEIVED already exist):
DIRECT_MESSAGE_SENT = "direct_message.sent"
DIRECT_MESSAGE_DELIVERED = "direct_message.delivered"
DIRECT_MESSAGE_ACKNOWLEDGED = "direct_message.acknowledged"
THREAD_CREATED = "thread.created"
MESSAGE_PROMOTED_TO_BOARD = "message.promoted_to_board"
```

### 6.4 Tier 1 Integration: Message-Aware Loop

The Tier 1 adapter loop is refactored to check for messages and board updates at each tool-call boundary:

```python
# Pseudocode — modified Tier 1 execute_task loop
for _ in range(MAX_ITERATIONS):
    if self._terminated:
        break

    # === AMBIENT AWARENESS: Inject board state if changed ===
    if ambient_injector is not None:
        board_update = ambient_injector.render_for_agent(
            agent_id=self._agent_id,
            last_seen_version=self._last_board_version,
            token_budget=200,
        )
        if board_update is not None:
            messages.append({"role": "user", "content": board_update})
            self._last_board_version = board_manager.get_state().version

    # === DIRECT MESSAGES: Check inbox ===
    if message_bus is not None:
        pending = message_bus.receive(self._agent_id)
        if pending:
            injection = format_message_injection(pending)
            messages.append({"role": "user", "content": injection})

    # === STANDARD LOOP: LLM call, tool execution ===
    response = self._client.messages.create(
        model=self._model, max_tokens=4096,
        system=system, messages=messages, tools=tools,
    )
    # ... budget tracking, tool execution, etc. (unchanged)
```

### 6.5 Tier 2 Integration: Workspace Files + MCP Tool

For current Tier 2 subprocess agents (before SDK migration):

**Workspace files** updated before agent launch and readable during execution:
```
workspace/
├── .agentos/
│   ├── board.md              # Current board state, human-readable
│   ├── inbox/                # Pending messages as markdown files
│   │   ├── msg-001.md        # "From: Research Agent [request] ..."
│   │   └── msg-002.md        # "From: Manager [directive] ..."
│   └── outbox/               # Agent drops messages here, system routes them
│       └── (agent writes files here to send messages)
```

**System prompt addition** (via `--append-system-prompt`):
```
TEAM COMMUNICATION: You are part of a collaborative workspace.
- Before starting, read .agentos/board.md for team context and announcements.
- Check .agentos/inbox/ for direct messages from teammates.
- To send a message, write a JSON file to .agentos/outbox/ with format:
  {"to": "agent_name or human", "content": "your message", "speech_act": "inform|request|propose"}
- After completing major steps, re-read the board and inbox for updates.
```

**MCP Communication Tool** (for agents with MCP support):
```python
# Tools exposed by AgentOS Communication MCP Server
tools = [
    {
        "name": "read_board",
        "description": "Read the current workspace board — announcements, team status, recent posts, decisions, open questions, and alerts.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "post_to_board",
        "description": "Post a message to the workspace board visible to all team members.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "section": {"type": "string", "enum": ["post", "question", "decision"]},
                "speech_act": {"type": "string", "enum": ["inform", "request", "propose"]}
            },
            "required": ["content"]
        }
    },
    {
        "name": "check_messages",
        "description": "Check for direct messages from team members and the human manager.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "send_message",
        "description": "Send a direct message to a specific team member or the human manager.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient name or 'human'"},
                "content": {"type": "string"},
                "speech_act": {"type": "string", "enum": ["inform", "request", "propose"], "default": "inform"},
                "priority": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}
            },
            "required": ["to", "content"]
        }
    },
]
```

---

## 7. Implementation Plan: Phase 1

Phase 1 builds two components: **The Board** and **Direct Messaging**. Together they provide the communication foundation for the workspace vision.

### 7.1 Overview

| Step | Component | Files | Depends On | Deliverable |
|------|-----------|-------|------------|-------------|
| 1 | Schemas | `schemas/comms.py` | Nothing | Message + Board Pydantic models |
| 2 | Event Types | `schemas/events.py` | Step 1 | New event types for comms |
| 3 | Message Bus | `kernel/message_bus.py` | Steps 1-2 | Send, receive, reply, threading |
| 4 | Board Manager | `kernel/board_manager.py` | Steps 1-3 | Board state, posts, auto-status, alerts |
| 5 | Ambient Injector | `kernel/ambient_context.py` | Step 4 | Compact board rendering for agents |
| 6 | Tier 1 Integration | `adapters/tier1.py` | Steps 3-5 | Message-aware tool-calling loop |
| 7 | Tier 2 Files | `adapters/tier2_shared.py` | Steps 3-4 | Workspace file inbox/outbox/board |
| 8 | CLI Commands | `cli/comms.py` | Steps 3-4 | `agentos board`, `agentos message` |
| 9 | Tests | `tests/unit/`, `tests/integration/` | Steps 1-8 | Full test coverage |

### 7.2 Step 1: Schemas (`agentos/schemas/comms.py`)

Create the Pydantic v2 models for the communication system.

**File:** `agentos/schemas/comms.py`

**Contents:**
- `SpeechAct` enum (inform, request, propose, accept, reject, confirm, alert, directive, status)
- `MessagePriority` enum (low, normal, high, critical)
- `DirectMessage` model (message_id, thread_id, reply_to, reply_by, sender/recipient, content, speech_act, structured_data, attachments, priority, workflow_id, timestamp, delivered, acknowledged)
- `BoardPost` model (post_id, section, author, content, speech_act, structured_data, pinned, resolved, timestamp, expires_at, source_message_id)
- `AgentStatus` model (agent_id, agent_name, role, state, current_task, progress_summary, last_active)
- `BoardState` model (workflow_id, version, announcements, team_status, recent_posts, decisions, open_questions, alerts, last_updated)

**Tests:** `tests/unit/test_comms_schemas.py`
- Validate all models construct correctly with required fields
- Validate defaults
- Validate enum values
- Test serialization/deserialization round-trip

### 7.3 Step 2: Event Types (`agentos/schemas/events.py`)

Add communication event types to the existing `EventType` enum.

**Changes to:** `agentos/schemas/events.py`

**New event types:**
```python
# Communication (V2 — Board)
BOARD_POST_CREATED = "board.post_created"
BOARD_POST_PINNED = "board.post_pinned"
BOARD_POST_RESOLVED = "board.post_resolved"
BOARD_POST_ARCHIVED = "board.post_archived"
BOARD_POST_PROMOTED = "board.post_promoted"
BOARD_STATE_INJECTED = "board.state_injected"

# Communication (V2 — Direct Messaging)
DIRECT_MESSAGE_SENT = "direct_message.sent"
DIRECT_MESSAGE_DELIVERED = "direct_message.delivered"
DIRECT_MESSAGE_ACKNOWLEDGED = "direct_message.acknowledged"
THREAD_CREATED = "thread.created"
```

**Tests:** Existing event type tests should still pass. Add validation that new types are valid `EventType` members.

### 7.4 Step 3: Message Bus (`agentos/kernel/message_bus.py`)

Build the direct messaging infrastructure.

**File:** `agentos/kernel/message_bus.py`

**Class:** `MessageBus`

**Constructor:** `__init__(event_log, seq, workflow_id)`

**Methods:**
- `send(message: DirectMessage) -> str` — Store message, log `DIRECT_MESSAGE_SENT` event, return message_id
- `receive(recipient_id, priority_min, mark_delivered) -> list[DirectMessage]` — Get pending messages, optionally mark delivered, log `DIRECT_MESSAGE_DELIVERED` events
- `reply(reply_to_id, content, speech_act, **kwargs) -> str` — Create reply message with auto-set thread_id and reply_to. If no thread exists, create one and log `THREAD_CREATED`
- `get_pending_count(recipient_id) -> int` — Count undelivered messages (cheap, no content)
- `get_thread(thread_id) -> list[DirectMessage]` — All messages in thread, ordered by timestamp
- `acknowledge(message_id)` — Mark acknowledged, log `DIRECT_MESSAGE_ACKNOWLEDGED`
- `promote_to_board(message_id, board_manager, section) -> str` — Create BoardPost from message, log `BOARD_POST_PROMOTED`

**Internal storage:** In-memory dict of messages keyed by message_id + per-recipient inbox (list of message_ids). Thread-safe with `threading.Lock`.

**Tests:** `tests/unit/test_message_bus.py`
- Send and receive direct message
- Reply creates thread automatically
- Thread retrieval returns ordered messages
- Priority filtering on receive
- Delivery tracking (delivered flag, delivered_at timestamp)
- Acknowledgment tracking
- Pending count accuracy
- Thread-safety under concurrent sends
- Event logging verification (correct event types and payloads)
- Promotion to board (requires mock BoardManager)

### 7.5 Step 4: Board Manager (`agentos/kernel/board_manager.py`)

Build the shared board state management.

**File:** `agentos/kernel/board_manager.py`

**Class:** `BoardManager`

**Constructor:** `__init__(event_log, seq, workflow_id)`

**Methods:**
- `post(post: BoardPost) -> str` — Add post to appropriate section, log `BOARD_POST_CREATED`, increment version
- `pin(post_id) -> None` — Pin a post (move to announcements if not already), log `BOARD_POST_PINNED`
- `unpin(post_id) -> None` — Unpin
- `resolve(post_id, resolved_by) -> None` — Mark question/proposal as resolved, log `BOARD_POST_RESOLVED`
- `archive(post_id) -> None` — Remove from active board, log `BOARD_POST_ARCHIVED`
- `update_agent_status(agent_id, status: AgentStatus) -> None` — Update team roster entry
- `add_system_alert(content, structured_data) -> str` — Add alert to board
- `get_state() -> BoardState` — Return complete board state
- `render_compact(max_tokens) -> str` — Render concise text summary for agent injection
- `render_full() -> dict` — Full JSON for dashboard API
- `cleanup_expired() -> int` — Archive posts past their expires_at
- `cleanup_resolved(older_than_minutes) -> int` — Archive resolved items after cooldown

**Auto-generation rules:**
- Team status is updated when the DAG executor changes task states (via `update_agent_status`)
- Budget alerts are auto-posted when budget thresholds are crossed (60%, 80%, 95%)
- Task completion/failure posts are auto-generated from task state change events

**Tests:** `tests/unit/test_board_manager.py`
- Create board, add posts to each section
- Pin/unpin posts
- Resolve questions
- Archive posts
- Agent status updates
- System alerts
- Version increments correctly
- `render_compact` stays within token budget
- `render_compact` prioritizes correctly (pinned > alerts > recent posts)
- Cleanup expired and resolved posts
- Event logging for all mutations
- Promotion from message bus integration

### 7.6 Step 5: Ambient Context Injector (`agentos/kernel/ambient_context.py`)

Format board state for agent context injection.

**File:** `agentos/kernel/ambient_context.py`

**Class:** `AmbientContextInjector`

**Constructor:** `__init__(board_manager: BoardManager)`

**Methods:**
- `render_for_agent(agent_id, last_seen_version, token_budget) -> str | None` — Returns formatted board state or None if unchanged since last_seen_version
- `format_message_injection(messages: list[DirectMessage]) -> str` — Format direct messages for LLM context injection

**Rendering format:**
```
[WORKSPACE BOARD — v{version}, updated {relative_time}]
{pinned announcements, if any}
{alerts, if any}
{messages pending for this agent, count only — "You have 2 unread messages"}
{team status: who's doing what}
{recent posts, newest first, max 3}
[END BOARD]
```

**Design decisions:**
- Return `None` when board hasn't changed → avoids injecting duplicate content
- Token budget enforced by truncating low-priority sections
- Agent-specific: highlight messages/questions addressed to this agent
- Relative timestamps ("2 min ago") instead of absolute

**Tests:** `tests/unit/test_ambient_context.py`
- Render returns None when version unchanged
- Render respects token budget
- Prioritization order is correct
- Agent-specific content included
- Format is parseable and consistent

### 7.7 Step 6: Tier 1 Integration (`agentos/adapters/tier1.py`)

Modify the Tier 1 tool-calling loop to inject board state and direct messages.

**Changes to:** `agentos/adapters/tier1.py`

**New parameters in `execute_task()`:**
- `message_bus: MessageBus | None = None`
- `board_manager: BoardManager | None = None`
- `ambient_injector: AmbientContextInjector | None = None`

**Loop modification (between tool execution and next API call):**
1. Check board for updates via `ambient_injector.render_for_agent()` → inject if changed
2. Check inbox via `message_bus.receive()` → inject pending messages
3. If agent produces a message in tool output (detected via `task_complete` or special tool), route through message bus

**New tool definitions exposed to Tier 1 agents:**
- `post_to_board` — agent can post to the board
- `send_message` — agent can send direct messages
- `read_board` — agent can explicitly request full board state (beyond the ambient compact summary)

**Tests:** `tests/integration/test_tier1_comms.py`
- Agent receives board state at first iteration
- Agent receives board update only when version changes
- Agent receives direct messages at turn boundaries
- Agent can send messages via tool call
- Agent can post to board via tool call
- Messages from human are delivered at next iteration
- Priority filtering: critical messages always delivered, low messages batched
- Budget impact: verify token overhead of injections

### 7.8 Step 7: Tier 2 Workspace Files (`agentos/adapters/tier2_shared.py`)

Add workspace-based communication for Tier 2 subprocess agents.

**Changes to:** `agentos/adapters/tier2_shared.py`

**New functions:**
- `write_board_state(workspace: Path, board_manager: BoardManager)` — Write `.agentos/board.md` with current board state in human-readable markdown
- `write_inbox(workspace: Path, messages: list[DirectMessage])` — Write pending messages as individual `.agentos/inbox/msg-{id}.md` files
- `read_outbox(workspace: Path) -> list[dict]` — Read and parse JSON files from `.agentos/outbox/`, return as message dicts
- `cleanup_inbox(workspace: Path)` — Remove delivered message files

**Changes to Tier 2 adapter flow:**
1. Before launching subprocess: write board state and inbox to workspace
2. After subprocess completes: read outbox, route messages through message bus, update board with any posts

**System prompt addition (appended via `--append-system-prompt`):**
Standard instructions for reading board, checking inbox, writing to outbox.

**Tests:** `tests/unit/test_tier2_comms.py`
- Board state written as readable markdown
- Inbox messages written as individual files
- Outbox files parsed correctly
- Cleanup removes delivered messages
- Invalid outbox files handled gracefully

### 7.9 Step 8: CLI Commands (`agentos/cli/comms.py`)

Add CLI commands for human communication.

**File:** `agentos/cli/comms.py`

**Commands:**

```
agentos board [--workflow-id WF_ID] [--db DB_PATH]
    Show current board state for a workflow.

agentos board post <content> [--section post|question|decision] [--workflow-id WF_ID]
    Post to the board as the human manager.

agentos board pin <post-id>
    Pin a post to announcements.

agentos board resolve <post-id>
    Mark a question/proposal as resolved.

agentos message send <recipient> <content> [--priority normal|high|critical] [--speech-act inform|request|directive]
    Send a direct message to an agent.

agentos message list [--workflow-id WF_ID]
    Show pending messages and recent conversations.

agentos message thread <thread-id>
    Show full conversation thread.
```

**Integration:** Register as Click group in `agentos/cli/main.py`.

**Tests:** `tests/unit/test_cli_comms.py`
- Board display formats correctly
- Board post creates post via BoardManager
- Message send routes through MessageBus
- Message list shows pending messages
- Thread display shows ordered conversation

### 7.10 Step 9: Tests

**Unit tests (one file per component):**
- `tests/unit/test_comms_schemas.py` — Schema validation
- `tests/unit/test_message_bus.py` — All MessageBus methods
- `tests/unit/test_board_manager.py` — All BoardManager methods
- `tests/unit/test_ambient_context.py` — Injector rendering
- `tests/unit/test_tier2_comms.py` — Workspace file communication
- `tests/unit/test_cli_comms.py` — CLI commands

**Integration tests:**
- `tests/integration/test_tier1_comms.py` — Tier 1 agent with message injection (requires mock LLM)
- `tests/integration/test_board_messaging.py` — Board + MessageBus interaction (promotion, auto-alerts)
- `tests/integration/test_comms_events.py` — Verify all communication events are logged correctly

**Target:** ~50 new tests across all files.

### 7.11 File Summary

**New files (8):**
```
agentos/schemas/comms.py              # Message + Board schemas
agentos/kernel/message_bus.py         # Direct messaging infrastructure
agentos/kernel/board_manager.py       # Shared board state management
agentos/kernel/ambient_context.py     # Board rendering for agent injection
agentos/cli/comms.py                  # CLI commands for human communication
tests/unit/test_comms_schemas.py      # Schema tests
tests/unit/test_message_bus.py        # MessageBus tests
tests/unit/test_board_manager.py      # BoardManager tests
tests/unit/test_ambient_context.py    # Injector tests
tests/unit/test_tier2_comms.py        # Tier 2 file comm tests
tests/unit/test_cli_comms.py          # CLI command tests
tests/integration/test_tier1_comms.py # Tier 1 integration tests
tests/integration/test_board_messaging.py  # Board+MessageBus integration
tests/integration/test_comms_events.py     # Event logging tests
```

**Modified files (4):**
```
agentos/schemas/events.py             # New event types
agentos/adapters/tier1.py             # Message-aware loop
agentos/adapters/tier2_shared.py      # Workspace file communication
agentos/cli/main.py                   # Register comms CLI group
```

### 7.12 Implementation Order and Dependencies

```
Step 1: schemas/comms.py ──────────────┐
                                        ├─→ Step 3: kernel/message_bus.py ──┐
Step 2: schemas/events.py (extend) ────┘                                    │
                                                                             ├─→ Step 6: adapters/tier1.py
Step 4: kernel/board_manager.py ──→ Step 5: kernel/ambient_context.py ──────┘
                                        │
                                        ├─→ Step 7: adapters/tier2_shared.py
                                        │
                                        └─→ Step 8: cli/comms.py

Step 9: Tests (written alongside each step)
```

Steps 1-2 are independent and can be done together.
Steps 3 and 4 depend on 1-2 but are independent of each other (can be parallel).
Step 5 depends on 4.
Steps 6, 7, 8 depend on 3-5 but are independent of each other (can be parallel).

### 7.13 What This Enables

After Phase 1 is complete:

- **Agents see the board** — every Tier 1 agent gets a compact board summary injected at every tool-call boundary. Tier 2 agents get it as a workspace file.
- **Agents can post to the board** — share findings, ask questions, propose decisions visible to the whole team.
- **Agents can message each other** — direct, threaded conversations with speech act typing.
- **Humans can message agents** — via CLI (`agentos message send`) during workflow execution.
- **Humans can post to the board** — announcements, directives, decisions via CLI.
- **Everything is logged** — all messages and board changes are events in the audit trail.
- **Private conversations can go public** — promote a direct message finding to the board for team awareness.

### 7.14 What This Does NOT Include (Deferred)

- **MCP Communication Server** — deferred to Phase 2 (requires MCP server scaffolding)
- **Tier 2 SDK session migration** — deferred to Phase 2 (larger adapter rewrite)
- **Dashboard/WebSocket integration** — deferred to Phase 2 (frontend work)
- **Communication protocols** (review, handoff, consultation, escalation) — deferred to Phase 2 (requires message bus to be stable first)
- **Channel facilitation** (AutoGen-style speaker selection) — deferred to Phase 3
- **Conflict detection on board** (blackboard cleaning agent) — deferred to Phase 3
- **Mobile notifications** — deferred to Phase 4

---

## Appendix: Relationship to Existing Documents

- **WORKSPACE_VISION.md** — Defines the overall vision (workspace > workflow). This document implements Phase 1 of that vision.
- **COMMUNICATION_ARCHITECTURE.md** — Defines the layered communication model and adapter constraints. This document's implementation plan builds on that analysis.
- **PROJECT_OVERVIEW.md** — Describes teams, channels, and agent communication at the vision level. This document makes it concrete.
- **V2_DEVELOPMENT_PLAN.md** — Sprint-based plan for V2 features including channels and memory. This document's Phase 1 aligns with that plan's channel work but takes a different (more ambitious) approach.
