# AgentOS — Concurrent Workspace: Implementation Plan

**Date:** April 2026
**Status:** Implementation plan — the real workspace vision

---

## The Vision (What It Should Feel Like)

You open a workspace. Agents are already working. The board is updating
in real-time. You see a researcher post "Found something interesting."
The designer responds "Share that — it's relevant to my work." The
architect is reading the codebase. The coordinator notices the codebase
is larger than expected and spawns an additional agent. You post on
the board: "Focus on the chat panel — that's the priority." All agents
see your post on their next read_board call and adjust.

**This is NOT a DAG. This is NOT sequential. This is a shared environment.**

---

## What Exists (and what to keep)

Everything below the runtime layer is solid and reusable:

| Component | Keep | Notes |
|---|---|---|
| BoardManager | YES | Thread-safe, versioned. Add file persistence. |
| MessageBus | YES | Thread-safe. Add file-based delivery. |
| BacklogManager | YES | Thread-safe, file-persisted. Works as-is. |
| DiscussionManager | YES | Remove blocking. Discussions become async board posts. |
| ContextCurator | YES | Pure function. No changes needed. |
| TaskVerifier | YES | Pure function. No changes needed. |
| CompletionDetector | YES | Pure function. No changes needed. |
| ProjectArtifacts | YES | Append-safe. No changes needed. |
| ContextSummaryManager | YES | Incremental merge. No changes needed. |
| HookManager | YES | Add new events for concurrent model. |
| Schemas | YES | Add supervisor config + agent process state. |
| MCP Server | MODIFY | Read live files instead of snapshots. Add heartbeat tool. |
| Comms State | REWRITE | Per-agent directories instead of single snapshot. |
| Coordinator Runner | EXTEND | Add reactive invocations (replan, assign, stall). |
| Runtime | REWRITE | Sequential run() → supervisor with concurrent launch. |
| AgentRunner | REVIVE | Currently dead code. Use for process management. |
| Dashboard API | EXTEND | Add human command endpoint. |

---

## Architecture: The Supervisor Model

### Three Process Types, One Shared State

```
SUPERVISOR (Python async loop, persistent)
├── Polls shared files every 2-3s
├── Launches/monitors agent processes
├── Routes messages between agents
├── Invokes coordinator on-demand
├── Processes human commands
└── Writes board.json + agent inboxes

AGENTS (Claude Code subprocesses, concurrent)
├── One per task, runs independently
├── Reads board via MCP read_board
├── Posts to board via MCP post_to_board
├── Messages teammates via MCP send_message
├── Reports progress via MCP report_progress
└── Terminates when task is done

HUMAN (Dashboard or CLI, continuous)
├── Reads board in real-time (WebSocket or polling)
├── Posts to board (visible to all agents)
├── Messages specific agents
├── Claims tasks (becomes a worker)
├── Creates tasks, sets priorities
├── Chats with coordinator
└── Pauses/resumes/completes workspace
```

### Shared File Layout

```
.agentos/
├── board.json              # Live board state (written by supervisor)
├── board.lock
├── backlog/
│   ├── tasks.json          # Already exists, file-locked
│   └── backlog.lock        # Already exists
├── agents/
│   ├── researcher/
│   │   ├── inbox.json      # Pending messages for this agent
│   │   ├── status.json     # Self-reported: {task, activity, timestamp}
│   │   └── outbox/         # Messages FROM this agent (already exists)
│   │       └── msg-001.json
│   ├── designer/
│   │   └── ...
│   └── architect/
│       └── ...
├── human/
│   ├── inbox.json          # Messages for the human
│   └── commands.json       # Human commands (claim, create task, etc.)
├── events/
│   └── events.jsonl        # Append-only supervisor event stream
└── summaries/              # Already exists
    └── ...
```

---

## Task-by-Task Plan

### Phase 1: Shared State Layer

**Goal:** Replace snapshot-based comms with live, per-agent file I/O.
All existing comms tools keep working, but now agents read live state.

---

#### Task 1.1 — Board file persistence

**Modify:** `agentos/comms/board_manager.py`

Add methods to save/load board state to/from a JSON file:

