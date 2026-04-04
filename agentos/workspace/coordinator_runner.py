"""CoordinatorRunner — launches the coordinator as a Claude Code instance.

Instead of raw API calls, the coordinator is a Tier 2 agent that can
read workspace files, use MCP comms tools, and produce structured
output files. Same infrastructure as worker agents, different prompt.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from agentos.comms.board_manager import BoardManager
from agentos.comms.comms_state import write_comms_state
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import AgentStatus, BoardPost, BoardSection, SpeechAct
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.schemas import BacklogTask, WorkspaceConfig

logger = logging.getLogger(__name__)

_COORDINATOR_ID = "coordinator"
_OUTPUT_DIR = "_coordinator_output"


def _run_coordinator_claude(
    prompt: str,
    workspace: Path,
    board: BoardManager,
    bus: MessageBus,
    workflow_id: str,
    max_turns: int = 15,
    project_dir: Path | None = None,
    status_fn=None,
) -> str:
    """Launch Claude Code as the coordinator and return raw output."""
    # Write comms state so coordinator can read the board
    pending = bus.receive(_COORDINATOR_ID)
    write_comms_state(workspace, board, pending, _COORDINATOR_ID, workflow_id)

    from agentos.adapters.tier2_shared import write_board_state
    write_board_state(workspace, board)

    # Ensure output dir exists
    output_dir = workspace / _OUTPUT_DIR
    output_dir.mkdir(exist_ok=True)

    comms_instructions = (
        "\n\n## Team Communication\n"
        "You have MCP tools for team communication:\n"
        "- **read_board**: See the shared workspace board\n"
        "- **post_to_board**: Share your plan with the team\n"
        "- **check_messages**: Check for messages from the human lead\n"
        "- **send_message**: Send a message to a team member\n\n"
        "Call read_board at the START to see the project context.\n"
    )

    full_prompt = prompt + comms_instructions

    cmd = [
        "claude", "--print",
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
        "--disallowedTools", "Agent,TodoWrite,ToolSearch",
    ]

    # Give coordinator access to the actual project codebase
    if project_dir and project_dir.exists():
        cmd.extend(["--add-dir", str(project_dir)])

    # Add MCP comms server
    mcp_config = json.dumps({
        "mcpServers": {
            "agentos-comms": {
                "command": sys.executable,
                "args": ["-m", "agentos.comms.mcp_server", "--workspace", str(workspace)],
                "env": {},
            }
        }
    })
    cmd.extend(["--mcp-config", mcp_config, "-p", full_prompt])

    logger.info("Launching coordinator (Claude Code)")

    # Stream with progress
    import threading

    result_text = ""
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(workspace),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

        def _read():
            nonlocal result_text
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    result_text = line
                elif event.get("type") == "assistant" and status_fn:
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            inp = block.get("input", {})
                            desc = _describe_coordinator_action(name, inp)
                            if desc:
                                status_fn(desc, "Coordinator")

        def _drain():
            for _ in proc.stderr:
                pass

        t_out = threading.Thread(target=_read, daemon=True)
        t_err = threading.Thread(target=_drain, daemon=True)
        t_out.start()
        t_err.start()
        proc.wait(timeout=600)
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        return result_text
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        logger.error("Coordinator timed out")
        return ""
    except FileNotFoundError:  # noqa: E722
        logger.error("claude CLI not found")
        return ""


def _describe_coordinator_action(name: str, inp: dict) -> str:
    """Human-readable description of a coordinator tool call."""
    if name == "Read":
        path = inp.get("file_path", inp.get("path", "?"))
        parts = path.replace("\\", "/").split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else path
        return f"📖 Reading {short}"
    if name == "Write":
        path = inp.get("file_path", inp.get("path", "?"))
        parts = path.replace("\\", "/").split("/")
        short = "/".join(parts[-2:]) if len(parts) > 2 else path
        return f"✏️  Writing {short}"
    if name == "Glob":
        return f"🔍 Finding: {inp.get('pattern', '?')}"
    if name == "Grep":
        return f"🔎 Searching: {inp.get('pattern', '?')[:40]}"
    if name == "Bash":
        cmd = inp.get("command", "?")
        return f"⚡ {cmd[:60]}"
    clean = name.replace("mcp__agentos-comms__", "").replace("mcp__agentos_comms__", "")
    if clean == "read_board":
        return "📋 Reading board"
    if clean == "post_to_board":
        return f"📋 Posting to board"
    if clean == "check_messages":
        return "💬 Checking messages"
    if clean == "send_message":
        return f"💬 Messaging {inp.get('to', '?')}"
    if clean == "report_progress":
        return f"📊 {inp.get('summary', 'progress')[:50]}"
    if name:
        return f"🔧 {name}"
    return ""


def run_decomposition(
    config: WorkspaceConfig,
    workspace: Path,
    board: BoardManager,
    bus: MessageBus,
    backlog: BacklogManager,
    workflow_id: str,
    project_dir: Path | None = None,
    status_fn=None,
    repo_map: str = "",
) -> list[BacklogTask]:
    """Launch coordinator to decompose the goal into tasks.

    The coordinator writes ``_coordinator_output/tasks.json`` with the
    decomposition. Returns the list of created BacklogTasks.
    """
    team_lines = []
    for p in config.team:
        roles = ", ".join(str(r) for r in p.roles)
        team_lines.append(f"- {p.name} ({p.type}, roles: {roles}): {p.specialization}")

    criteria = "\n".join(f"- {c}" for c in config.acceptance_criteria) or "None specified"
    docs = "\n".join(f"- {d}" for d in config.documents) or "None"

    repo_section = ""
    if repo_map:
        repo_section = (
            f"\n## Codebase Structure\n"
            f"The map below shows the project. You already have the full structure —\n"
            f"do NOT read files to understand the codebase. Use this map.\n\n"
            f"{repo_map}\n"
        )

    prompt = f"""You are the project coordinator. Your job is to decompose a goal into concrete, actionable tasks for your team. You do NOT execute tasks yourself — you plan and delegate.

