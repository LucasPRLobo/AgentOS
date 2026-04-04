# Next Steps Implementation Plan

---

## 1. Persistent Coordinator Session

### Problem

The coordinator is stateless. Each human message triggers a fresh
`claude --print -p "..." --max-turns 1` invocation. The coordinator
doesn't remember previous messages, decisions, or context. If you ask
"what did we decide earlier?" it has no idea.

### Solution

Use the same `--continue` pattern as worker agents. The coordinator
gets a `PersistentAgent` entry with a named session. First invocation
sets up the session; subsequent messages resume it.

### Changes

#### supervisor.py

**Add coordinator to PersistentAgent tracking:**
```python
# In __init__, after agent loop:
self._coordinator_agent = PersistentAgent("coordinator", wf_id)
```

**Rewrite `_run_coordinator_response()`:**

Current (stateless, fresh each time):
```python
cmd = ["claude", "--print", "--output-format", "text",
       "--max-turns", "1", "--model", "sonnet", "-p", prompt]
result = subprocess.run(cmd, ...)
```

New (persistent session):
```python
cmd = ["claude", "--print", "--output-format", "text",
       "--max-turns", "3", "--model", "sonnet",
       "--name", self._coordinator_agent.session_name]
if self._coordinator_agent.session_started:
    cmd.append("--continue")
else:
    self._coordinator_agent.session_started = True
cmd.extend(["-p", prompt])
result = subprocess.run(cmd, ...)
```

**First-turn coordinator prompt (sets up the role):**
```
You are the workspace coordinator for "{workspace_name}".
Your job: manage the team, answer human questions, report progress,
adjust plans when asked. You maintain an ongoing conversation with
the human lead.

## Codebase
{repo_map}

## Team
{team_list}

## Current State
{board_compact}
{task_summary}

The human will message you. Respond conversationally — 2-4 sentences.
Be helpful, specific, and aware of what the team is doing.
```

**Subsequent-turn prompt (just the new message):**
```
The human says: "{message}"

Current state:
Active agents: {active_list}
Tasks: {done}/{total} done

Respond conversationally. If they asked a question, answer it.
If they gave a directive, acknowledge it and explain how you'll act.
```

The subsequent prompt is much smaller because the coordinator already
has the full context from the first turn + all previous messages.

**Token savings:** First turn ~2K tokens (repo map + setup). Each
subsequent response ~500 tokens (just the message + brief state).
Currently each response costs ~2K tokens (full state every time).

#### Changes summary

| File | Change | Lines |
|---|---|---|
| `supervisor.py` | Add `_coordinator_agent`, rewrite `_run_coordinator_response`, add first-turn setup | ~60 |
| Tests | Test coordinator remembers context across messages | ~30 |

---

## 2. Blank Workspace Flow

### Problem

Starting a workspace requires a YAML file with team, budget, goals
defined upfront. The user has to know the team structure before
the project begins. This is backwards — the coordinator should
help the user figure out the team.

### Solution

The TUI starts with just the coordinator. The human describes what
they want, the coordinator proposes a team, the human approves,
and the workspace initializes.

### Flow

```
$ agentos

 AgentOS │ New Workspace
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 COORDINATOR
 coordinator: Hi! What would you like to work on?

 > I need to research and design a dashboard frontend

 coordinator: Got it. For a dashboard design project, I'd suggest:
   🔍 ui-researcher — UX patterns + competitor analysis
   🎨 designer — layout, components, interaction design
   🏗️ architect — React architecture, state, WebSocket
   👤 you — review + direction
 Budget: ~$8 for research + design
 Should I set up this team?

 > Yes but add a writer for docs too

 coordinator: Updated:
   🔍 ui-researcher
   🎨 designer
   🏗️ architect
   ✍️  writer — technical documentation
   👤 you
 Setting up workspace...

 coordinator: Workspace ready. Decomposing the goal into tasks...
 [agents start spawning]
```

### Implementation

#### New entry point: `examples/agentos_start.py` (or modify workspace_live.py)

Accept no arguments — start blank:
```
python examples/workspace_live.py
# or
python examples/workspace_live.py --new
```

#### Phase 1: Coordinator-only conversation

Before the supervisor starts, run a coordinator conversation to
establish the workspace config:

```python
class WorkspaceTUI(App):
    async def on_mount(self):
        if self.yaml_path:
            # Existing flow: load from YAML
            ...
        else:
            # Blank flow: conversation with coordinator
            self._start_blank_workspace()

    def _start_blank_workspace(self):
        self._add_to_view("home", "[yellow]coordinator[/]: Hi! What would you like to work on?")
        self._mode = "setup"  # Special mode: messages go to setup coordinator
```

#### Phase 2: Setup coordinator

A specialized coordinator session that:
1. Asks what the user wants to do
2. Proposes a team (agent names, roles, specializations)
3. Suggests a budget
4. Waits for approval
5. Outputs a workspace config as JSON

```python
def _run_setup_coordinator(self, user_messages: list[str]) -> dict:
    """Run the setup coordinator to build a workspace config."""
    prompt = f"""You are the AgentOS setup coordinator. The user wants to start a new project.

Based on their description, propose a workspace configuration.

User messages so far:
{chr(10).join(user_messages)}

Respond conversationally AND output a JSON config when ready:
{{
  "ready": true/false,
  "response": "your conversational message",
  "config": {{
    "name": "Project Name",
    "goal": "what the project aims to do",
    "team": [
      {{"name": "agent-name", "type": "agent", "specialization": "what they do"}},
      {{"name": "human-name", "type": "human"}}
    ],
    "budget": {{"max_cost_usd": 8.0}}
  }}
}}

If the user hasn't given enough info yet, set ready=false and ask questions.
If they've approved the team, set ready=true and include the full config.
"""
    cmd = ["claude", "--print", "--output-format", "text",
           "--max-turns", "1", "--model", "sonnet",
           "--name", "agentos-setup", "-p", prompt]
    if self._setup_started:
        cmd.insert(-2, "--continue")
    ...
```