```python
def save_to_file(self, path: Path) -> None:
    """Serialize current board state to JSON file with locking."""
    from agentos.workspace.filelock import file_lock
    with file_lock(path.with_suffix('.lock')):
        state = self.get_state()
        path.write_text(state.model_dump_json(indent=2))

def load_from_file(self, path: Path) -> None:
    """Load board state from JSON file."""
    if not path.exists():
        return
    from agentos.comms.schemas import BoardState
    data = json.loads(path.read_text())
    state = BoardState(**data)
    # Merge into in-memory state...
```

The supervisor calls `save_to_file()` every poll cycle.
MCP server reads this file directly.

**Tests:** Write/read round-trip, concurrent writes with locking.

**~80 lines code, ~60 lines tests**

---

#### Task 1.2 — Per-agent file I/O

**Rewrite:** `agentos/comms/comms_state.py`

Replace the single-snapshot pattern with per-agent directories:

```python
def ensure_agent_dir(workspace: Path, agent_id: str) -> Path:
    """Create .agentos/agents/{agent_id}/ if needed."""

def write_agent_inbox(workspace: Path, agent_id: str, messages: list) -> None:
    """Write pending messages to agent's inbox.json (locked)."""

def read_agent_inbox(workspace: Path, agent_id: str) -> list[dict]:
    """Read and clear agent's inbox.json."""

def read_agent_outbox(workspace: Path, agent_id: str) -> list[dict]:
    """Read and clear all .json files from agent's outbox/."""

def write_agent_status(workspace: Path, agent_id: str, status: dict) -> None:
    """Write agent's self-reported status (heartbeat)."""

def read_agent_status(workspace: Path, agent_id: str) -> dict | None:
    """Read agent's last reported status."""

def write_human_inbox(workspace: Path, messages: list) -> None:
    """Write messages for the human."""

def read_human_commands(workspace: Path) -> list[dict]:
    """Read and clear human commands."""

def write_human_command(workspace: Path, command: dict) -> None:
    """Human writes a command (from CLI/dashboard)."""
```

Keep the old `write_comms_state()` as a compatibility wrapper that
calls the new functions.

**Tests:** All read/write functions, concurrent access, clearing after read.

**~200 lines code, ~150 lines tests**

---

#### Task 1.3 — MCP server reads live files

**Modify:** `agentos/comms/mcp_server.py`

Current: reads `comms_state.json` (pre-written snapshot).
New: reads `board.json` and `agents/{id}/inbox.json` directly.

Changes:
- `read_board` → reads `.agentos/board.json` (or falls back to old format)
- `check_messages` → reads `.agentos/agents/{agent_id}/inbox.json`
- `post_to_board` / `send_message` → still writes to outbox (supervisor routes)
- **NEW tool: `report_progress(summary, activity)`** → writes to
  `.agentos/agents/{agent_id}/status.json` with timestamp

This means agents see LIVE board state, not a stale snapshot from
before they launched. When researcher posts a finding, designer sees
it on their next `read_board` call.

**Tests:** MCP tools read correct files, report_progress writes status.

**~100 lines changes, ~80 lines tests**

---

### Phase 2: Supervisor Core

**Goal:** Replace the sequential `run()` loop with a persistent
supervisor that manages concurrent agent processes.

---

#### Task 2.1 — Supervisor schemas

**Modify:** `agentos/workspace/schemas.py`

Add:
```python
class SupervisorConfig(BaseModel):
    poll_interval: float = 2.0      # seconds between supervisor ticks
    max_concurrent: int = 4          # max simultaneous agents
    agent_timeout: float = 600.0     # seconds before killing an agent
    heartbeat_stale: float = 30.0    # seconds without heartbeat = stalled
    coordinator_cooldown: float = 10.0  # min seconds between coordinator invocations

class AgentProcessState(BaseModel):
    agent_id: str
    task_id: str
    pid: int
    launched_at: str
    last_heartbeat: str | None = None
    last_activity: str | None = None
    status: str = "running"  # running, completed, failed, stalled, killed

class HumanCommand(BaseModel):
    command_id: str = Field(default_factory=_uuid)
    action: str  # post_to_board, send_message, claim_task, create_task,
                 # complete_task, set_priority, pause, resume, complete
    payload: dict = Field(default_factory=dict)
    timestamp: str = Field(default_factory=_utc_now_iso)
```

