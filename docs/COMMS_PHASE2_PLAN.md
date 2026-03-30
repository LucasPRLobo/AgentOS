# AgentOS Communication System — Phase 2 Plan

**Companion to:** COMMS_RESEARCH_AND_PLAN.md | COMMUNICATION_ARCHITECTURE.md
**Date:** March 2026
**Branch:** `feature/agent-comunitaion`
**Status:** Planning

---

## Phase 2 Overview

Phase 1 delivered the Board and Direct Messaging foundation. Phase 2 makes communication **active** — agents can communicate mid-execution, exchanges follow structured protocols, and the system reacts to events automatically.

### Three deliverables:

| # | Deliverable | What it solves |
|---|---|---|
| **P2.1** | MCP Communication Server | Agents can check messages, send messages, read/post to board **during** execution — not just at start |
| **P2.2** | Communication Protocols | Structured exchanges (consult, review, escalate) that the system can track, enforce, and auto-resolve |
| **P2.3** | Board Auto-Updates | Board reacts to system events automatically — task state changes, budget thresholds, errors |

---

## P2.1 — MCP Communication Server

### Problem

Tier 2 agents currently only see the board and messages at launch (via workspace files). During execution, they are blind to new messages, board updates, and team activity. The MCP server gives them a "walkie-talkie" — tools they can call anytime during execution to participate in workspace communication.

### Architecture

```
Claude Code (Tier 2 agent)
    │
    │  calls tool: check_messages()
    │  calls tool: send_message(to="agent-b", content="...")
    │  calls tool: read_board()
    │  calls tool: post_to_board(content="...", section="question")
    │
    ▼
AgentOS Comms MCP Server  (stdio transport, spawned by Claude Code)
    │
    │  reads/writes via shared state files
    │
    ▼
Workspace Communication State  (.agentos/comms_state.json)
    │
    │  Orchestrator reads/routes between agents
    │
    ▼
BoardManager + MessageBus  (kernel components from Phase 1)
```

### Transport: stdio

Claude Code spawns the MCP server as a child process. Communication over stdin/stdout via JSON-RPC. The server lifecycle is tied to the agent session.

**Why stdio over HTTP:**
- Simplest — no port management, no separate daemon
- Claude Code handles lifecycle automatically
- No network config needed
- Perfect for single-user local development
- Can add HTTP later for remote/multi-client scenarios

### State Sharing Problem

The MCP server runs as a **child process of Claude Code**, not as a child of AgentOS. It cannot directly access the in-memory BoardManager and MessageBus. Two options:

**Option A: File-based state** (simpler, chosen for initial implementation)
- The orchestrator writes comms state to `.agentos/comms_state.json` before launching the agent
- The MCP server reads this file for board state and pending messages
- When the agent sends a message or posts to the board, the MCP server writes to `.agentos/outbox/`
- The orchestrator reads outbox after agent completes (same as Phase 1, but now messages can be sent mid-task)

**Option B: HTTP sidecar** (future, for real-time)
- AgentOS runs an HTTP API alongside the workflow
- The MCP server forwards tool calls to this API
- Enables true real-time message delivery
- More complex but needed for long-running agents

### MCP Server Implementation

**File:** `agentos/comms/mcp_server.py`

**Tools exposed:**

```python
@mcp.tool()
def read_board() -> str:
    """Read the workspace board — announcements, team status, recent posts,
    decisions, open questions, and alerts.

    Call this at the start of your work and periodically to stay aware
    of team activity.
    """

@mcp.tool()
def post_to_board(content: str, section: str = "post",
                   speech_act: str = "inform") -> str:
    """Post a message to the workspace board visible to all team members.

    Sections: post (general), question (needs answer), decision (records
    a choice made). Speech acts: inform, request, propose.
    """

@mcp.tool()
def check_messages() -> str:
    """Check for direct messages from team members and the human manager.

    Returns pending messages or 'No new messages.' Call this periodically
    and after major steps in your work.
    """

@mcp.tool()
def send_message(to: str, content: str, speech_act: str = "inform",
                  priority: str = "normal") -> str:
    """Send a direct message to a team member or the human manager.

    Recipients: use agent names (e.g. 'research-agent') or 'human'.
    Speech acts: inform (FYI), request (need response), propose (suggest direction).
    Priority: low, normal, high.
    """
```

