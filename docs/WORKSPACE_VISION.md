# AgentOS — Workspace Vision

**Companion to:** PROJECT_OVERVIEW.md | V2_DEVELOPMENT_PLAN.md
**Date:** March 2026
**Status:** Vision — defining the building blocks for AgentOS 2.0

---

## The Shift: From Workflow Execution to Collaborative Workspace

AgentOS 1.0 orchestrates agents through **static workflows**. A user writes YAML, defines tasks in a DAG, and the executor runs them. Agents complete isolated tasks and pass structured outputs forward. This works — it is reliable, auditable, and governable. But it is not how teams work.

Real teamwork is fluid. People start working, discover problems, ask teammates for help, replan mid-project, and produce work that nobody predicted at the start. A junior analyst doesn't wait for a formal "task assignment" to flag something strange in the data — they message a colleague. A manager doesn't define every task upfront — they set a direction and the team figures out the details.

**AgentOS 2.0 makes the workspace the central primitive, not the workflow.**

A workspace is a persistent environment where AI agents and human users collaborate as a real team. The workflow (DAG) still exists — but it is a living plan that evolves as work progresses, not a rigid program that executes. Agents work to their fullest within governed boundaries, communicate with each other and with humans naturally, and the system monitors and intervenes only when necessary.

The vision is not "agents in a metaverse office." The visual is irrelevant. The innovation is the **workframe** — the actual mechanisms that allow agents and humans to collaborate effectively, safely, and productively on real work.

---

## What Exists Today (AgentOS 1.0)

| Capability | Status | Limitation |
|---|---|---|
| DAG execution | Complete | Static — defined before execution, cannot adapt |
| Structured handoffs (TaskOutput) | Complete | One-directional — upstream to downstream only |
| Message channels (ChannelRouter) | Complete | Workflow-scoped, publish/subscribe only, no conversations |
| Teams with manager agents | Complete | Manager runs plan→execute→review loop, not real-time coordination |
| Approval gates | Complete | Binary (approve/reject/feedback), not conversational |
| Cross-run memory | Complete | Injected as synthetic context, not shared project understanding |
| Knowledge graph | Complete | Extracted post-task, not queryable by agents during execution |
| Dynamic agent spawning | Complete | Policy-gated, but spawned agents still follow static task model |
| Mutable DAG | Complete | Runtime insertions work, but only via spawn signals in open_questions |
| Budget enforcement | Complete | Hard limits — good for safety, but no nuanced "burn rate" awareness |
| Event log / audit trail | Complete | Comprehensive, but designed for post-hoc analysis, not real-time awareness |

**Summary:** The building blocks exist. Channels, teams, memory, knowledge graph, spawn, mutable DAG — these are all implemented. But they are wired as **workflow features** bolted onto a static execution model. The challenge is not building from scratch — it is **reframing and extending** these systems into a collaborative workspace framework.

---

## The Two Building Blocks

Every gap between AgentOS 1.0 and the workspace vision reduces to two fundamental challenges:

### 1. Communication

**The problem:** Agents today pass structured outputs through a DAG. They do not converse, negotiate, ask for help, or coordinate in real-time. Channels exist but are one-way publish/subscribe — not interactive.

**What the workspace needs:**
- Agents that can **talk to each other** mid-task, not just hand off results
- Agents that can **talk to humans** naturally, not just through approval gates
- Humans that can **broadcast context** to the team ("the client changed the scope")
- A coordinator that can **route, prioritize, and escalate** communication
- All of this **logged and governed** — no off-the-record agent chatter

**Why this is unique:** Claude Code's Agent Teams let agents message each other, but with no governance, no persistence, no human integration, and no audit trail. OpenClaw connects to messaging platforms but has no multi-agent coordination. No existing system combines real-time agent-agent and agent-human communication with full governance.

### 2. Context

**The problem:** Agents today receive context as a snapshot — task description + predecessor outputs + injected memories. They have no persistent understanding of the project, no awareness of what other agents are doing right now, and no way to build shared knowledge during execution.