**~60 lines**

---

#### Task 2.2 — WorkspaceSupervisor

**New file:** `agentos/workspace/supervisor.py`

The core supervisor class. This is the centerpiece.

```python
class WorkspaceSupervisor:
    """Persistent supervisor for concurrent workspace execution.

    Replaces the sequential run() loop. Manages concurrent agent
    processes, routes messages, invokes coordinator reactively,
    and processes human commands.
    """

    def __init__(self, runtime: WorkspaceRuntime, config: SupervisorConfig):
        self._runtime = runtime
        self._config = config
        self._active: dict[str, AgentProcessState] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    async def run(self):
        """Main supervisor loop."""
        self._runtime.start()

        # Initial decomposition if backlog is empty
        if not self._runtime.backlog.get_all_tasks():
            self._invoke_coordinator("decompose")

        while self._runtime.state.status == WorkspaceStatus.ACTIVE:
            await self._tick()
            await asyncio.sleep(self._config.poll_interval)

    async def _tick(self):
        """Single supervisor cycle — the heartbeat of the workspace."""

        # 1. COLLECT: Check what happened since last tick
        completed = self._check_completed_agents()
        outbox_msgs = self._collect_all_outboxes()
        human_cmds = self._read_human_commands()
        heartbeats = self._check_heartbeats()

        # 2. REACT: Process events and make decisions
        for agent_info in completed:
            self._on_agent_completed(agent_info)

        for msg in outbox_msgs:
            self._route_message(msg)

        for cmd in human_cmds:
            self._process_human_command(cmd)

        for stalled_id in heartbeats.get("stalled", []):
            self._on_agent_stalled(stalled_id)

        # 3. SPAWN: Launch agents for ready tasks (up to concurrency limit)
        self._spawn_ready_agents()

        # 4. CHECK: Completion, budget, stalls
        self._check_workspace_health()

        # 5. WRITE: Update shared state files
        self._write_shared_state()
```

Key methods:

```python
def _spawn_agent(self, agent_id: str, task: BacklogTask) -> None:
    """Launch a Claude Code instance. Returns immediately (non-blocking)."""
    # Build command (reuse _default_execute logic)
    # Popen without wait
    # Track in self._active + self._procs
    # Claim task, start task

def _check_completed_agents(self) -> list[AgentProcessState]:
    """Poll all active processes. Return those that finished."""
    # proc.poll() != None → completed
    # Read stdout for result json
    # Parse manifest if exists
    # Detect new files in workspace

def _on_agent_completed(self, info: AgentProcessState) -> None:
    """Handle a completed agent."""
    # Parse output (manifest, new files, tool calls)
    # Mark task COMPLETED
    # Run verification
    # If auto_accept → mark DONE, unblock dependents
    # If needs_review → open review discussion (async, non-blocking)
    # Update agent status on board
    # Write output artifact
    # Fire TASK_COMPLETED hook

def _route_message(self, msg: dict) -> None:
    """Route an outbox message to the right destination."""
    # "to": "board" → board.post()
    # "to": "human" → write to human inbox
    # "to": "agent-id" → write to agent inbox

def _process_human_command(self, cmd: HumanCommand) -> None:
    """Process a command from the human."""
    # "post_to_board" → board.post()
    # "send_message" → write to agent inbox
    # "claim_task" → backlog.claim_task()
    # "create_task" → backlog.create_task() or propose_task()
    # "complete_task" → mark done
    # "set_priority" → update task
    # "pause" → runtime.pause()
    # "resume" → runtime.resume()
    # "spawn_agent" → launch additional agent

def _spawn_ready_agents(self) -> None:
    """Find ready tasks and launch agents for them."""
    ready = self._runtime.backlog.get_ready_tasks()
    slots = self._config.max_concurrent - len(self._active)
    for task in ready[:slots]:
        agent_id = self._pick_or_assign_agent(task)
        if agent_id and agent_id not in self._active:
            self._spawn_agent(agent_id, task)

def _on_agent_stalled(self, agent_id: str) -> None:
    """Handle a stalled agent — no heartbeat for too long."""
    # Kill process
    # Mark task as failed
    # Optionally invoke coordinator for reassignment

def _invoke_coordinator(self, reason: str, **context) -> None:
    """Invoke the coordinator for a planning decision."""
    # Launches coordinator as Claude Code subprocess (blocking for now)
    # reason: "decompose", "replan", "assign", "stall_resolution"
    # Reads result (tasks.json or assessment.json)
    # Applies decisions to backlog

def _write_shared_state(self) -> None:
    """Write board.json, agent inboxes, human inbox, state artifact."""
    # board.save_to_file(.agentos/board.json)
    # Deliver pending messages to agent inbox files
    # Deliver human messages to human/inbox.json
    # artifacts.update_state()

def _check_workspace_health(self) -> None:
    """Check completion, budget, stalls."""
    result = self._runtime._completion.check()
    if result.complete:
        self._runtime.complete()
    # Check budget thresholds
    # Check for stalled tasks
    # Check diminishing returns
```