## Goal
{config.goal}

## Description
{config.description or 'No additional description.'}

## Acceptance Criteria
{criteria}

## Team
{chr(10).join(team_lines) or 'No team members yet.'}
{repo_section}
## Documents Available
{docs}

## Instructions
1. Read the board for project context
2. Use the codebase map above — do NOT read files to explore the project
3. Decompose into specific, non-overlapping tasks
4. Write your task decomposition to `{_OUTPUT_DIR}/tasks.json` with this exact format:

```json
{{
  "plan_summary": "2-3 sentence overview of the approach",
  "tasks": [
    {{
      "title": "short task name",
      "description": "what to do (specific, actionable)",
      "suggested_for": "team member name or null",
      "depends_on_titles": ["other task titles this needs first"],
      "acceptance_criteria": ["how to verify done"],
      "estimated_minutes": 10,
      "priority": "high"
    }}
  ]
}}
```

5. Post your plan summary to the board using post_to_board

Rules:
- Tasks must be specific and non-overlapping
- Flag tasks over 35 minutes for decomposition
- Assign to team members based on their specialization
- Human team members get tasks requiring judgment or review
- The tasks.json file is REQUIRED — the system reads it to create the backlog"""

    board.update_agent_status(AgentStatus(
        agent_id=_COORDINATOR_ID, agent_name="Coordinator",
        role="Project coordination", state="running",
    ))

    _run_coordinator_claude(prompt, workspace, board, bus, workflow_id,
                            project_dir=project_dir, status_fn=status_fn)

    board.update_agent_status(AgentStatus(
        agent_id=_COORDINATOR_ID, agent_name="Coordinator",
        role="Project coordination", state="idle",
    ))

    # Parse output
    return _parse_decomposition(workspace, backlog)


def run_progress_check(
    config: WorkspaceConfig,
    workspace: Path,
    board: BoardManager,
    bus: MessageBus,
    backlog: BacklogManager,
    workflow_id: str,
) -> dict:
    """Launch coordinator to check progress and potentially replan.

    Returns the coordinator's assessment dict.
    """
    tasks = backlog.get_all_tasks()
    done = [t for t in tasks if t.status == "done"]
    active = [t for t in tasks if t.status not in ("done", "cancelled")]

    task_status_lines = []
    for t in tasks:
        assigned = f" → {t.assigned_to}" if t.assigned_to else ""
        task_status_lines.append(f"- [{t.status}] {t.title}{assigned}")

    prompt = f"""You are the project coordinator checking progress.