#### Phase 3: Config → workspace

Once the coordinator outputs `ready: true`, parse the config and
create a `WorkspaceConfig` from it:

```python
def _apply_setup_config(self, config_dict: dict):
    """Create workspace from coordinator's proposed config."""
    from agentos.workspace.schemas import WorkspaceConfig, WorkspaceParticipant

    team = [
        WorkspaceParticipant(
            name=t["name"], type=t.get("type", "agent"),
            specialization=t.get("specialization", ""),
        )
        for t in config_dict.get("team", [])
    ]
    config = WorkspaceConfig(
        name=config_dict.get("name", "New Workspace"),
        goal=config_dict.get("goal", ""),
        team=team,
        budget=BudgetSpec(**config_dict.get("budget", {})),
    )
    # Initialize runtime with this config
    self.runtime = WorkspaceRuntime(config, ...)
    self.run_supervisor()
```

#### Changes summary

| File | Change | Lines |
|---|---|---|
| `workspace_live.py` | Blank mode, setup coordinator conversation, config parsing | ~120 |
| `workspace_live.py` | `--new` flag, no-argument start | ~10 |
| Tests | Manual testing (interactive flow) | — |

---

## 3. Agent Response Reliability

### Problem

Agents sometimes don't respond to DMs even with the interrupt
mechanism. Root causes:

1. **Timing:** DM arrives while agent is between tool calls.
   `check_messages` reads and clears the inbox, but the message
   arrived after the last `check_messages` and before the next one.

2. **Clearing on read:** `read_agent_inbox` was clearing messages
   on read (fixed — no longer clears). But the MCP `_read_state()`
   might still consume them.

3. **Agent ignores the directive:** Even with "you MUST reply",
   the agent sometimes continues its task without responding.
   Claude Code agents are not guaranteed to follow instructions.

4. **Interrupt timing:** `_interrupt_for_messages` kills the process,
   but `--continue` resumes from the last completed turn, not
   mid-turn. Work done in the interrupted turn is lost.

### Solutions

#### Fix 3a: Don't clear inbox in MCP `_read_state()`

Current: `_read_state()` calls `read_agent_inbox()` which used to
clear on read. We fixed the default to `clear=False`, but verify
it's working correctly end-to-end.

**Verify:** The MCP `_read_state()` at line 82 calls
`read_agent_inbox(ws, agent_id)` — this should NOT clear. Confirmed:
the default is `clear=False` after our fix.

**But:** Multiple `check_messages` calls show the same messages
repeatedly. The agent sees "You have 1 message" every time it checks.
This is actually fine — better to see the message twice than miss it.

To avoid confusion, track which messages the agent has already seen:

```python
# In _read_state(), after reading inbox:
# Mark messages as "delivered" (but don't remove)
inbox = read_agent_inbox(ws, agent_id)
# Filter to only undelivered
undelivered = [m for m in inbox if not m.get("_delivered")]
# Mark as delivered
for m in inbox:
    m["_delivered"] = True
write_agent_inbox_raw(ws, agent_id, inbox)  # Write back with marks
```

#### Fix 3b: Stronger interrupt prompt

Current interrupt prompt:
```
IMPORTANT: You have urgent messages from the team.
Stop what you're doing and respond to them FIRST using send_message.
```

Stronger version:
```
CRITICAL INTERRUPT: The human lead has sent you a direct message.
You MUST respond using send_message BEFORE doing anything else.
Do NOT continue your previous task until you have responded.

Message from human: "{content}"

After responding, you may continue your previous work.
```

#### Fix 3c: Verify response was sent

After the interrupt agent process completes, check the outbox
for a `send_message` to the human. If no response was sent,
log a warning and optionally retry.

```python
def _on_agent_completed(self, info):
    if info.task_id == "dm-response":
        # Check if the agent actually responded
        from agentos.comms.comms_state import read_agent_outbox
        outbox = read_agent_outbox(self._rt._workspace_dir, info.agent_id)
        responded = any(
            m.get("to") == "human" for m in outbox
        )
        if not responded:
            logger.warning("Agent %s did not respond to DM", info.agent_id)
            # Could retry or notify the human
```

#### Fix 3d: Graceful interrupt (SIGTERM before SIGKILL)

Current: `agent.current_proc.terminate()` sends SIGTERM, waits 5s,
then SIGKILL. Claude Code should handle SIGTERM gracefully — it saves
the session before exiting. Verify this works with `--continue`.

#### Changes summary

| File | Change | Lines |
|---|---|---|
| `supervisor.py` | Stronger interrupt prompt | ~10 |
| `supervisor.py` | Verify response sent after DM completion | ~15 |
| `comms_state.py` | Message delivery tracking (mark as delivered) | ~20 |
| `mcp_server.py` | Filter to undelivered messages in check_messages | ~10 |
| Tests | Test DM → interrupt → response → resume flow | ~40 |

---

## Implementation Order

```
Step 1 (Persistent coordinator) ──→ independent, do first
Step 2 (Blank workspace) ─────────→ depends on Step 1 (coordinator session)
Step 3 (Response reliability) ────→ independent, do alongside 1 or 2
```

Step 1 is the foundation for Step 2 (blank workspace needs a persistent
coordinator to have a setup conversation). Step 3 is independent.

## Total Scope

| Step | Lines (est.) |
|---|---|
| 1. Persistent coordinator | ~90 |
| 2. Blank workspace | ~130 |
| 3. Response reliability | ~95 |
| **Total** | **~315** |
