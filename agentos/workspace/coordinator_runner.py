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
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Agent,TodoWrite,ToolSearch",
    ]

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
    try:
        result = subprocess.run(
            cmd, cwd=str(workspace),
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0 and result.stderr:
            logger.warning("Coordinator stderr: %s", result.stderr[:300])
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error("Coordinator timed out")
        return ""
    except FileNotFoundError:
        logger.error("claude CLI not found")
        return ""


def run_decomposition(
    config: WorkspaceConfig,
    workspace: Path,
    board: BoardManager,
    bus: MessageBus,
    backlog: BacklogManager,
    workflow_id: str,
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

    prompt = f"""You are the project coordinator. Your job is to decompose a goal into concrete, actionable tasks for your team. You do NOT execute tasks yourself — you plan and delegate.

## Goal
{config.goal}

## Description
{config.description or 'No additional description.'}

## Acceptance Criteria
{criteria}

## Team
{chr(10).join(team_lines) or 'No team members yet.'}

## Documents Available
{docs}

## Instructions
1. Read the board for project context
2. Analyze the goal and team capabilities
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

    _run_coordinator_claude(prompt, workspace, board, bus, workflow_id)

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

    for td in tasks_data:
        task = BacklogTask(
            title=td.get("title", "Untitled"),
            description=td.get("description", ""),
            created_by="coordinator",
            suggested_for=td.get("suggested_for"),
            required_role=td.get("required_role"),
            acceptance_criteria=td.get("acceptance_criteria", []),
            estimated_minutes=td.get("estimated_minutes"),
            priority=td.get("priority", "normal"),
            model_tier=td.get("model_tier"),
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