## Goal
{config.goal}

## Current Backlog
{chr(10).join(task_status_lines)}

## Status
Tasks done: {len(done)} / {len(tasks)}
Tasks remaining: {len(active)}

## Instructions
1. Read the board to see findings and team status
2. Assess whether progress is on track
3. If all tasks are done, assess whether the goal is met
4. Write your assessment to `{_OUTPUT_DIR}/assessment.json`:

```json
{{
  "assessment": "What's going well, what's stuck",
  "all_done": true/false,
  "goal_met": true/false,
  "recommendation": "complete" or "continue with X" or "needs human review",
  "new_tasks": [],
  "team_changes": []
}}
```

5. Post a status update to the board"""

    _run_coordinator_claude(prompt, workspace, board, bus, workflow_id, max_turns=10)

    # Parse assessment
    assessment_path = workspace / _OUTPUT_DIR / "assessment.json"
    if assessment_path.exists():
        try:
            data = json.loads(assessment_path.read_text())
            assessment_path.unlink()
            return data
        except json.JSONDecodeError:
            pass

    return {"assessment": "No assessment produced", "goal_met": False}


def _parse_decomposition(workspace: Path, backlog: BacklogManager) -> list[BacklogTask]:
    """Parse the coordinator's tasks.json and create backlog tasks."""
    tasks_path = workspace / _OUTPUT_DIR / "tasks.json"
    if not tasks_path.exists():
        logger.warning("Coordinator did not produce tasks.json")
        return []

    try:
        data = json.loads(tasks_path.read_text())
        tasks_path.unlink()  # Clean up
    except json.JSONDecodeError:
        logger.warning("Coordinator produced invalid tasks.json")
        return []

    plan_summary = data.get("plan_summary", "")
    tasks_data = data.get("tasks", [])

    if not tasks_data:
        logger.warning("Coordinator produced empty task list")
        return []

    # Build title→id map for dependency resolution
    title_to_id: dict[str, str] = {}
    tasks: list[BacklogTask] = []

    _VALID_PRIORITIES = {"low", "normal", "high", "critical"}
    _VALID_TIERS = {"haiku", "sonnet", "opus", None}

    for td in tasks_data:
        # Sanitize LLM output — models sometimes invent values
        raw_priority = td.get("priority", "normal")
        priority = raw_priority if raw_priority in _VALID_PRIORITIES else "normal"
        raw_tier = td.get("model_tier")
        model_tier = raw_tier if raw_tier in _VALID_TIERS else None

        task = BacklogTask(
            title=td.get("title", "Untitled"),
            description=td.get("description", ""),
            created_by="coordinator",
            suggested_for=td.get("suggested_for"),
            required_role=td.get("required_role"),
            acceptance_criteria=td.get("acceptance_criteria", []),
            estimated_minutes=td.get("estimated_minutes"),
            priority=priority,
            model_tier=model_tier,
        )
        title_to_id[task.title] = task.task_id
        tasks.append(task)

    # Resolve title-based dependencies to IDs
    for i, td in enumerate(tasks_data):
        dep_titles = td.get("depends_on_titles", [])
        tasks[i].depends_on = [
            title_to_id[t] for t in dep_titles if t in title_to_id
        ]

    # Register tasks in backlog
    for task in tasks:
        backlog.create_task(task)

    backlog.recompute_priorities()

    logger.info(
        "Coordinator created %d tasks. Plan: %s",
        len(tasks), plan_summary[:100],
    )
    return tasks
