"""Workspace persistence — save and restore state across sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agentos.workspace.schemas import (
    BacklogTask,
    WorkspaceConfig,
    WorkspaceState,
    WorkspaceStatus,
)

logger = logging.getLogger(__name__)

_STATE_DIR = ".agentos-workspace"


def save_workspace(
    workspace_dir: Path,
    config: WorkspaceConfig,
    state: WorkspaceState,
    tasks: list[BacklogTask],
) -> Path:
    """Save workspace state to disk. Returns the state directory path."""
    state_dir = workspace_dir / _STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)

    (state_dir / "config.json").write_text(config.model_dump_json(indent=2))
    (state_dir / "state.json").write_text(state.model_dump_json(indent=2))

    backlog_data = [t.model_dump(mode="json") for t in tasks]
    (state_dir / "backlog.json").write_text(json.dumps(backlog_data, indent=2))

    return state_dir


def load_workspace(workspace_dir: Path) -> dict | None:
    """Load workspace state from disk. Returns dict with config, state, tasks or None."""
    state_dir = workspace_dir / _STATE_DIR
    if not state_dir.exists():
        return None

    result = {}

    config_path = state_dir / "config.json"
    if config_path.exists():
        try:
            result["config"] = WorkspaceConfig(**json.loads(config_path.read_text()))
        except Exception as exc:
            logger.warning("Failed to load workspace config: %s", exc)
            return None

    state_path = state_dir / "state.json"
    if state_path.exists():
        try:
            result["state"] = WorkspaceState(**json.loads(state_path.read_text()))
        except Exception as exc:
            logger.warning("Failed to load workspace state: %s", exc)

    backlog_path = state_dir / "backlog.json"
    if backlog_path.exists():
        try:
            tasks_data = json.loads(backlog_path.read_text())
            result["tasks"] = [BacklogTask(**t) for t in tasks_data]
        except Exception as exc:
            logger.warning("Failed to load backlog: %s", exc)
            result["tasks"] = []

    return result if "config" in result else None


def workspace_exists(workspace_dir: Path) -> bool:
    """Check if a saved workspace state exists."""
    return (workspace_dir / _STATE_DIR / "config.json").exists()
