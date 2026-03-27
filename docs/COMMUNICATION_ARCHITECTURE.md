# AgentOS — Communication Architecture

**Companion to:** WORKSPACE_VISION.md | PROJECT_OVERVIEW.md
**Date:** March 2026
**Status:** Research — confronting the hard constraint before designing solutions

---

## The Hard Constraint

LLMs are request-response systems. They receive input, produce output, and stop. They do not listen for messages, notice changes in their environment, or maintain event loops. Every mechanism for making agents "communicate" must work within this fundamental limitation.

This is not a design question. It is a feasibility question. If we cannot make agents communicate effectively within the request-response constraint, the collaborative workspace vision described in WORKSPACE_VISION.md is not achievable with current LLM architectures.

This document confronts the constraint directly, catalogs every injection point available in our current adapter architecture, and proposes a layered communication model that works within reality.

---

## What We Actually Control

### Tier 1 Agents (API-controlled tool-calling loop)

AgentOS **fully controls** the execution loop. The loop in `tier1.py` works like this:

```
for each iteration (max 50):
    check termination flag
    send messages[] to LLM API
    track budget
    if stop_reason == "end_turn": break
    for each tool_use in response:
        execute tool → collect result
    append assistant response to messages[]
    append tool results to messages[]
```

**What we can inject and when:**

| Injection Point | What | How |
|---|---|---|
| Before first iteration | System prompt, initial messages | Function arguments (already works) |
| Between any two iterations | New messages into the `messages[]` list | Requires refactoring the loop (straightforward) |
| During tool execution | Modify tool results, add context | Via `tool_handler` callback (already exists) |
| At any iteration boundary | Terminate | Via `terminate()` flag (already exists) |

**The key insight for Tier 1:** We have a clean injection point between every single tool call. The agent calls a tool, we execute it, and before sending the results back to the LLM, we can append additional messages — "by the way, Agent B just found something relevant" or "the human wants you to change direction." The LLM sees this as part of the conversation and responds naturally.

**Cost:** Each injected message adds tokens to the next API call. But the control is total — we decide what to inject, when, and how much.

### Tier 2 Agents (Claude Code subprocess)

AgentOS launches Claude Code as a subprocess and waits for it to finish. The current adapter (`tier2_claude_code.py`) is fire-and-forget:

```
build command with --print --output-format stream-json
launch subprocess.Popen()
stream stdout (monitor tool calls, emit events)
wait for process exit
parse manifest.json from workspace
```

**What we can currently do mid-execution:**

| Capability | Status |
|---|---|
| Monitor tool calls in real-time | Yes (stdout streaming) |
| Track budget | Yes (post-hoc from usage output) |
| Terminate | Yes (SIGTERM/SIGKILL) |
| Inject messages | No |
| Modify context | No |
| Redirect the agent | No |

**What external interfaces exist (researched March 2026):**

| Interface | Mid-Execution? | Maturity | Notes |
|---|---|---|---|
| Python Agent SDK (`query()` + `resume`) | No — turn-based | Stable | Can resume sessions between turns |
| TypeScript V2 (`session.send()`) | No — turn-based | Preview | Cleaner API, same limitation |
| `--input-format stream-json` | Possibly | CLI flag exists, docs sparse | Bidirectional NDJSON over stdin/stdout. Needs experimentation. |
| Channels (MCP-based push) | **Yes — true mid-execution** | Research preview (March 2026) | Requires claude.ai login, not API keys |
| Hooks (`PreToolUse`, `PostToolUse`) | Reactive only | Stable | Can add context when agent acts, not when external event occurs |
| MCP tool ("check_messages") | Pull-based | Stable | Agent must choose to call the tool — not guaranteed |
| Session file manipulation | Between sessions only | Unsupported hack | Fragile, likely corrupts running sessions |

---

## The Honest Assessment

### What works today

**Tier 1 agents can have full real-time communication.** AgentOS controls the loop. Between any two tool calls, we can inject messages from other agents, from humans, or from the system. This is clean, reliable, and requires only a refactor of the Tier 1 loop to check a message queue at each iteration boundary.

