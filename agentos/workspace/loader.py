"""Load workspace configuration from YAML files or dicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agentos.workspace.schemas import TeamMode, WorkspaceConfig


# Aliases for user-friendly YAML
_MODE_ALIASES: dict[str, str] = {
    "dynamic": TeamMode.SUGGEST,
    "manual": TeamMode.LOCKED,
    "auto": TeamMode.AUTO_FULL,
}


def load_workspace_config(path: Path) -> WorkspaceConfig:
    """Load a WorkspaceConfig from a YAML file."""
    raw = yaml.safe_load(path.read_text())
    data = raw.get("workspace", raw)

    # Resolve relative document paths
    base_dir = path.parent
    if "documents" in data:
        data["documents"] = [
            str((base_dir / d).resolve()) if not Path(d).is_absolute() else d
            for d in data["documents"]
        ]

    return load_workspace_config_from_dict(data)


def load_workspace_config_from_dict(data: dict[str, Any]) -> WorkspaceConfig:
    """Parse a dict into a WorkspaceConfig, handling aliases."""
    # Resolve team_mode aliases
    mode = data.get("team_mode", "suggest")
    data["team_mode"] = _MODE_ALIASES.get(mode, mode)

    # Resolve coordinator authority alias
    coord = data.get("coordinator", {})
    if isinstance(coord, dict):
        auth = coord.get("authority", "suggest")
        coord["authority"] = _MODE_ALIASES.get(auth, auth)

    return WorkspaceConfig(**data)