**~400 lines code, ~200 lines tests**

---

#### Task 2.3 — Non-blocking agent launch

**Modify/extract from:** `agentos/workspace/runtime.py`

Extract the agent launch logic from `_default_execute()` into a
standalone function that builds the command and returns a `Popen`
without waiting:

```python
def launch_agent_process(
    agent_id: str,
    task: BacklogTask,
    workspace: Path,
    project_dir: Path | None,
    curator: ContextCurator,
    board: BoardManager,
    bus: MessageBus,
    workflow_id: str,
) -> tuple[subprocess.Popen, list[str]]:
    """Build and launch a Claude Code agent. Returns (proc, cmd)."""
    # Build prompt with curated context
    # Build command with MCP, --add-dir, stream-json
    # Popen() and return immediately
```

Also extract output parsing into a standalone function:

```python
def collect_agent_output(
    proc: subprocess.Popen,
    workspace: Path,
    files_before: set[str],
) -> dict:
    """Read stdout, parse manifest, detect new files. Call after proc completes."""
```

**~150 lines refactor**

---

### Phase 3: Human Integration

**Goal:** The human participates freely — as worker or manager —
without blocking the supervisor loop.

---

#### Task 3.1 — Human command protocol

**New functions in:** `agentos/comms/comms_state.py` (already added in 1.2)

The human (via CLI or dashboard) writes commands to
`.agentos/human/commands.json`. The supervisor reads and processes
them each tick.

Command types:
```python
# As manager
{"action": "post_to_board", "payload": {"content": "Focus on chat panel", "section": "directive"}}
{"action": "send_message", "payload": {"to": "researcher", "content": "Also check Slack's UX"}}
{"action": "create_task", "payload": {"title": "Research Slack UX", "suggested_for": "researcher"}}
{"action": "set_priority", "payload": {"task_id": "...", "priority": "critical"}}
{"action": "spawn_agent", "payload": {"task_id": "...", "agent_name": "researcher-2"}}
{"action": "pause"}
{"action": "resume"}

# As worker
{"action": "claim_task", "payload": {"task_id": "...", "participant": "lucas"}}
{"action": "complete_task", "payload": {"task_id": "...", "summary": "Done"}}
```

**~60 lines**

---

#### Task 3.2 — Async discussions

**Modify:** `agentos/comms/discussions.py`

Remove all blocking patterns. Discussions become board posts that
agents and humans respond to asynchronously:

- `open()` — posts to board + human inbox. Does NOT wait.
- Human responds via command: `{"action": "reply_discussion", "payload": {"thread_id": "...", "content": "..."}}`
- Supervisor detects the reply, calls `add_message()`, checks if resolution criteria met.
- Coordinator can also be invoked to check if discussion is resolvable.

No `_human_input_fn` needed. Discussions are just threaded board posts.

**~80 lines changes**

---

#### Task 3.3 — Dashboard human commands

**Modify:** `agentos/dashboard/workspace_api.py`

Add endpoint for human commands:
```
POST /api/workspaces/{workspace_id}/command
  body: {"action": "...", "payload": {...}}

Writes to .agentos/human/commands.json (supervisor picks up on next tick)
```

Also modify the WebSocket to include discussion threads and agent
progress in real-time updates.

**~60 lines**

---

#### Task 3.4 — CLI human interface

