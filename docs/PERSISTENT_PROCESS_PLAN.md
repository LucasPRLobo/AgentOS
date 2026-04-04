# Persistent Agent Processes — Implementation Plan

## The Change

**Current:** Each task launches a new `claude --print` subprocess.
15 tasks = 15 cold starts = 15x full system prompt cost.

**New:** Each agent is ONE long-lived `claude --print --input-format
stream-json --output-format stream-json` process. Tasks, DMs, and
commands are sent as messages on stdin. The system prompt is loaded
once. Every subsequent turn gets cache hits (~10% cost).

## The Protocol

```
Launch:
  claude --print \
    --input-format stream-json \
    --output-format stream-json \
    --session-id <uuid> \
    --permission-mode bypassPermissions \
    --name "agentos-ws-<agent>" \
    --add-dir <project_dir> \
    --mcp-config <mcp_json>

Send task (stdin → process):
  {"type":"user","message":{"role":"user","content":"Task: Research UX patterns..."}}\n

Read response (process → stdout):
  {"type":"assistant","message":{"content":[{"type":"text","text":"..."},{"type":"tool_use",...}]}}\n
  {"type":"result","subtype":"success","duration_ms":1234}\n

Send DM (stdin → process):
  {"type":"user","message":{"role":"user","content":"Human says: what did you find?"}}\n

Process stays alive until workspace completes or stdin closes.
```

## Architecture

```
SUPERVISOR
├── _persistent_procs: dict[agent_id, PersistentProcess]
│   ├── researcher: Popen (stdin/stdout pipes, alive)
│   ├── designer:   Popen (stdin/stdout pipes, alive)
│   └── architect:  Popen (stdin/stdout pipes, alive)
│
│   On task ready:
│     proc.stdin.write(task_message + "\n")
│     → read stdout until "result" message
│     → process output, mark task done
│
│   On DM arrives:
│     proc.stdin.write(dm_message + "\n")
│     → read stdout until "result" message
│     → route response
│
│   On workspace complete:
│     close all stdin → processes exit
```

## Implementation Tasks

### Task 1: PersistentProcess class

**New class in:** `agentos/workspace/supervisor.py` (or separate file)

```python
class PersistentProcess:
    """A long-lived Claude Code process that accepts multiple turns via stdin."""

    def __init__(self, agent_id: str, cmd: list[str], cwd: str):
        self.agent_id = agent_id
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=cwd,
        )
        self.state = "idle"  # idle, working, responding
        self.current_task_id: str | None = None
        self._stdout_buffer: list[dict] = []
        self._result_event = threading.Event()
        self._last_result: dict | None = None

        # Background thread reads stdout continuously
        self._reader_thread = threading.Thread(
            target=self._read_stdout, daemon=True,
        )
        self._reader_thread.start()

        # Drain stderr
        threading.Thread(
            target=lambda: [None for _ in self.proc.stderr],
            daemon=True,
        ).start()

    def send_message(self, content: str) -> None:
        """Send a user message to the process (non-blocking write)."""
        import json
        msg = {
            "type": "user",
            "message": {"role": "user", "content": content},
        }
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        self._result_event.clear()

    def wait_for_result(self, timeout: float = 600) -> dict | None:
        """Block until the current turn completes (result message)."""
        self._result_event.wait(timeout=timeout)
        return self._last_result

    def _read_stdout(self) -> None:
        """Background: continuously read stdout, parse NDJSON events."""
        import json
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            self._stdout_buffer.append(event)

            # Emit tool call events for live display
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        self._on_tool_call(block)

            # Result = turn complete
            if event.get("type") == "result":
                self._last_result = event
                self._result_event.set()

    def _on_tool_call(self, block: dict) -> None:
        """Override point for emitting tool call events."""
        pass  # Supervisor hooks in here

    @property
    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        """Close stdin → process exits cleanly."""
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)
```

**~80 lines**

### Task 2: Launch persistent processes at workspace start

**Modify:** `supervisor.py` → `run()` method

Instead of spawning agents per task, launch one persistent process
per agent at workspace start:

```python
async def run(self):
    self._rt.start()

    # Write CLAUDE.md to workspace
    ...

    # Launch persistent processes for all agents
    for agent_id, agent in self._agents.items():
        self._launch_persistent(agent)

    # Send initial setup message to each agent
    for agent_id, agent in self._agents.items():
        setup_msg = (
            f"You are {agent_id}, a team member in an AgentOS workspace.\n"
            f"You are part of a team working on: {self._rt.config.goal}\n\n"
            f"## Codebase\n{self._repo_map}\n\n"
            f"## Communication\n"
            f"You have MCP tools: read_board, post_to_board, check_messages, "
            f"send_message, report_progress.\n"
            f"Check the board and messages frequently.\n\n"
            f"Wait for task assignments. I'll send them as messages."
        )
        self._persistent[agent_id].send_message(setup_msg)
        self._persistent[agent_id].wait_for_result(timeout=120)

    # Coordinator decomposition (if needed)
    ...

    # Main supervisor loop (same as before, but spawning is now sending)
    while active:
        await self._tick()
        await asyncio.sleep(self._config.poll_interval)
```