**State file format** (`.agentos/comms_state.json`):
```json
{
    "board_compact": "[WORKSPACE BOARD — v5]\nPINNED: ...\n...",
    "board_full": { ... },
    "inbox": [
        {
            "message_id": "...",
            "sender_id": "human-manager",
            "content": "Focus on Germany",
            "speech_act": "directive",
            "priority": "high",
            "timestamp": "..."
        }
    ],
    "agent_id": "research-agent",
    "workflow_id": "wf-123"
}
```

**Outbox format** (unchanged from Phase 1):
Agent writes JSON files to `.agentos/outbox/` which the orchestrator reads after task completion. For mid-task sends, the MCP server also writes to outbox and can trigger a state file refresh.

### MCP Config Integration

**Per-agent in workflow YAML:**
```yaml
agents:
  research-agent:
    adapter: tier2_claude_code
    role: "Macro researcher"
    claude_code:
      mcp_config:
        - '{"mcpServers": {"agentos-comms": {"command": "python", "args": ["-m", "agentos.comms.mcp_server"], "env": {"AGENTOS_WORKSPACE": "${WORKSPACE_PATH}"}}}}'
```

**Auto-injection by adapter:**
The Tier 2 adapter should auto-inject the comms MCP config when a MessageBus/BoardManager is available, without requiring YAML config. The adapter builds the `--mcp-config` flag dynamically.

### System Prompt Addition

Update the existing `write_comms_prompt_addition()` to reference MCP tools instead of (or in addition to) file-based communication:

```
## Team Communication
You have MCP tools for team communication:
- read_board: See the shared workspace board (announcements, team status, findings)
- post_to_board: Share findings, ask questions, record decisions
- check_messages: Check for direct messages from teammates
- send_message: Send a direct message to a teammate or the human manager

Call read_board at the START of your work. Call check_messages periodically.
When you discover something important, post_to_board so the team knows.
```

---

## P2.2 — Communication Protocols

### Problem

Phase 1 messages are free-form — an agent sends text with a speech act, but the system doesn't enforce or track structured exchanges. Protocols formalize common patterns so the system can:
- Track whether a request got a response
- Auto-escalate unanswered requests after a timeout
- Detect when a review cycle is complete
- Route escalations to the right participant

### Protocol Definitions

Each protocol defines: participants, message sequence, completion condition, and timeout behavior.

#### Consultation Protocol

**Purpose:** Agent needs expert input before proceeding.

```
Requester → Expert:  [request] "Which GDP source for developed markets?"
Expert → Requester:  [inform]  "Use IMF — more recent methodology."
System:              Marks consultation as RESOLVED.
```

**Schema:**
```python
class ConsultationProtocol(BaseModel):
    protocol_id: str
    requester_id: str
    expert_id: str
    question: str
    response: str | None = None
    state: Literal["open", "answered", "timeout"] = "open"
    timeout_minutes: int = 30
    created_at: str
    resolved_at: str | None = None
```

**Behavior:**
- System tracks open consultations
- If no response within timeout, auto-posts to board as open question
- Unanswered consultations surface in agent/human dashboards

#### Review Protocol

**Purpose:** Agent submits work for review by another agent or human.

```
Author → Reviewer:   [request]  "Draft ready for review" + {artifact, criteria}
Reviewer → Author:   [response] {verdict: approve|revise|reject, issues: [...]}
If revise:
  Author revises, resubmits → loop
System:              Marks review as COMPLETE when approved or rejected.
```