**New file:** `examples/workspace_live.py`

A terminal UI for the human to participate in a live workspace:

```
AgentOS Workspace: Dashboard Design
Status: ACTIVE | Agents: 3 running | Tasks: 2/8 done
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOARD (live updates):
  📌 Project: Research and design the dashboard frontend
  🔵 researcher: Reading agentos/comms/board_manager.py
  🔵 architect: Writing technical_architecture.md
  🟢 designer: Posted finding: "Linear's kanban uses minimal cards"
  ❓ coordinator: @human Should we add a file browser panel?

YOUR TURN (type a command or message):
> Focus on the chat panel — that's the most important part
  [posted to board]

> /claim task-5
  [claimed: Write comparison report]

> /msg researcher Also look at how Grafana handles alerts
  [sent to researcher]

> /status
  researcher: 📖 Reading workspace/ChatPanel.tsx (42s ago)
  architect:  ✏️  Writing technical_architecture.md (15s ago)
  designer:   idle — waiting for research output
```

This is a polling loop that reads board.json + agent statuses +
human inbox every 2 seconds and renders the latest state.
Human input goes to commands.json.

**~250 lines**

---

### Phase 4: Coordinator Reactions

**Goal:** Coordinator is invoked by the supervisor when decisions
are needed — not as a sequential planner but as a reactive advisor.

---

#### Task 4.1 — Reactive coordinator invocations

**Extend:** `agentos/workspace/coordinator_runner.py`

Add new invocation types:

```python
def run_assignment(config, workspace, board, bus, backlog, ready_tasks, ...) -> dict:
    """Coordinator decides who should work on ready tasks.
    Returns: {"assignments": [{"task_id": "...", "agent_id": "..."}]}"""

def run_replan(config, workspace, board, bus, backlog, trigger, ...) -> list[BacklogTask]:
    """Coordinator replans based on a trigger event.
    Returns: new/modified tasks."""

def run_stall_resolution(config, workspace, board, bus, backlog, stalled_task, ...) -> dict:
    """Coordinator decides what to do about a stalled task.
    Returns: {"action": "reassign|cancel|spawn_helper|wait", ...}"""

def run_team_adjustment(config, workspace, board, bus, backlog, ...) -> dict:
    """Coordinator recommends team changes.
    Returns: {"spawn": ["researcher-2"], "deactivate": [], "reason": "..."}"""
```

Each is a Claude Code subprocess with a focused prompt.
The supervisor calls these when specific events trigger them.

**~200 lines code, ~100 lines tests**

---

#### Task 4.2 — Supervisor trigger conditions

**In:** `agentos/workspace/supervisor.py`

Define when the supervisor invokes the coordinator:

```python
def _should_invoke_coordinator(self) -> str | None:
    """Check if coordinator intervention is needed. Returns reason or None."""

    # After initial start (no tasks)
    if not self._runtime.backlog.get_all_tasks():
        return "decompose"

    # When ready tasks have no suggested agent
    ready = self._runtime.backlog.get_ready_tasks()
    unassigned = [t for t in ready if not t.suggested_for]
    if unassigned:
        return "assign"

    # When all active agents finished but tasks remain
    if not self._active and self._runtime.backlog.get_open_tasks():
        return "assign"

    # When an agent stalled
    if self._stalled_agents:
        return "stall_resolution"

    # When human requested replan
    # When budget threshold crossed
    # When diminishing returns detected

    return None
```

**~80 lines**

---

### Phase 5: Streaming & Observability

**Goal:** Real-time visibility into what agents are doing.

---

#### Task 5.1 — Agent progress streaming

**Already partially exists.** The current `_default_execute()` in
runtime.py streams tool calls via `stream-json` format.

Move this to the supervisor: while agents run, the supervisor reads
their stdout pipes in background threads and updates agent status:

```python
def _monitor_agent_stdout(self, agent_id: str, proc: subprocess.Popen):
    """Background thread: read agent stdout, update status."""
    for line in proc.stdout:
        event = json.loads(line)
        if event.get("type") == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "tool_use":
                    desc = describe_tool_call(block["name"], block["input"])
                    self._update_agent_activity(agent_id, desc)
```