**~40 lines changes**

### Task 3: Replace _spawn_agent with send_task

**Modify:** `supervisor.py`

Current `_spawn_agent()` launches a new subprocess. Replace with
sending a message to the existing persistent process:

```python
def _assign_task(self, agent_id: str, task: BacklogTask) -> None:
    """Assign a task to a persistent agent process."""
    proc = self._persistent.get(agent_id)
    if not proc or not proc.is_alive:
        # Restart if dead
        self._launch_persistent(self._agents[agent_id])
        proc = self._persistent[agent_id]

    # Claim task
    self._rt.claim_task(task.task_id, agent_id)
    self._rt.backlog.start_task(task.task_id)

    # Build context
    context = ""
    if self._rt._curator:
        ctx = self._rt._curator.curate(task)
        context = self._rt._curator.render_prompt_section(ctx)

    # Send task as a message
    msg = (
        f"New task assigned:\n\n"
        f"## {task.title}\n{task.description}\n\n"
        f"{context}\n\n"
        f"Complete this task. Post findings to the board. "
        f"Check messages frequently."
    )

    proc.state = "working"
    proc.current_task_id = task.task_id
    proc.send_message(msg)

    self._emit_event("agent_spawned", {
        "agent": agent_id, "task": task.title,
    })
```

**~40 lines**

### Task 4: Collect results from persistent processes

**Modify:** `supervisor.py` → `_tick()`

Instead of polling `proc.poll()` for process completion, check if
any persistent process has finished its current turn:

```python
async def _tick(self):
    # 1. Check for completed turns
    for agent_id, proc in self._persistent.items():
        if proc.state == "working" and proc._result_event.is_set():
            self._on_turn_completed(agent_id, proc)

    # 2. Collect outboxes, human commands (same as before)
    ...

    # 3. Assign tasks to idle agents
    for task in ready_tasks:
        agent_id = self._pick_agent(task)
        if agent_id:
            agent_proc = self._persistent.get(agent_id)
            if agent_proc and agent_proc.state == "idle":
                self._assign_task(agent_id, task)

def _on_turn_completed(self, agent_id: str, proc: PersistentProcess):
    """Handle a completed turn from a persistent agent."""
    task_id = proc.current_task_id
    proc.state = "idle"
    proc.current_task_id = None
    proc._result_event.clear()

    if task_id and task_id != "dm-response":
        # Complete the task (same logic as before)
        # Detect new files, parse manifest, mark done
        ...

    # Agent is now idle — ready for next task or DM
```

**~60 lines**

### Task 5: DM handling via stdin

**Modify:** `supervisor.py`

DMs become trivially simple — just send a message to the process:

```python
def _send_dm_to_agent(self, agent_id: str, messages: list[dict]) -> None:
    """Send DM to a persistent agent. No restart needed."""
    proc = self._persistent.get(agent_id)
    if not proc or not proc.is_alive:
        return

    msg_text = "\n".join(
        f"From {m.get('from', '?')}: {m.get('content', '')}"
        for m in messages
    )

    if proc.state == "idle":
        # Agent is free — send directly
        proc.state = "responding"
        proc.current_task_id = "dm-response"
        proc.send_message(
            f"You have direct messages. Respond using send_message.\n\n"
            f"{msg_text}\n\n"
            f"After responding, wait for the next task."
        )
    else:
        # Agent is working — queue for later
        # The agent will see it via check_messages MCP tool
        # (inbox file is already written by the supervisor)
        pass
```

**No more killing processes, no more --continue restarts.**

**~30 lines**

### Task 6: Coordinator as persistent process

The coordinator also becomes a persistent process:

```python
def _launch_coordinator(self):
    """Launch the coordinator as a persistent stream-json process."""
    cmd = self._build_persistent_cmd("coordinator")
    self._coordinator_proc = PersistentProcess("coordinator", cmd, cwd)

    # Setup message
    setup = (
        f"You are the workspace coordinator for '{self._rt.config.name}'.\n"
        f"Your job: manage the team, answer human questions, report progress.\n"
        f"You maintain an ongoing conversation with the human lead.\n\n"
        f"## Codebase\n{self._repo_map}\n\n"
        f"## Team\n{team_list}\n\n"
        f"Wait for messages from the human."
    )
    self._coordinator_proc.send_message(setup)
    self._coordinator_proc.wait_for_result(timeout=120)

def _run_coordinator_response(self, human_messages):
    """Send human message to coordinator — instant, no new process."""
    text = "\n".join(human_messages)

    # Brief state context
    tasks = self._rt.backlog.get_all_tasks()
    done = sum(1 for t in tasks if t.status == "done")
    active = ", ".join(self._active.keys()) or "none"

    msg = (
        f"Human says: {text}\n\n"
        f"[State: {done}/{len(tasks)} tasks, active: {active}]"
    )
    self._coordinator_proc.send_message(msg)
    # Response arrives via stdout → routed to board
```