**What the workspace needs:**
- A **living project state** that all agents and humans can read and contribute to
- **Awareness of ongoing work** — what other agents are doing, not just what they finished
- **Persistent project knowledge** that survives across sessions and workflow runs
- **Efficient context delivery** — agents shouldn't re-read everything, just what's relevant
- Context that **humans can also see and shape** — not hidden in agent prompts

**Why this matters:** Context is what separates a team from a group of individuals. A team of agents that each know only their own task will produce fragmented, inconsistent work. A team that shares understanding of the project, the goals, the constraints, and each other's progress will produce coherent, high-quality work.

---

## Communication: Deep Dive

### Current State

AgentOS has three communication mechanisms:

1. **Structured handoffs** (TaskOutput) — Rich JSON manifests with findings, confidence, sources. One-directional, task-boundary-only.
2. **Message channels** (ChannelRouter) — BROADCAST/QUEUE modes, MESSAGE_SENT/RECEIVED events. But messages are fire-and-forget — no replies, no threads, no conversations.
3. **Gates** — Human-to-system communication. Approve, reject, or provide feedback. Not conversational — a single exchange, not a dialogue.

### What's Missing

#### A. Conversational messaging (agent↔agent)

Current channels let Agent A publish a message that Agent B receives. But Agent B cannot reply to that specific message. There is no concept of a conversation thread, a question-and-answer exchange, or back-and-forth negotiation.

**Example of what should work:** A research agent finds contradictory data. It messages the analysis agent: "I found conflicting GDP figures from two sources — IMF says 2.3%, World Bank says 2.7%. Which should I use for the model?" The analysis agent replies: "Use IMF for developed markets, World Bank for emerging. Flag the discrepancy in the report." The research agent acknowledges and continues.

This requires:
- **Message threading** — replies linked to original messages
- **Request/response pattern** — an agent can ask a question and wait for an answer (with timeout)
- **Agent availability** — the system knows which agents are currently active and can receive messages
- **Priority/urgency** — some messages are informational, others are blocking

#### B. Human-agent conversation

Current gates are checkpoints — the workflow pauses, the human provides input, execution resumes. But real collaboration requires ongoing conversation:

- A human should be able to **message any agent at any time**, not just at gate points
- An agent should be able to **ask the human a question** without triggering a formal gate
- Multiple humans should be able to participate (stakeholder + domain expert + project manager)
- The conversation history should be **part of the project record**

**Example:** A human notices the research agent is going down the wrong path (visible in the real-time dashboard). They message the agent: "Focus on European markets, not Asian." The agent acknowledges and adjusts — no workflow pause, no gate, no YAML change.

#### C. Team-wide communication

Beyond point-to-point messaging, teams need broadcast capabilities:

- **Status updates** — agents automatically share progress ("research 60% complete, found 3 key sources so far")
- **Announcements** — human or coordinator broadcasts context change to all agents
- **Alerts** — system surfaces anomalies to the team ("budget at 80%", "Agent X failed, tasks being reassigned")

#### D. Structured communication protocols

Not all communication should be free-form. Some exchanges follow patterns:

- **Handoff protocol** — "I'm done with X, here's what you need to know to continue"
- **Review protocol** — "Here's my work, please evaluate against these criteria"
- **Consultation protocol** — "I need expert input on X before I can proceed" (already exists as consultation tasks, but limited to pre-defined DAG nodes)
- **Escalation protocol** — "I can't resolve this, routing to human/coordinator"
- **Negotiation protocol** — "I think we should approach X this way" / "I disagree, here's why" / "Let's compromise on..."

### Communication Architecture Sketch