**Schema:**
```python
class ReviewProtocol(BaseModel):
    protocol_id: str
    author_id: str
    reviewer_id: str
    artifact_path: str
    criteria: list[str]
    state: Literal["submitted", "in_review", "revision_requested",
                    "approved", "rejected"] = "submitted"
    rounds: list[ReviewRound] = []
    max_rounds: int = 3

class ReviewRound(BaseModel):
    round_number: int
    verdict: Literal["approve", "revise", "reject"]
    issues: list[dict] = []        # {severity, description}
    feedback: str | None = None
    timestamp: str
```

#### Escalation Protocol

**Purpose:** Agent can't resolve something — routes to coordinator or human.

```
Agent → Coordinator/Human:  [request, priority: high]  "Can't resolve X" + {context}
Coordinator/Human → Agent:  [directive]                 "Do Y instead"
System:                     Marks escalation as RESOLVED.
```

**Schema:**
```python
class EscalationProtocol(BaseModel):
    protocol_id: str
    escalator_id: str
    target_id: str              # "human" or coordinator agent
    issue: str
    context: dict | None = None
    resolution: str | None = None
    state: Literal["open", "resolved", "timeout"] = "open"
    priority: MessagePriority = MessagePriority.HIGH
    timeout_minutes: int = 60
```

### Protocol Manager

**File:** `agentos/comms/protocol_manager.py`

```python
class ProtocolManager:
    """Tracks structured communication exchanges.

    Monitors open protocols, auto-escalates timeouts,
    and logs protocol state changes as events.
    """

    def start_consultation(self, requester, expert, question, timeout): ...
    def start_review(self, author, reviewer, artifact, criteria): ...
    def start_escalation(self, agent, target, issue, context): ...

    def resolve(self, protocol_id, response): ...
    def check_timeouts(self) -> list[str]: ...  # Returns timed-out protocol IDs

    def get_open_protocols(self, participant_id) -> list: ...
    def get_protocol(self, protocol_id) -> Protocol: ...
```

### Event Types

```python
PROTOCOL_STARTED = "protocol.started"
PROTOCOL_RESPONSE_RECEIVED = "protocol.response_received"
PROTOCOL_RESOLVED = "protocol.resolved"
PROTOCOL_TIMEOUT = "protocol.timeout"
PROTOCOL_ESCALATED = "protocol.escalated"
```

### MCP Tool Integration

Add protocol tools to the MCP server:

```python
@mcp.tool()
def request_consultation(expert: str, question: str) -> str:
    """Ask another agent for expert input. The system will track
    whether you receive a response."""

@mcp.tool()
def request_review(reviewer: str, artifact_path: str,
                    criteria: list[str] | None = None) -> str:
    """Submit your work for review by another agent or the human."""

@mcp.tool()
def escalate(issue: str, context: str = "") -> str:
    """Escalate an issue you can't resolve to the human manager."""
```

---

## P2.3 — Board Auto-Updates

### Problem

Currently the board only updates when agents or humans explicitly post. The board should automatically reflect system state — task transitions, budget consumption, errors, protocol timeouts.

### Auto-Update Rules

| System Event | Board Action |
|---|---|
| Task state → RUNNING | Update team status: agent "running" |
| Task state → SUCCEEDED | Update team status: agent "succeeded" + auto-post summary |
| Task state → FAILED | Update team status: agent "failed" + alert with error |
| Budget at 60% | System alert: "Budget at 60%" |
| Budget at 80% | System alert: "Budget at 80% — consider wrapping up" |
| Budget at 95% | System alert (critical): "Budget nearly exhausted" |
| Budget exceeded | System alert (critical) + pin: "Budget exceeded — execution halted" |
| Protocol timeout | System alert: "Consultation/review timed out — needs attention" |
| Agent spawned | Team status: new agent added + board post |
| Gate waiting | Board question: "Gate {id} waiting for human input" |
| Gate resolved | Board post: "Gate {id} resolved: {action}" |

