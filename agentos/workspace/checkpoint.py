"""Workspace checkpoint — serialize and restore in-memory supervisor state.

The backlog (tasks.json) and board (board.json) are already persisted
continuously by BacklogManager and the supervisor write loop.  This module
handles the *in-memory gap*: agent states, task assignments, and supervisor
metadata that would otherwise be lost on process restart.

Checkpoint layout (.agentos/checkpoint.json):
    {
      "version": 1,
      "saved_at": "<iso>",
      "workspace_id": "...",
      "workflow_id": "...",
      "workspace_status": "active",
      "agent_states": {
        "<agent_id>": {
          "state": "idle" | "working" | "responding",
          "session_started": true,
          "current_task_id": null | "<task_id>"
        }
      },
      "task_assignments": {
        "<task_id>": "<agent_id>"
      },
      "in_progress_task_ids": ["<task_id>", ...],
      "tick_count": 42
    }

On resume:
- Task assignments are restored on BacklogTask objects already loaded from disk.
- In-progress tasks are reset to OPEN so agents re-claim them (or skip-coordinator
  mode lets the user pick up naturally via the existing backlog).
- ``session_started`` is restored so agents use ``--continue`` on their next turn.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentos.workspace.supervisor import WorkspaceSupervisor

logger = logging.getLogger(__name__)

CHECKPOINT_VERSION = 1
CHECKPOINT_FILENAME = "checkpoint.json"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_checkpoint(supervisor: "WorkspaceSupervisor", workspace_dir: Path) -> Path:
    """Serialize supervisor state to ``workspace_dir/.agentos/checkpoint.json``.

    Safe to call at any time — writes atomically via a temp file rename.
    Returns the path to the checkpoint file.
    """
    rt = supervisor._rt
    agentos_dir = workspace_dir / ".agentos"
    agentos_dir.mkdir(parents=True, exist_ok=True)

    # Collect agent states
    agent_states: dict[str, dict[str, Any]] = {}
    for agent_id, agent in supervisor._agents.items():
        agent_states[agent_id] = {
            "state": agent.state,
            "session_started": agent.session_started,
            "current_task_id": agent.current_task_id,
        }

    # Collect task assignments (tasks currently assigned to someone)
    task_assignments: dict[str, str] = {}
    in_progress_ids: list[str] = []
    try:
        for task in rt.backlog.get_all_tasks():
            if task.assigned_to:
                task_assignments[task.task_id] = task.assigned_to
            if task.status in ("in_progress", "claimed"):
                in_progress_ids.append(task.task_id)
    except Exception as exc:
        logger.warning("Checkpoint: failed reading backlog tasks: %s", exc)

    checkpoint: dict[str, Any] = {
        "version": CHECKPOINT_VERSION,
        "saved_at": _utc_now_iso(),
        "workspace_id": str(rt.state.workspace_id),
        "workflow_id": str(rt._workflow_id),
        "workspace_status": str(rt.state.status),
        "agent_states": agent_states,
        "task_assignments": task_assignments,
        "in_progress_task_ids": in_progress_ids,
        "tick_count": supervisor._tick_count,
    }

    checkpoint_path = agentos_dir / CHECKPOINT_FILENAME
    tmp_path = checkpoint_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(checkpoint, indent=2))
        tmp_path.replace(checkpoint_path)
        logger.info("Checkpoint saved: %s", checkpoint_path)
    except OSError as exc:
        logger.error("Checkpoint save failed: %s", exc)

    return checkpoint_path


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_checkpoint(workspace_dir: Path) -> dict[str, Any] | None:
    """Load and validate checkpoint from ``workspace_dir/.agentos/checkpoint.json``.

    Returns the checkpoint dict on success, or ``None`` if no checkpoint
    exists or it is invalid/corrupt.
    """
    checkpoint_path = workspace_dir / ".agentos" / CHECKPOINT_FILENAME
    if not checkpoint_path.exists():
        return None

    try:
        data = json.loads(checkpoint_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Checkpoint load failed (corrupt): %s", exc)
        return None

    if not isinstance(data, dict):
        logger.warning("Checkpoint load failed: not a dict")
        return None

    if data.get("version") != CHECKPOINT_VERSION:
        logger.warning(
            "Checkpoint version mismatch: got %s, expected %s",
            data.get("version"), CHECKPOINT_VERSION,
        )
        return None

    # Basic structure validation
    required_keys = {"saved_at", "agent_states", "task_assignments", "in_progress_task_ids"}
    missing = required_keys - set(data.keys())
    if missing:
        logger.warning("Checkpoint missing keys: %s", missing)
        return None

    logger.info(
        "Checkpoint loaded: saved_at=%s, agents=%d, tasks=%d, in_progress=%d",
        data.get("saved_at", "?"),
        len(data.get("agent_states", {})),
        len(data.get("task_assignments", {})),
        len(data.get("in_progress_task_ids", [])),
    )
    return data


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_checkpoint(supervisor: "WorkspaceSupervisor", checkpoint: dict[str, Any]) -> None:
    """Restore supervisor state from a loaded checkpoint.

    This is called *after* the backlog and board are already loaded from disk,
    so we only need to restore the in-memory agent tracking state.

    In-progress tasks are reset to OPEN so agents re-claim them naturally
    on the next supervisor tick.
    """
    rt = supervisor._rt

    # 1. Restore agent session state (so --continue works on next spawn)
    agent_states: dict[str, Any] = checkpoint.get("agent_states", {})
    for agent_id, state_data in agent_states.items():
        agent = supervisor._agents.get(agent_id)
        if agent is None:
            logger.debug("Checkpoint: agent %s not in current team, skipping", agent_id)
            continue
        agent.session_started = bool(state_data.get("session_started", False))
        # Always start agents as idle — processes don't survive restarts
        agent.state = "idle"
        agent.current_task_id = None
        agent.current_proc = None

    # 2. Reset in-progress tasks → OPEN so they get re-claimed
    in_progress_ids: list[str] = checkpoint.get("in_progress_task_ids", [])
    reset_count = 0
    for task_id in in_progress_ids:
        try:
            task = rt.backlog.get_task(task_id)
            # Only reset tasks that are still stuck in a transient state
            if task.status in ("in_progress", "claimed"):
                task.status = "open"          # type: ignore[assignment]
                task.assigned_to = None
                task.claimed_at = None
                reset_count += 1
                logger.debug("Checkpoint: reset task %s (%s) to open", task_id, task.title)
        except ValueError:
            logger.debug("Checkpoint: task %s no longer in backlog", task_id)

    if reset_count:
        logger.info("Checkpoint: reset %d in-progress tasks to open", reset_count)

    # 3. Restore tick count (cosmetic / logging)
    supervisor._tick_count = checkpoint.get("tick_count", 0)

    logger.info(
        "Checkpoint applied: %d agents restored, %d tasks reset to open",
        len(agent_states), reset_count,
    )


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_checkpoint(workspace_dir: Path) -> None:
    """Remove the checkpoint file (called after successful clean completion)."""
    checkpoint_path = workspace_dir / ".agentos" / CHECKPOINT_FILENAME
    try:
        checkpoint_path.unlink(missing_ok=True)
        logger.debug("Checkpoint deleted: %s", checkpoint_path)
    except OSError as exc:
        logger.warning("Could not delete checkpoint: %s", exc)


# ---------------------------------------------------------------------------
# Introspection (for TUI)
# ---------------------------------------------------------------------------


def checkpoint_summary(workspace_dir: Path) -> dict[str, Any] | None:
    """Return a human-readable summary dict of a checkpoint, or None.

    Keys: saved_at, agent_count, task_count, in_progress_count, workspace_status.
    """
    data = load_checkpoint(workspace_dir)
    if data is None:
        return None
    return {
        "saved_at": data.get("saved_at", "unknown"),
        "agent_count": len(data.get("agent_states", {})),
        "task_count": len(data.get("task_assignments", {})),
        "in_progress_count": len(data.get("in_progress_task_ids", [])),
        "workspace_status": data.get("workspace_status", "unknown"),
        "tick_count": data.get("tick_count", 0),
    }