```
┌─────────────────────────────────────────────────────┐
│                  Message Bus                         │
│  (extends ChannelRouter with threads, replies,       │
│   presence, priority, and human participants)        │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Channels (topic-based)     Threads (conversation)   │
│  ├── #research-findings     ├── thread-001 (Q&A)     │
│  ├── #team-status           ├── thread-002 (review)  │
│  ├── #alerts                └── thread-003 (decision)│
│  └── #human-directives                               │
│                                                      │
│  Protocols (structured exchanges)                    │
│  ├── handoff(from, to, manifest)                     │
│  ├── consult(requester, expert, question)             │
│  ├── review(author, reviewer, artifact, criteria)     │
│  └── escalate(agent, coordinator/human, issue)        │
│                                                      │
│  Governance layer                                    │
│  ├── All messages → event log                        │
│  ├── Capability check on send/receive                │
│  ├── Rate limiting (prevent agent chatter storms)    │
│  └── Human visibility into all channels              │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Key Design Decisions to Investigate

1. **Synchronous vs asynchronous messaging** — Should an agent block while waiting for a reply, or continue working and process the reply when it arrives? Real humans do both (email vs. in-person question). Agents likely need both modes.

2. **How agents "check messages"** — LLM agents don't have event loops. They run inference, produce output, and stop. How do you inject a message into an agent that's mid-task? Options: (a) messages queue and are injected at the next tool call, (b) messages interrupt the current task, (c) a side-channel that the agent polls. Each has tradeoffs.

3. **Token cost of communication** — Every message an agent receives costs tokens to process. Chatty agents waste budget. The system needs to balance communication richness against efficiency. Possible: message summarization, relevance filtering, priority-based delivery.

4. **Human interface** — How do humans participate in agent communication? A chat interface? Notifications with inline reply? Mobile push? The UX decision shapes what kind of collaboration is possible.

5. **Conversation memory** — Does an agent remember all prior messages in a thread, or just the most recent? Long conversations will exceed context windows. Need a summarization or retrieval strategy.

---

## Context: Deep Dive

### Current State

AgentOS has several context mechanisms:

1. **Task descriptions** — Static text from workflow YAML
2. **Predecessor outputs** — TaskOutput manifests from completed upstream tasks
3. **Channel messages** — Injected as synthetic TaskOutput entries
4. **Cross-run memory** — MemoryEntry objects (FINDING, DECISION, ERROR_PATTERN, etc.) with TTL decay
5. **Knowledge graph** — Entities and relationships extracted from task outputs
6. **Workspace files** — .agentos_context/ directory with JSON manifests
7. **Specialization tracker** — Agent-role performance history

### What's Missing

#### A. Living project state

Current context is assembled **per-task at execution time** — a snapshot. There is no persistent, queryable representation of "the project" that agents can reference.

**What this should be:** A structured document (or set of documents) maintained by the system and editable by agents and humans:

- **Project brief** — goals, constraints, stakeholders, success criteria
- **Current plan** — what work is planned, in progress, and completed (derived from DAG + events, but presented as a readable state)
- **Key decisions** — what has been decided and why (not buried in event log, but surfaced)
- **Shared artifacts** — the important outputs so far, curated and organized
- **Open questions** — what remains unresolved, who is working on what

**Why it matters:** When a new agent joins the workspace (spawned mid-execution or starting a new session), it needs to understand the project quickly. Today it gets a task description and predecessor outputs. It should get the equivalent of "here's the project, here's where we are, here's what you need to know."

#### B. Real-time awareness

Agents today know what predecessors **completed**. They don't know what other agents are **currently doing**.

**Example:** Analysis agent starts working on European market data. Meanwhile, research agent (running in parallel) discovers a major policy change that invalidates the analysis agent's assumptions. Today, the analysis agent won't know until the research agent finishes and the DAG routes the output. In a real team, the research agent would immediately flag: "Stop — ECB just announced rate change, your model needs updating."

This requires:
- **Progress broadcasting** — agents periodically share what they're working on and what they've found
- **Relevance routing** — not every progress update goes to every agent, only to those affected
- **Interruption mechanism** — a way to notify an agent that its context has changed

#### C. Context efficiency

LLMs have finite context windows. As projects grow, the accumulated context (all messages, all outputs, all decisions) will exceed what any single agent can hold. The system needs:

- **Context curation** — select the most relevant context for each agent's current task
- **Summarization** — compress historical context without losing critical information
- **Retrieval** — agents can query for specific context on demand ("what did the research agent find about interest rates?")
- **Tiered context** — essential context always present, supplementary context available on request

#### D. Human-readable project state

Humans need to see the same project context that agents see, but in a form that makes sense to non-technical users:

- Not raw JSON manifests — a dashboard with natural language summaries
- Not event log entries — a timeline of meaningful milestones
- Not token budgets — dollar costs and time estimates
- Not task IDs — agent names and role descriptions

### Context Architecture Sketch

```
┌─────────────────────────────────────────────────────┐
│                 Project Context Layer                │
│                                                      │
│  Project State (living document)                     │
│  ├── brief: goals, constraints, success criteria     │
│  ├── plan: current DAG state, human-readable         │
│  ├── decisions: key choices + rationale               │
│  ├── artifacts: curated outputs + summaries           │
│  └── questions: open issues, assigned owners          │
│                                                      │
│  Context Engine                                      │
│  ├── Assembler: builds per-agent context window       │
│  ├── Curator: selects relevant subset for each agent  │
│  ├── Summarizer: compresses historical context        │
│  ├── Retriever: on-demand context queries             │
│  └── Broadcaster: pushes updates to affected agents   │
│                                                      │
│  Sources (existing, to be integrated)                │
│  ├── Event log → timeline, decisions, state           │
│  ├── Memory store → cross-run knowledge               │
│  ├── Knowledge graph → entities, relationships        │
│  ├── Workspace files → artifacts                      │
│  ├── Channel messages → conversation history          │
│  └── Specialization tracker → agent capabilities      │
│                                                      │
│  Presentation                                        │
│  ├── Agent view: optimized for LLM context window     │
│  ├── Human view: dashboard, timeline, summaries       │
│  └── API view: structured JSON for integrations       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Key Design Decisions to Investigate