### What doesn't work today

**Tier 2 agents (Claude Code) cannot receive messages mid-execution.** Once a Claude Code subprocess starts, it runs autonomously until it finishes or is killed. The only mid-execution options are:

1. **Channels** — true push-based injection, but research preview and requires claude.ai login (not suitable for server-side orchestration yet)
2. **MCP polling tool** — give the agent a `check_orchestrator_messages()` tool and instruct it to call it periodically. Works but is unreliable (the agent may not call it) and wastes tokens on empty polls
3. **Kill and restart** — terminate the agent, restart with updated context. Expensive, unreliable, loses in-progress work

### What could work soon

**The Agent SDK with session resume** enables turn-based communication. Instead of one long subprocess that runs to completion, AgentOS could run Claude Code in short turns:

```
Turn 1: "Research European markets" → agent works, produces partial results
Turn 2: "Update: ECB just announced rate change. Continue with this in mind." → agent continues
Turn 3: "Human says focus on Germany specifically." → agent adjusts
```

This is not real-time. The agent finishes each turn before seeing the next message. But it transforms Tier 2 from fire-and-forget into multi-turn conversation, which enables most collaboration patterns that matter.

**The `--input-format stream-json` flag** could enable true bidirectional streaming — pipe messages to Claude Code's stdin while reading responses from stdout. This is the most promising path but is underdocumented (GitHub issue #24594) and needs experimentation.

---

## Proposed Architecture: Layered Communication Model

Not all communication needs the same latency. The key insight is that different message types have different urgency levels, and we can use different mechanisms for each:

### Layer 1: Turn-Boundary Messaging (works now for Tier 1, near-term for Tier 2)

Messages are queued and delivered at the next natural boundary:
- **Tier 1:** Between tool calls (every few seconds)
- **Tier 2 (future):** Between session turns (every few minutes)

**Suitable for:**
- Context updates ("Agent B found relevant data")
- Non-urgent human input ("Focus more on European markets")
- Status requests ("What's your progress?")
- Informational broadcasts ("Budget at 60%")

**Architecture:**

```
┌──────────────────────────────────────────────────────────┐
│                    Message Queue                          │
│  Per-agent inbox backed by event log                     │
│                                                          │
│  Agent A's inbox:                                        │
│  ├── msg-001: from Agent B, priority: normal             │
│  │   "Found contradictory GDP data, see findings"        │
│  ├── msg-002: from Human, priority: high                 │
│  │   "Focus on Germany, not all of EU"                   │
│  └── msg-003: from System, priority: low                 │
│      "Budget at 60%, 2 hours elapsed"                    │
│                                                          │
│  Delivery:                                               │
│  ├── Tier 1: injected between tool calls                 │
│  ├── Tier 2: injected at session resume                  │
│  └── Human: delivered to dashboard/notification          │
└──────────────────────────────────────────────────────────┘
```

**Implementation for Tier 1 (refactor execute_task loop):**

```python
# Pseudocode — modified Tier 1 loop
for _ in range(MAX_ITERATIONS):
    if self._terminated:
        break

    # >>> NEW: Check message queue before each API call
    pending = self._message_queue.receive(self._agent_id)
    if pending:
        messages.append({
            "role": "user",
            "content": self._format_injected_messages(pending)
        })
    # <<< END NEW

    response = self._client.messages.create(...)
    # ... rest of loop unchanged
```

**Implementation for Tier 2 (migrate to SDK sessions):**

```python
# Pseudocode — SDK session-based Tier 2 adapter
session = sdk.create_session(workspace=workspace, tools=allowed_tools)

# Initial turn
result = session.query(task_prompt)

# Check for messages after each turn
while not task_complete(result):
    pending = self._message_queue.receive(self._agent_id)
    if pending:
        # Resume with injected context
        result = session.query(
            format_messages(pending),
            resume=session.id
        )
    else:
        break  # No messages, agent finished
```

### Layer 2: Interrupt Messaging (Tier 1 now, Tier 2 limited)

Some messages cannot wait for the next turn boundary. These require interrupting the agent:

**Suitable for:**
- Critical context changes ("Stop — the data you're using is wrong")
- Budget exceeded ("Hard limit reached, terminate cleanly")
- Human override ("Cancel this approach entirely")

**Tier 1 implementation:** Set a flag that injects a high-priority message at the very next tool call boundary. Since Tier 1 tool calls happen every few seconds, this is near-real-time.

**Tier 2 implementation:** For critical interrupts, terminate the subprocess and restart with updated context. This is the "kill and restart" approach, which is expensive but acceptable for rare, critical interrupts. The key is making it rare — most messages go through Layer 1.

```python
# Pseudocode — Tier 2 interrupt
async def interrupt(self, message: str, reason: str):
    """Interrupt running agent with critical message."""
    # Save current progress
    partial_output = self._capture_partial_output()

    # Terminate
    self._process.terminate()
    await self._wait_for_exit()

    # Restart with updated context
    updated_prompt = self._build_interrupt_prompt(
        original_task=self._current_task,
        partial_progress=partial_output,
        interrupt_message=message,
        interrupt_reason=reason,
    )

    # Resume execution
    return await self.execute_task(updated_prompt, ...)
```

### Layer 3: Environment-Based Awareness (works now, extend)

Instead of injecting messages into the agent's conversation, make information available in the agent's environment for it to discover:

**Mechanism:** Write files to the workspace that the agent can read.

```
workspace/
├── .agentos/
│   ├── inbox/           # Messages for this agent
│   │   ├── msg-001.md   # "From: Research Agent — Found conflicting data..."
│   │   └── msg-002.md   # "From: Human — Please focus on Germany"
│   ├── project_state.md # Living project state document
│   ├── team_status.md   # What other agents are doing right now
│   └── alerts.md        # Budget warnings, system notices
```

**For Tier 2 agents:** Include in the system prompt (via `--append-system-prompt`):
```
IMPORTANT: Before starting work and after completing major steps, check
.agentos/inbox/ for messages from your team. If messages exist, read
and incorporate them before continuing. Also check .agentos/project_state.md
for the latest project context.
```

**For Tier 1 agents:** Add a custom tool:
```python
def check_messages(agent_id: str) -> str:
    """Check for messages from team members and the human."""
    messages = message_queue.receive(agent_id)
    if not messages:
        return "No new messages."
    return format_messages(messages)
```

**Pros:**
- Works with both Tier 1 and Tier 2 today, no adapter changes
- Natural — agents read files, which they already do
- Low implementation cost

**Cons:**
- Unreliable — agent may not check (prompt-level instruction, not enforcement)
- Wasteful — agent checks even when no messages exist
- Latency — depends on when agent happens to check

**When to use:** As a supplement to Layer 1/2, not a replacement. Particularly useful for non-urgent context (project state, team status) that the agent benefits from having available but doesn't need delivered immediately.

### Layer 4: MCP-Based Communication (future, when Channels stabilize)

When Claude Code Channels exit research preview and support API key auth:

```
┌─────────────────────────────────────────────────────────┐
│              AgentOS Channel MCP Server                  │
│                                                          │
│  Exposes to Claude Code:                                 │
│  ├── channel events: messages from other agents/humans   │
│  ├── reply tool: send message back through AgentOS       │
│  ├── project state: current project context              │
│  └── team status: what other agents are doing            │
│                                                          │
│  Claude Code receives events mid-execution and reacts:   │
│  "New message from Research Agent: ECB rate change..."   │
│  Agent adjusts approach without restarting               │
│                                                          │
│  All messages flow through AgentOS:                      │
│  ├── Logged as events                                    │
│  ├── Subject to capability checks                        │
│  └── Visible in dashboard                                │
└─────────────────────────────────────────────────────────┘
```

This is the ideal architecture — true push-based, mid-execution messaging for Tier 2 agents. But it depends on Channels maturing and supporting API key authentication.

---

## How Agents "Notice" Things

The feedback asks a deeper question: how do agents become aware of changes in their environment?

Humans notice things because we have continuous sensory input. LLMs don't. They process a fixed input and produce output. "Noticing" must be engineered. There are three strategies:

### Strategy 1: Polling (agent checks periodically)

The agent is instructed to periodically check for updates. This can be:
- A tool call (`check_messages()`, `check_project_state()`)
- A file read (`.agentos/inbox/`)
- Built into the system prompt ("After every major step, check for updates")

**When it works:** When the polling interval is short relative to the importance of the update. If the agent checks every 2-3 tool calls and messages arrive every 10 minutes, this is fine.

**When it fails:** When the agent ignores the instruction (LLMs are not reliable instruction-followers for meta-tasks), or when the polling overhead exceeds the communication value.

**How to improve reliability:**
- Make the check tool always available and explicitly named in the system prompt
- Make the tool return useful info even when no messages exist (e.g., project status summary, budget remaining) so the agent is rewarded for calling it
- For Tier 1, make polling automatic at the framework level (check queue every N tool calls regardless of what the agent does)

### Strategy 2: Injection (system pushes to agent)

The system inserts information into the agent's context at natural boundaries:
- Tier 1: Between tool calls (framework-controlled, guaranteed)
- Tier 2 with SDK: Between session turns (framework-controlled, guaranteed)
- Tier 2 with Channels: Mid-execution (push-based, when available)

**When it works:** When the framework controls the execution loop (Tier 1) or the session boundary (Tier 2 with SDK).

**When it fails:** When the agent has no boundaries (long-running Tier 2 subprocess with no turn structure).

### Strategy 3: Environmental change (world changes, agent discovers it)

Instead of sending the agent a message, change its environment and let it discover the change during normal work:
- Update a file the agent is likely to read
- Modify the workspace state
- Change a resource the agent depends on

**When it works:** When the agent's normal work involves reading the changed resource. A research agent that reads from a shared data directory will naturally discover new data files.

**When it fails:** When the change is in a resource the agent wouldn't normally check. You can't rely on an agent noticing that `.agentos/alerts.md` was updated unless it has reason to read that file.

### Recommended Approach: Hybrid

No single strategy works for all cases. The system should use:

1. **Injection (guaranteed)** for Tier 1 and SDK-based Tier 2 — this is the primary communication channel, framework-controlled, no reliability concerns
2. **Polling (best-effort)** as a supplement for Tier 2 agents that run as long subprocesses — via MCP tool + prompt instruction
3. **Environmental change** for non-urgent context — project state, team status, shared artifacts updated in workspace
4. **Interrupt (emergency)** for critical messages that cannot wait — terminate and restart with updated context

---

## The Message Bus: Core Infrastructure

All communication layers feed through a single message bus. This is the new kernel component that replaces (or extends) the current ChannelRouter.

### Message Schema

```python
class WorkspaceMessage(BaseModel):
    """A message in the workspace communication system."""
    message_id: str                    # UUID
    thread_id: str | None = None       # For conversation threading
    reply_to: str | None = None        # Message being replied to

    # Addressing
    sender_type: Literal["agent", "human", "system"]
    sender_id: str                     # Agent ID, human user ID, or "system"
    recipient_type: Literal["agent", "human", "channel", "broadcast"]
    recipient_id: str | None = None    # Specific recipient or channel name

    # Content
    content: str                       # Natural language message
    structured_data: dict | None = None  # Optional structured payload

    # Metadata
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    message_type: Literal[
        "inform",      # FYI, no response expected
        "request",     # Asking for something, response expected
        "response",    # Reply to a request
        "directive",   # Human instruction, must be followed
        "alert",       # System warning
        "handoff",     # Formal work handoff with manifest
        "status",      # Progress update
    ] = "inform"

    # Protocol (for structured exchanges)
    protocol: str | None = None        # "handoff", "review", "consult", "escalate"
    protocol_state: str | None = None  # Protocol-specific state

    # Tracking
    timestamp: str                     # ISO datetime
    delivered: bool = False
    delivered_at: str | None = None
    acknowledged: bool = False

    # Governance
    workflow_id: str
    requires_capability: str | None = None  # Capability needed to read this message
```

### Message Bus Interface