Activity descriptions flow to:
- Agent status on the board (visible to other agents)
- Dashboard WebSocket (visible to human)
- CLI display (live terminal updates)

**~100 lines**

---

#### Task 5.2 — Event stream file

**New:** `.agentos/events/events.jsonl`

Append-only file where the supervisor writes every significant event:

```jsonl
{"ts": "...", "type": "agent_spawned", "agent": "researcher", "task": "Research UX"}
{"ts": "...", "type": "agent_activity", "agent": "researcher", "activity": "Reading ChatPanel.tsx"}
{"ts": "...", "type": "board_post", "author": "researcher", "content": "Found..."}
{"ts": "...", "type": "agent_completed", "agent": "researcher", "task": "Research UX"}
{"ts": "...", "type": "human_command", "action": "post_to_board", "content": "Focus on chat"}
{"ts": "...", "type": "task_unblocked", "task": "Design layout"}
{"ts": "...", "type": "agent_spawned", "agent": "designer", "task": "Design layout"}
```

Dashboard and CLI tail this file for live updates.

**~60 lines**

---

### Phase 6: Integration + Demo

---

#### Task 6.1 — Wire supervisor into workspace start

**Modify:** `agentos/workspace/runtime.py`

Add a `run_concurrent()` method that creates and runs the supervisor:

```python
async def run_concurrent(self, supervisor_config: SupervisorConfig | None = None):
    """Run workspace with concurrent agent execution."""
    from agentos.workspace.supervisor import WorkspaceSupervisor
    config = supervisor_config or SupervisorConfig()
    supervisor = WorkspaceSupervisor(self, config)
    return await supervisor.run()
```

Keep the old `run()` for backwards compatibility (sequential mode).

**~20 lines**

---

#### Task 6.2 — Live demo script

**New:** `examples/workspace_live.py` (from Task 3.4)

The complete human experience:
1. Load YAML config
2. Start workspace + supervisor in background thread
3. Terminal UI: live board, agent progress, human input
4. Human can post, message, claim tasks, create tasks
5. Ctrl+C to pause/stop

**~250 lines**

---

#### Task 6.3 — Dashboard integration

**Modify:** `examples/start_dashboard.py`

Start the dashboard with the supervisor running in background.
WebSocket delivers live updates. Human commands via API.

**~50 lines changes**

---

#### Task 6.4 — Integration tests

**New:** `tests/integration/test_supervisor.py`

- Supervisor launches 2 agents concurrently (mock execute)
- Agent completion triggers task state change
- Outbox messages route correctly
- Human command creates task
- Stall detection works
- Coordinator invoked on trigger
- Workspace completes when all tasks done

**~300 lines**

---

## Summary

| Phase | Tasks | New/Modified | Lines (est.) |
|---|---|---|---|
| **P1: Shared state** | 1.1-1.3 | board_manager, comms_state, mcp_server | ~670 |
| **P2: Supervisor** | 2.1-2.3 | supervisor.py (new), schemas, runtime | ~810 |
| **P3: Human** | 3.1-3.4 | comms_state, discussions, workspace_api, workspace_live.py | ~450 |
| **P4: Coordinator** | 4.1-4.2 | coordinator_runner, supervisor | ~380 |
| **P5: Streaming** | 5.1-5.2 | supervisor, events file | ~160 |
| **P6: Integration** | 6.1-6.4 | runtime, demos, tests | ~620 |
| **Total** | **16 tasks** | | **~3,090** |

### Dependency Graph

```
P1 (shared state) ─────────────────┐
                                    ├── P2 (supervisor) ──── P4 (coordinator)
                                    │        │
                                    │        ├── P5 (streaming)
                                    │        │
                                    ├── P3 (human) ──────── P6 (integration)
                                    │
                                    └── (all depend on P1)
```

### What This Enables

After implementation, a workspace session looks like:

```
$ python examples/workspace_live.py examples/dashboard_design.yaml

AgentOS Workspace: Dashboard Design
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGENTS: researcher[🔵] designer[🔵] architect[🔵]
TASKS:  3 running | 2 ready | 5 blocked | 0 done
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LIVE BOARD:
  📌 Goal: Research and design the AgentOS dashboard
  🔵 researcher: 📖 Reading comms/board_manager.py
  🔵 architect: 🔎 Searching for 'WebSocket'
  🔵 designer: 🔧 WebSearch: Linear kanban UX patterns
  💬 researcher → board: "The existing board has 6 sections.
     Key insight: the board is versioned, so WebSocket can
     poll by version number for efficient updates."
  💬 architect → researcher: "Can you check what events the
     WebSocket already streams? I need that for my architecture doc."

> Also look at how the discussion threads should appear in the UI

  [posted to board — all agents will see this on next read_board]

  🔵 researcher: 📖 Reading comms/discussions.py
  🔵 designer: ✏️  Writing ux_research.md
  💬 coordinator: "Researcher is exploring deeply. Spawning
     researcher-2 to handle the UX competitor analysis in parallel."
  🟢 researcher-2 spawned for: Competitor UX analysis

> /status
  researcher:   📖 Reading discussions.py (12s ago)
  researcher-2: 🔧 WebSearch: Asana board UX (3s ago)
  designer:     ✏️  Writing ux_research.md (8s ago)
  architect:    📖 Reading workspace_api.py (5s ago)
```

**This is the vision: agents working together, the human in the room with them, everyone seeing what everyone else is doing.**

---

## Human Participation Guarantees

The human is NOT an approver. The human is NOT a checkpoint gate.
The human is a **team member** — they can work alongside agents,
direct them, and participate in discussions at any moment.

### Every-Tick Guarantee

On every supervisor tick (every 2-3 seconds), the supervisor:
1. Reads `.agentos/human/commands.json` — any human action takes effect immediately
2. Writes `.agentos/human/inbox.json` — human sees all messages within one tick
3. Updates board.json — human sees all board changes within one tick

**Test:** At any point during execution, the human can type a message
and have it influence what agents do next. Not after the current task
finishes. Not at the next checkpoint. On the next tick.

### Human as Worker

The human is listed in the team roster like any agent. They can:
- **Claim tasks** from the backlog — supervisor won't assign those to agents
- **Complete tasks** — marks DONE, unblocks dependents, triggers downstream
- **Submit work** — writes files to the workspace, posts findings to the board
- **Ask for help** — messages an agent: "Can you research X for me while I work on Y?"

When the human claims a task, their status on the board shows:
`lucas: working on "Write comparison report"` — visible to all agents.

The coordinator accounts for human capacity when planning. It can
suggest tasks for the human that require judgment, creativity, or
domain expertise that agents lack.

### Human as Manager

The human can at any time, without waiting for any checkpoint:
- **Post directives** to the board — "Focus on the chat panel"
  → All agents see this on their next `read_board` call
- **Message any agent** — "Researcher, also check Slack's UX"
  → Agent sees it in their inbox on next `check_messages` call
- **Create tasks** — "We also need to research Grafana dashboards"
  → Task appears in backlog, supervisor assigns it
- **Change priorities** — "Make the architecture doc critical"
  → Task reordered, may trigger coordinator replanning
- **Spawn agents** — "Add another researcher for competitor analysis"
  → Supervisor launches a new Claude Code process
- **Kill agents** — "Stop the designer, wrong approach"
  → Process killed, task goes back to OPEN
- **Talk to coordinator** — "This approach isn't working, replan"
  → Supervisor invokes coordinator with human feedback
- **Pause/resume** — "Pause everything while I review"
  → All agent spawning stops, running agents finish their current turn

### Coordinator Watches the Human Too

The coordinator doesn't just observe agents. It also:
- **Reacts to human directives** — if human posts "focus on X",
  coordinator adjusts assignment priorities
- **Accounts for human tasks** — if human claimed 2 tasks,
  coordinator doesn't overload them
- **Asks the human proactively** — when something uncertain comes up,
  coordinator posts a question to the board (not a blocking gate)
- **Surfaces summaries for the human** — "Researcher found X,
  architect found Y. Here's what I think we should do next."

### No Blocking, Ever

Discussions are async board posts. The human responds when they want.
Work continues on non-dependent tasks in the meantime. If a discussion
is urgent, the coordinator marks it HIGH priority — but it still
doesn't block execution.

The only thing that blocks the workspace is: the human explicitly
typing `pause`. Everything else is concurrent and non-blocking.