1. **Who maintains the project state?** Options: (a) a dedicated coordinator agent, (b) the system automatically derives it from events, (c) collaborative — agents and humans both edit it. Likely a hybrid: system derives baseline from events, coordinator agent curates, humans can override.

2. **How to summarize without losing critical details?** Summarization is lossy. A research finding compressed into one sentence might lose the nuance that matters. Need a strategy: keep full details in storage, present summaries by default, allow agents to "drill down" when needed.

3. **Context window management** — With 1M token context windows (Opus 4.6), this is less urgent than it used to be. But projects that run for days with many agents will still accumulate more context than fits. The system needs graceful degradation: prioritize recent + high-relevance context, archive the rest.

4. **Consistency** — If two agents read the project state at different times, they might see different things. How do we ensure agents working on related tasks have consistent context? Possible: versioned project state with explicit sync points.

5. **Context attribution** — When an agent acts on shared context, we should know which piece of context influenced the decision. This matters for debugging ("why did the agent do that?") and governance ("was the agent acting on validated information?").

---

## From Vision to Building Blocks

The workspace vision is ambitious. We build toward it incrementally, with each step delivering standalone value while moving toward the full picture.

### Phase 1: Communication Foundation

**Goal:** Agents and humans can have real conversations within a governed framework.

**Building blocks:**
1. **Message threading** — Extend ChannelRouter with reply-to semantics, thread grouping
2. **Request/response pattern** — Agent sends question, receives answer (with timeout + fallback)
3. **Human participant model** — Humans as first-class channel participants, not just gate responders
4. **Communication event types** — THREAD_CREATED, REPLY_SENT, CONVERSATION_CLOSED etc.

**What this enables:** Agents can ask each other questions mid-task. Humans can direct agents without formal gates. Communication is logged and governed.

**What exists to build on:** ChannelRouter (broker, pub/sub, events), consultation tasks (request/response pattern), gate feedback (human input model).

### Phase 2: Context Engine

**Goal:** Agents have efficient, relevant, shared understanding of the project.

**Building blocks:**
1. **Project state document** — Structured, maintained representation of project status
2. **Context assembler** — Builds per-agent context from project state + task-specific needs
3. **Context retrieval** — Agents can query for specific information on demand
4. **Progress broadcasting** — Agents share work-in-progress, not just completed outputs