```python
class MessageBus(ABC):
    """Central communication hub for the workspace."""

    @abstractmethod
    def send(self, message: WorkspaceMessage) -> str:
        """Send a message. Returns message_id. Logs MESSAGE_SENT event."""

    @abstractmethod
    def receive(self, recipient_id: str,
                priority_min: str = "low",
                since: str | None = None) -> list[WorkspaceMessage]:
        """Receive pending messages for a recipient. Logs MESSAGE_RECEIVED events."""

    @abstractmethod
    def reply(self, reply_to: str, content: str, **kwargs) -> str:
        """Reply to a specific message. Auto-sets thread_id and reply_to."""

    @abstractmethod
    def broadcast(self, channel: str, message: WorkspaceMessage) -> list[str]:
        """Send to all subscribers of a channel. Returns list of message_ids."""

    @abstractmethod
    def get_thread(self, thread_id: str) -> list[WorkspaceMessage]:
        """Get all messages in a conversation thread."""

    @abstractmethod
    def subscribe(self, participant_id: str, channel: str) -> None:
        """Subscribe to a channel."""

    @abstractmethod
    def get_pending_count(self, recipient_id: str) -> int:
        """Check how many undelivered messages exist (cheap, no content loaded)."""
```

### Integration with Existing Systems

The MessageBus **extends** the existing ChannelRouter, not replaces it:

```
Current ChannelRouter:
  - publish(channel, message) → broadcast to subscribers
  - receive(subscriber_id) → get pending messages
  - MESSAGE_SENT / MESSAGE_RECEIVED events

MessageBus adds:
  - Direct messaging (agent-to-agent, not just channel-based)
  - Threading (reply_to, thread_id)
  - Message types and priorities
  - Human participants
  - Protocol support (structured exchanges)
  - Delivery tracking (delivered, acknowledged)
```

The ChannelRouter can be refactored as the broadcast subsystem within the MessageBus. All existing channel-based workflows continue to work.

---

## Adapter Changes Required

### Tier 1: Message-Aware Loop

Refactor `execute_task()` in `tier1.py` to check the message bus between iterations:

```python
# New parameter
message_bus: MessageBus | None = None

# In the loop, between tool execution and next API call:
if message_bus is not None:
    pending = message_bus.receive(agent_id, priority_min="normal")
    if pending:
        # Inject as a user message with clear framing
        injection = format_message_injection(pending)
        messages.append({"role": "user", "content": injection})

        # For high-priority messages, also log
        for msg in pending:
            if msg.priority in ("high", "critical"):
                event_log.append(Event(
                    event_type=EventType.MESSAGE_DELIVERED_URGENT,
                    ...
                ))
```

**Message formatting for injection:**

```python
def format_message_injection(messages: list[WorkspaceMessage]) -> str:
    """Format messages for injection into LLM conversation."""
    parts = ["[TEAM COMMUNICATION — Messages from your workspace]"]
    for msg in messages:
        header = f"From: {msg.sender_id} ({msg.sender_type})"
        if msg.priority in ("high", "critical"):
            header += f" [PRIORITY: {msg.priority.upper()}]"
        if msg.message_type == "directive":
            header += " [DIRECTIVE — must follow]"
        parts.append(f"\n{header}")
        parts.append(msg.content)
        if msg.message_type == "request":
            parts.append("(Response expected — use reply tool or address in your output)")
    parts.append("\n[END TEAM COMMUNICATION — Continue your work, incorporating the above as needed]")
    return "\n".join(parts)
```

### Tier 2: Session-Based Adapter

Migrate from fire-and-forget subprocess to SDK session-based execution:

```python
class Tier2SessionAdapter(AgentAdapter):
    """Claude Code adapter using Agent SDK sessions for multi-turn execution."""

    async def execute_task(self, task_description, role, workspace,
                           predecessor_context, allowed_tools,
                           message_bus=None, **kwargs):

        session = self._create_session(workspace, allowed_tools)
        prompt = build_prompt(task_description, role, predecessor_context)

        # Execute in turns
        turn = 0
        while turn < self._max_turns:
            # Run one turn
            result = await session.query(prompt if turn == 0 else follow_up)
            turn += 1

            # Check if task is complete
            if self._is_task_complete(result, workspace):
                break

            # Check for pending messages
            if message_bus is not None:
                pending = message_bus.receive(self._agent_id)
                if pending:
                    follow_up = format_message_injection(pending)
                    continue  # Run another turn with the messages

            # No messages and task not complete — agent needs more turns
            follow_up = "Continue your work."

        return self._parse_output(workspace)
```

