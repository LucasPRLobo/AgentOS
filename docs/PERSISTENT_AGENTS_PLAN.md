# Persistent Agent Sessions — Implementation Plan

## The Change

**Current:** One subprocess per task. Agent spawns, works, terminates. No memory.

**New:** Agents maintain persistent sessions via `claude --continue`. Each message
or task is a new turn in an ongoing conversation. Agents remember everything.

## How Claude Code Sessions Work

```bash
# First turn: agent starts with a task
claude --print -p "You are researcher. Task: Research UX patterns" \
  --name "ws-researcher" --output-format stream-json

# Session is saved to disk automatically

# Second turn: human sends a DM
claude --print --continue -p "Human says: what are you finding?" \
  --name "ws-researcher" --output-format stream-json

# Agent sees full history + new message, responds, session updated

# Third turn: new task assigned
claude --print --continue -p "New task: Research AI agent dashboards" \
  --name "ws-researcher" --output-format stream-json
```

Each `--continue` picks up where the last session left off. Full context preserved.

## Agent Lifecycle (New)

```
IDLE ──(task assigned)──→ WORKING ──(task done)──→ IDLE
  │                          │                       │
  │                          │                       │
  ├──(DM arrives)──→ RESPONDING ──(replied)──→ IDLE  │
  │                                                  │
  └──(DM arrives)────────────────────────────────────┘
```

Agents are NEVER killed after completing a task. They go back to IDLE.
When a DM arrives, they wake up, respond, and go back to IDLE.
When a new task is assigned, they wake up, work, and go back to IDLE.

## Supervisor Changes

### Agent state tracking

```python
class PersistentAgent:
    agent_id: str
    session_name: str          # "ws-{workspace}-{agent_id}"
    state: "idle" | "working" | "responding"
    current_task_id: str | None
    current_proc: subprocess.Popen | None
    session_started: bool      # Has the first turn happened?
    pending_messages: list[str] # DMs queued while agent is working
```

### Supervisor tick changes

```python
async def _tick(self):
    # ... existing collect/react steps ...

    # NEW: Check for pending DMs to idle agents
    for agent_id, agent in self._agents.items():
        if agent.state == "idle" and agent.pending_messages:
            self._wake_agent_for_messages(agent)

    # NEW: Assign tasks to idle agents (not spawn new processes)
    ready = self._rt.backlog.get_ready_tasks()
    for task in ready:
        agent_id = self._pick_agent(task)
        if agent_id:
            agent = self._agents[agent_id]
            if agent.state == "idle":
                self._wake_agent_for_task(agent, task)
```

### Waking an agent

```python
def _wake_agent_for_task(self, agent: PersistentAgent, task: BacklogTask):
    """Resume the agent's session with a new task."""
    prompt = f"New task assigned: {task.title}\n{task.description}\n..."

    cmd = ["claude", "--print", "--output-format", "stream-json"]
    if agent.session_started:
        cmd.extend(["--continue", "--name", agent.session_name])
    else:
        cmd.extend(["--name", agent.session_name])
        agent.session_started = True

    cmd.extend(["-p", prompt])
    # ... launch, monitor, etc.

def _wake_agent_for_messages(self, agent: PersistentAgent):
    """Resume the agent's session to handle DMs."""
    messages = agent.pending_messages
    agent.pending_messages = []

    prompt = "You have messages from the team:\n\n"
    for msg in messages:
        prompt += f"From {msg['from']}: {msg['content']}\n"
    prompt += "\nRespond to each message using send_message, then wait for further instructions."

    cmd = ["claude", "--print", "--continue", "--name", agent.session_name,
           "--output-format", "stream-json", "-p", prompt]
    # ... launch, monitor, etc.
```

### DM routing change

When a human sends a DM to an agent:
- If agent is IDLE → wake immediately with the message
- If agent is WORKING → queue the message (agent will see it via check_messages + unread notification)
- If agent is RESPONDING → queue it (handled after current response)

## Implementation Steps

1. Add `PersistentAgent` tracking to supervisor
2. Change `_spawn_agent` → `_wake_agent_for_task` (uses --continue for subsequent turns)
3. Add `_wake_agent_for_messages` (DM handling)
4. Change `_on_agent_completed` → set state to IDLE instead of removing
5. Change DM routing to queue + wake pattern
6. Update TUI to show agent states: working/idle/responding