### Implementation

**File:** `agentos/comms/board_hooks.py`

```python
class BoardEventHooks:
    """Listens to event log and auto-updates the board.

    Called by the executor after emitting events, or runs as
    a polling loop that tails the event log.
    """

    def __init__(self, board_manager, event_log, workflow_id): ...

    def on_event(self, event: Event) -> None:
        """Process a single event and update the board if needed."""
        if event.event_type == EventType.TASK_STATE_CHANGED:
            self._handle_task_state(event)
        elif event.event_type == EventType.BUDGET_CONSUMED:
            self._handle_budget(event)
        elif event.event_type == EventType.GATE_WAITING:
            self._handle_gate_waiting(event)
        # ... etc

    def process_since(self, since_seq: int) -> int:
        """Process all events since a sequence number. Returns new seq."""
```

This hooks into the executor's event emission — after each event is logged, `on_event()` is called to update the board.

---

## Implementation Plan

### Step-by-step with dependencies

```
P2.1 — MCP Server                     P2.3 — Board Auto-Updates
  │                                      │
  ├─ 1. Install mcp SDK dep             ├─ 5. BoardEventHooks
  ├─ 2. Comms MCP server                ├─ 6. Budget threshold alerts
  ├─ 3. Comms state file I/O            └─ 7. Tests
  ├─ 4. Tier 2 adapter auto-injection
  └─ 4b. Tests + live demo
                    │
                    ▼
           P2.2 — Protocols
             ├─ 8. Protocol schemas
             ├─ 9. ProtocolManager
             ├─ 10. Protocol MCP tools
             ├─ 11. Protocol event types
             └─ 12. Tests
```

P2.1 and P2.3 are independent — can be built in parallel.
P2.2 depends on P2.1 (protocols are exposed as MCP tools).

### Files

**New files:**
```
agentos/comms/mcp_server.py          # MCP server with comms tools
agentos/comms/comms_state.py         # State file I/O for MCP server
agentos/comms/protocols.py           # Protocol schemas
agentos/comms/protocol_manager.py    # Protocol tracking and timeout
agentos/comms/board_hooks.py         # Board auto-updates from events
tests/unit/test_mcp_comms.py         # MCP server tool tests
tests/unit/test_protocols.py         # Protocol manager tests
tests/unit/test_board_hooks.py       # Board auto-update tests
tests/e2e/test_mcp_live.py           # Live test: agent uses MCP comms tools
```

**Modified files:**
```
agentos/schemas/events.py            # Protocol event types
agentos/adapters/tier2_claude_code.py # Auto-inject MCP config
agentos/adapters/tier2_shared.py     # Updated prompt with MCP tool references
pyproject.toml                       # mcp dependency (optional)
```

### Estimated scope

| Deliverable | New files | New tests | Complexity |
|---|---|---|---|
| P2.1 MCP Server | 2 | ~25 | Medium (MCP SDK integration) |
| P2.2 Protocols | 2 | ~30 | Medium (state tracking, timeouts) |
| P2.3 Board Auto-Updates | 1 | ~15 | Low (event → board mapping) |
| **Total** | **5** | **~70** | |

---

## Testing Strategy

### P2.1 — MCP Server

- **Unit:** Test each tool function in isolation with mock state files
- **Integration:** Write comms state → call tool → verify outbox
- **Live:** Launch Claude Code with MCP server, verify agent uses comms tools

### P2.2 — Protocols

- **Unit:** Start protocol → receive response → verify state transitions
- **Unit:** Timeout detection and auto-escalation
- **Integration:** Agent starts consultation via MCP → expert responds → protocol resolves

### P2.3 — Board Auto-Updates

- **Unit:** Feed events → verify correct board posts/alerts
- **Unit:** Budget threshold triggers at correct percentages
- **Integration:** Run a mini workflow → verify board reflects all state changes