**What this enables:** New agents onboard instantly. Agents stay aware of project evolution. Context is efficient (curated, not dumped).

**What exists to build on:** Memory store (persistence, decay, types), knowledge graph (entities, relationships, provenance), event log (state derivation), replayer (state reconstruction).

### Phase 3: Dynamic Collaboration

**Goal:** The team adapts its plan based on what it discovers.

**Building blocks:**
1. **Continuous replanning** — Coordinator agent adjusts the DAG based on progress and discoveries
2. **Work claiming** — Agents pick up tasks from a backlog, not just receive assignments
3. **Role-based autonomy** — Agents with roles have standing authority to act within their domain
4. **Interruption and redirection** — Change an agent's task or priorities mid-execution

**What this enables:** The plan evolves as work progresses. The team is responsive, not rigid.

**What exists to build on:** Mutable DAG (runtime insertions), manager adapter (plan→execute→review), team composer (dynamic spawning), spawn policy (governance).

### Phase 4: Human Integration

**Goal:** Non-technical humans participate as natural team members.

**Building blocks:**
1. **Conversational interface** — Chat-based interaction with agents and the workspace
2. **Natural language workflow creation** — Describe a project, system generates the plan
3. **Real-time dashboard** — Visual project state, timeline, costs, agent activity
4. **Mobile notifications** — Agents can reach humans on their phone for decisions
5. **Multi-human collaboration** — Multiple human stakeholders with different roles

**What this enables:** Non-technical users run agent teams without YAML, CLI, or engineering knowledge.

**What exists to build on:** Dashboard frontend (Canvas, PropertyPanel, NodePalette), gate system (human-in-the-loop), parameterized workflows (user-friendly config).

---

## What Makes This Not a Gimmick

The "AI agents in an office" demos that exist today are visual novelties. They show avatars sitting at desks but the underlying coordination is either:
- Simple prompt chaining (CrewAI-style)
- Unstructured message passing with no governance
- Pre-scripted sequences with no real adaptation

AgentOS's workspace is different because:

1. **The agents do real work** — They are actual autonomous systems (Claude Code, Codex, API agents) with tools, file access, and decision-making ability. Not prompt chains.

2. **The collaboration is governed** — Every message logged, every action auditable, budgets enforced, capabilities scoped. This makes it trustworthy for real-stakes work.

3. **The plan is alive** — The DAG evolves based on what agents discover. Work is dynamic, not scripted.

4. **Humans are real participants** — Not just approvers at checkpoints, but team members who can direct, contribute, and collaborate at any point.

5. **The context is shared and persistent** — Agents build on each other's knowledge. The project state survives across sessions. New agents onboard from shared understanding, not from scratch.

6. **It works for non-technical users** — The governance (budget, security, audit trail) that engineers appreciate becomes the trust layer that non-technical users need. "I can see what my agents are doing, what it's costing, and I can stop them if needed."

---

## Open Questions

These are the hard problems that need research and experimentation:

1. **How do LLM agents participate in real-time communication?** They don't have event loops. Injecting messages mid-inference is non-trivial. What's the right abstraction?

2. **How do you prevent communication overhead from consuming more tokens than the actual work?** Agent chatter is expensive. What's the right balance?

3. **Can a coordinator agent effectively manage a dynamic team, or does this require a fundamentally different architecture?** The manager adapter works for plan→execute→review. Does it scale to continuous coordination?

4. **What context delivery strategy works best for long-running projects?** Summarization loses detail. Full context exceeds windows. Retrieval requires knowing what to ask for. What's the right hybrid?

5. **How do you make this accessible to non-technical users without dumbing it down?** The power of the system is in its governance and flexibility. How do you expose that through a simple interface?

6. **What's the right granularity for "real-time awareness"?** Every tool call? Every minute? Every milestone? Too granular is noisy and expensive. Too coarse misses critical moments.

7. **How do multiple humans collaborate with agent teams?** Role-based access? Shared chat? Separate interfaces? What happens when two humans give conflicting directions?