**~50 lines**

### Task 7: Tool call streaming from persistent processes

The `PersistentProcess._read_stdout()` runs in a background thread
and collects all events. We need to hook into it for live display:

```python
class PersistentProcess:
    def __init__(self, agent_id, cmd, cwd, on_tool_call=None,
                 on_result=None):
        self._on_tool_call_cb = on_tool_call  # fn(agent_id, name, input)
        self._on_result_cb = on_result        # fn(agent_id, result)
        ...

    def _on_tool_call(self, block):
        if self._on_tool_call_cb:
            self._on_tool_call_cb(
                self.agent_id,
                block.get("name", ""),
                block.get("input", {}),
            )
```

The supervisor creates processes with callbacks:

```python
def _launch_persistent(self, agent):
    proc = PersistentProcess(
        agent.agent_id, cmd, cwd,
        on_tool_call=self._handle_tool_call,
        on_result=self._handle_result,
    )

def _handle_tool_call(self, agent_id, name, inp):
    desc = self._describe_tool_call(name, inp)
    if desc:
        self._emit_event("agent_activity", {
            "agent": agent_id, "activity": desc,
        })
```

**~30 lines**

### Task 8: Graceful shutdown

When workspace completes, close all stdin pipes:

```python
def _shutdown_all(self):
    """Close all persistent processes gracefully."""
    for proc in self._persistent.values():
        proc.close()
    if self._coordinator_proc:
        self._coordinator_proc.close()
```

**~10 lines**

### Task 9: Fallback for crashed processes

If a persistent process crashes (exits unexpectedly), restart it:

```python
def _check_process_health(self):
    """Restart any crashed persistent processes."""
    for agent_id, proc in self._persistent.items():
        if not proc.is_alive:
            logger.warning("Agent %s process died — restarting", agent_id)
            self._launch_persistent(self._agents[agent_id])
            self._emit_event("agent_restarted", {"agent": agent_id})
```

Add to `_tick()`:

```python
async def _tick(self):
    self._check_process_health()
    ...
```

**~15 lines**

---

## Summary

| Task | What | Lines |
|---|---|---|
| 1. PersistentProcess class | stdin/stdout NDJSON protocol, result tracking | ~80 |
| 2. Launch at workspace start | One process per agent, setup message | ~40 |
| 3. Replace spawn with send | Task assignment via stdin message | ~40 |
| 4. Collect results | Poll result events, complete tasks | ~60 |
| 5. DM handling | Send DM via stdin, no restart | ~30 |
| 6. Coordinator persistent | Coordinator as stream-json process | ~50 |
| 7. Tool call streaming | Callbacks from stdout reader | ~30 |
| 8. Graceful shutdown | Close stdin on workspace end | ~10 |
| 9. Crash recovery | Detect dead processes, restart | ~15 |
| **Total** | | **~355** |

## Expected Impact

| Metric | Current (--print per task) | After (stream-json persistent) |
|---|---|---|
| Process launches per run | 15-20 (tasks + DMs + coordinator) | 3-4 (one per agent + coordinator) |
| System prompt cost | Full cost × 15-20 = ~750K-1M tokens | Full cost × 4 = ~200K tokens |
| Cache hits | None (cold start each time) | ~90% after turn 1 |
| DM response | Kill + restart + --continue (~20K) | stdin message (~500 tokens) |
| Coordinator response | New process each time (~5K) | stdin message (~500 tokens) |
| Total per run | ~400-500K tokens | ~80-120K tokens |
| Plan usage per run | ~30% | ~5-8% |
| DM latency | 10-30 seconds (process startup) | 2-5 seconds (stdin write) |

## Dependency Order

```
Task 1 (PersistentProcess) ──→ Task 2 (launch at start)
                           ──→ Task 7 (tool call streaming)
Task 2 ──→ Task 3 (replace spawn)
       ──→ Task 6 (coordinator)
Task 3 ──→ Task 4 (collect results)
Task 4 ──→ Task 5 (DM handling)
Task 8 + Task 9 ──→ after everything else
```

Tasks 1→2→3→4 are the critical path.
Tasks 5, 6, 7 can be done in parallel after Task 2.
Tasks 8, 9 are finishing touches.