**Tradeoff:** This changes Claude Code from one long-running session to multiple shorter turns. Each turn resumes the session, so context is preserved. But there's overhead per turn (session resume cost) and the agent may lose "flow" between turns.

**Mitigation:** Only interrupt between turns when messages are actually pending. If no messages, let the agent continue without interruption. The `max_turns` parameter becomes a knob for balancing responsiveness (more turns = more chances to inject messages) against efficiency (fewer turns = less overhead).

### Tier 2 Alternative: MCP Communication Tool

For agents that must run as long subprocesses (not SDK-based), provide an MCP server:

```python
class AgentOSCommunicationMCP:
    """MCP server that agents can use to check and send messages."""

    tools = [
        {
            "name": "check_team_messages",
            "description": "Check for messages from your team members and the human. "
                         "Call this at the start of your work and after major steps.",
            "input_schema": {}
        },
        {
            "name": "send_team_message",
            "description": "Send a message to a team member or the human.",
            "input_schema": {
                "to": "string — recipient agent name or 'human'",
                "content": "string — your message",
                "priority": "string — 'normal' or 'high'",
            }
        },
        {
            "name": "get_project_state",
            "description": "Get the current project state including goals, progress, "
                         "key decisions, and what other agents are working on.",
            "input_schema": {}
        },
    ]
```

This gives Tier 2 agents a pull-based communication channel that works today, with the caveat that calling it is the agent's choice.

---

## Communication Patterns Enabled

With the message bus and adapter changes, these collaboration patterns become possible:

### Pattern 1: Agent asks agent for help

```
Research Agent → MessageBus → Analysis Agent
  "Found conflicting GDP data from IMF and World Bank.
   Which source should I prioritize for developed markets?"

Analysis Agent → MessageBus → Research Agent
  "Use IMF for developed markets (more recent methodology).
   Flag the discrepancy in findings with confidence: medium."
```

**Mechanism:** Request/response via message bus. Research agent sends request, continues other work. At next turn boundary, analysis agent receives the question, responds, and research agent gets the reply at its next boundary.

### Pattern 2: Human redirects an agent

```
Human → MessageBus → Research Agent
  [priority: high, type: directive]
  "Focus on Germany specifically, not all of EU.
   The client narrowed the scope."
```

**Mechanism:** Human sends directive through dashboard/CLI. Message queued with high priority. Delivered at next turn boundary for Tier 1 (seconds) or next session turn for Tier 2 (minutes).

### Pattern 3: Agent broadcasts a discovery

```
Research Agent → MessageBus → #team-updates channel
  [type: inform]
  "Breaking: ECB announced emergency rate change.
   This affects all European market analysis."

All subscribed agents receive at their next turn boundary.
```

**Mechanism:** Broadcast via channel subscription. All agents working on European markets get the update at their next natural boundary.

### Pattern 4: Structured review request

```
Writer Agent → MessageBus → Reviewer Agent
  [protocol: review, type: request]
  content: "Draft report ready for review"
  structured_data: {
    artifact: "/workspace/reports/draft_v1.md",
    criteria: ["factual accuracy", "clarity", "completeness"],
    deadline: "before synthesis task starts"
  }

Reviewer Agent → MessageBus → Writer Agent
  [protocol: review, type: response]
  content: "Review complete. Two issues found."
  structured_data: {
    verdict: "revise",
    issues: [
      {"severity": "high", "description": "GDP figure in section 3 contradicts source"},
      {"severity": "low", "description": "Conclusion could be more specific"}
    ]
  }
```

### Pattern 5: Escalation to human

