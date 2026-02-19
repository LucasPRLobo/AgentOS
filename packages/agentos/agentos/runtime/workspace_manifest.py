"""WorkspaceManifest — thread-safe in-memory file tracker for workspaces."""

from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class WorkspaceFileEntry(BaseModel):
    """Metadata for a tracked workspace file."""

    path: str
    size_bytes: int
    modified: str  # ISO timestamp
    created_by_agent: str = ""
    sha256: str = ""


class WorkspaceManifest:
    """In-memory, thread-safe manifest of files in the workspace.

    Used by:
    - EventEmittingFileWriteTool to track file creation/modification
    - workspace_status tool to list workspace files
    - Workflow compiler to inject predecessor file context
    """

    def __init__(self) -> None:
        self._entries: dict[str, WorkspaceFileEntry] = {}
        self._lock = threading.Lock()

    def record_file(
        self,
        path: str,
        size: int,
        sha256: str,
        agent_name: str = "",
    ) -> tuple[bool, WorkspaceFileEntry]:
        """Record a file write. Returns (is_new, entry)."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            is_new = path not in self._entries
            entry = WorkspaceFileEntry(
                path=path,
                size_bytes=size,
                modified=now,
                created_by_agent=agent_name,
                sha256=sha256,
            )
            self._entries[path] = entry
            return is_new, entry

    def list_files(self) -> list[WorkspaceFileEntry]:
        """All tracked files, sorted by path."""
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.path)

    def files_by_agent(self, agent_name: str) -> list[WorkspaceFileEntry]:
        """Files created/modified by a specific agent."""
        with self._lock:
            return sorted(
                (e for e in self._entries.values() if e.created_by_agent == agent_name),
                key=lambda e: e.path,
            )

    def get_file(self, path: str) -> WorkspaceFileEntry | None:
        """Get entry for a specific file path."""
        with self._lock:
            return self._entries.get(path)

    def snapshot(self) -> dict[str, Any]:
        """Serialize the manifest for event payloads."""
        with self._lock:
            return {
                "file_count": len(self._entries),
                "files": [e.model_dump() for e in sorted(
                    self._entries.values(), key=lambda e: e.path,
                )],
            }

    def scan_workspace(self, root: Path) -> None:
        """Scan existing files on disk into the manifest (startup/recovery).

        Does not overwrite entries already recorded (e.g. from file events).
        """
        root = Path(root)
        if not root.exists():
            return

        hidden = {"events.db", "__pycache__", ".DS_Store"}
        with self._lock:
            for p in sorted(root.rglob("*")):
                if not p.is_file():
                    continue
                if any(part.startswith(".") or part in hidden for part in p.parts):
                    continue
                rel = str(p.relative_to(root))
                if rel in self._entries:
                    continue  # Don't overwrite known entries
                stat = p.stat()
                try:
                    content = p.read_bytes()
                    sha = hashlib.sha256(content).hexdigest()
                except OSError:
                    sha = ""
                self._entries[rel] = WorkspaceFileEntry(
                    path=rel,
                    size_bytes=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    sha256=sha,
                )
