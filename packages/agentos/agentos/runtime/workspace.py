"""Workspace — scoped directory and command abstraction for agent execution."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from pydantic import BaseModel, Field


class WorkspaceConfig(BaseModel):
    """Configuration for an agent workspace."""

    root: str = Field(description="Root directory path for the workspace")
    allowed_patterns: list[str] = Field(
        default_factory=lambda: ["**"],
        description="Glob patterns for allowed file paths (relative to root)",
    )
    allowed_commands: list[str] = Field(
        default_factory=list,
        description="Allowlist of base commands (e.g., ['python', 'git', 'pytest'])",
    )
    read_only: bool = Field(
        default=False,
        description="If True, only read operations are permitted",
    )


class Workspace:
    """Scoped workspace for agent execution.

    Enforces path containment within the root directory and command allowlisting.
    """

    def __init__(self, config: WorkspaceConfig) -> None:
        self._config = config
        self._root = Path(config.root).resolve()

    @property
    def root(self) -> Path:
        """Resolved root directory path."""
        return self._root

    @property
    def config(self) -> WorkspaceConfig:
        return self._config

    def resolve_path(self, path: str) -> Path:
        """Resolve a path relative to the workspace root.

        Raises ValueError if the resolved path escapes the workspace root.
        """
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(
                f"Path '{path}' resolves to '{resolved}' which is outside "
                f"workspace root '{self._root}'"
            ) from None
        return resolved

    def is_path_allowed(self, path: str) -> bool:
        """Check if a path is within the workspace root and matches allowed patterns."""
        try:
            resolved = self.resolve_path(path)
        except ValueError:
            return False

        # Get path relative to root for pattern matching
        relative = resolved.relative_to(self._root)
        relative_str = str(relative)

        return any(
            fnmatch.fnmatch(relative_str, pattern)
            for pattern in self._config.allowed_patterns
        )

    def is_command_allowed(self, command: str) -> bool:
        """Check if a command's base name is in the allowlist."""
        if not self._config.allowed_commands:
            return False
        # Extract the base command (first word)
        base_command = command.strip().split()[0] if command.strip() else ""
        return base_command in self._config.allowed_commands