```
Coordinator Agent → MessageBus → Human
  [priority: high, type: request, protocol: escalate]
  "Research agent and analysis agent disagree on methodology.
   Research wants top-down macro analysis.
   Analysis wants bottom-up sector analysis.
   Both have valid arguments. Need human decision."
  structured_data: {
    option_a: { agent: "research", approach: "top-down", rationale: "..." },
    option_b: { agent: "analysis", approach: "bottom-up", rationale: "..." },
  }
```

---

## Implementation Roadmap

### Step 1: Message Bus (kernel component)

Build `MessageBus` as a new kernel module (`agentos/kernel/message_bus.py`):
- Backed by event log (all messages are events)
- Extends/wraps existing ChannelRouter
- Message schema with threading, priorities, types
- Direct messaging + channel broadcast
- Human as first-class participant type

**Test:** Unit tests for send/receive/reply/broadcast/threading.

### Step 2: Tier 1 Message-Aware Loop

Refactor `tier1.py` to check message bus between iterations:
- Add `message_bus` parameter to `execute_task()`
- Check queue between tool execution and next API call
- Format injected messages clearly for the LLM
- Respect priority levels (critical = immediate, low = batch)

**Test:** Integration test — two Tier 1 agents communicating via message bus during execution.

### Step 3: Communication MCP Server

Build MCP server for agent-initiated communication:
- `check_team_messages` tool
- `send_team_message` tool
- `get_project_state` tool
- Wire into Tier 2 adapter via `--mcp-config`

**Test:** Tier 2 agent using MCP tools to send and receive messages.

### Step 4: Tier 2 SDK Session Adapter

Migrate Tier 2 from subprocess to Agent SDK sessions:
- Session creation with tools and permissions
- Multi-turn execution with resume
- Message injection between turns
- Preserve current features (budget tracking, tool monitoring, manifest parsing)

**Test:** Integration test — Tier 2 agent receiving messages between session turns.

### Step 5: Human Communication Interface

Extend CLI and dashboard API to support human messaging:
- `agentos message send <agent-id> "text"` — send message to running agent
- `agentos message list` — see pending messages and conversations
- Dashboard WebSocket for real-time message display
- Mobile notification hooks (webhook-based)

**Test:** E2E test — human sends message via CLI, agent receives and responds.

### Step 6: Communication Protocols

Implement structured exchange patterns:
- Handoff protocol (formal work transfer)
- Review protocol (request review, receive verdict)
- Consultation protocol (ask expert, get answer)
- Escalation protocol (surface to human/coordinator)

**Test:** Protocol-specific integration tests.

---

## Cost Analysis

Communication has a token cost. Every injected message is tokens the agent must process. Every reply is tokens the agent produces. This cost must be managed.

**Estimated overhead per message injection (Tier 1):**
- Average message: ~200 tokens
- Injection framing: ~100 tokens
- Agent processing: ~300 tokens response acknowledging the message
- **Total: ~600 tokens per message received**

**At Opus 4.6 pricing ($15/M input, $75/M output):**
- Receiving a message: ~$0.003 input + ~$0.02 output ≈ **$0.025 per message**
- 10 messages during a task: ~$0.25 overhead

**Mitigation strategies:**
- Batch low-priority messages (deliver multiple at once instead of one at a time)
- Summarize long threads before injection (compress conversation to key points)
- Rate limit per agent (max N messages per minute)
- Budget allocation for communication (separate from task budget)
- Priority filtering (only deliver high/critical during expensive operations)

---

## Open Questions Remaining

1. **Session resume fidelity** — When resuming a Claude Code SDK session with a new message, how well does the agent maintain its prior reasoning chain? Needs experimentation.

2. **Message ordering** — When multiple messages arrive between turns, what order should they be injected? By priority? By timestamp? By sender?

3. **Acknowledgment semantics** — Does "delivered" mean the agent saw the message, or that it was injected into context? Does "acknowledged" require explicit agent response?

4. **Multi-human coordination** — When two humans send conflicting directives, which wins? Need a human role/authority model.

5. **stream-json bidirectional** — The `--input-format stream-json` flag needs experimentation. If it works for bidirectional communication, it could replace the SDK session approach for Tier 2 with lower overhead.
