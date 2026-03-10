"""Scoped workspace — path containment, file tracking, and event emission."""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.workspace import FileManifestEntry, FileOperation, WorkspaceConfig


class WorkspaceError(Exception):
    """Raised for workspace constraint violations."""


class Workspace:
    """Scoped workspace with path containment and file tracking.

    All file operations go through this class so that:
    1. Paths outside the workspace root are rejected.
    2. Glob patterns restrict which files an agent can access.
    3. Read-only workspaces block write operations.
    4. Every file operation is tracked in the manifest and emitted as an event.
    """

    def __init__(
        self,
        config: WorkspaceConfig,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._config = config
        self._root = Path(config.root).resolve()
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._manifest: list[FileManifestEntry] = []

    @property
    def root(self) -> Path:
        return self._root

    @property
    def read_only(self) -> bool:
        return self._config.read_only

    @property
    def manifest(self) -> list[FileManifestEntry]:
        return list(self._manifest)

    def ensure_root(self) -> None:
        """Create the workspace root directory if it doesn't exist."""
        self._root.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path within the workspace, enforcing containment.

        Raises WorkspaceError if the resolved path escapes the root.
        """
        resolved = (self._root / relative_path).resolve()
        if not self._is_contained(resolved):
            raise WorkspaceError(
                f"Path escapes workspace root: {relative_path!r} "
                f"resolves to {resolved}, outside {self._root}"
            )
        return resolved

    def check_pattern(self, relative_path: str) -> bool:
        """Check if a relative path matches any allowed pattern."""
        return any(
            fnmatch.fnmatch(relative_path, pattern)
            for pattern in self._config.allowed_patterns
        )

    def write_file(
        self,
        relative_path: str,
        content: str | bytes,
        agent_id: str,
        task_id: str,
    ) -> Path:
        """Write a file within the workspace.

        Raises WorkspaceError if read-only, path escapes root, or
        path doesn't match allowed patterns.
        """
        if self._config.read_only:
            raise WorkspaceError("Workspace is read-only")

        if not self.check_pattern(relative_path):
            raise WorkspaceError(
                f"Path {relative_path!r} does not match allowed patterns: "
                f"{self._config.allowed_patterns}"
            )

        target = self.resolve_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        is_new = not target.exists()
        operation = FileOperation.CREATED if is_new else FileOperation.MODIFIED

        if isinstance(content, str):
            target.write_text(content)
        else:
            target.write_bytes(content)

        size = target.stat().st_size
        self._record(relative_path, operation, agent_id, task_id, size)
        return target

    def read_file(self, relative_path: str) -> str:
        """Read a text file from the workspace.

        Raises WorkspaceError if path escapes root or doesn't match patterns.
        """
        if not self.check_pattern(relative_path):
            raise WorkspaceError(
                f"Path {relative_path!r} does not match allowed patterns: "
                f"{self._config.allowed_patterns}"
            )

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise WorkspaceError(f"File not found: {relative_path!r}")
        return target.read_text()

    def delete_file(
        self,
        relative_path: str,
        agent_id: str,
        task_id: str,
    ) -> None:
        """Delete a file from the workspace.

        Raises WorkspaceError if read-only, path escapes root, or
        path doesn't match allowed patterns.
        """
        if self._config.read_only:
            raise WorkspaceError("Workspace is read-only")

        if not self.check_pattern(relative_path):
            raise WorkspaceError(
                f"Path {relative_path!r} does not match allowed patterns: "
                f"{self._config.allowed_patterns}"
            )

        target = self.resolve_path(relative_path)
        if not target.exists():
            raise WorkspaceError(f"File not found: {relative_path!r}")

        size = target.stat().st_size
        target.unlink()
        self._record(relative_path, FileOperation.DELETED, agent_id, task_id, size)

    def list_files(self) -> list[str]:
        """List all files in the workspace as paths relative to root."""
        if not self._root.exists():
            return []
        return sorted(
            str(p.relative_to(self._root))
            for p in self._root.rglob("*")
            if p.is_file()
        )

    def query_manifest(self, task_id: str | None = None, agent_id: str | None = None) -> list[FileManifestEntry]:
        """Query file manifest entries, optionally filtered by task or agent."""
        entries = self._manifest
        if task_id is not None:
            entries = [e for e in entries if e.task_id == task_id]
        if agent_id is not None:
            entries = [e for e in entries if e.agent_id == agent_id]
        return entries

    def cleanup(self) -> None:
        """Remove the workspace root directory and all contents."""
        if self._root.exists():
            shutil.rmtree(self._root)

    def cleanup_task(self, task_name: str) -> None:
        """Remove a single task's subdirectory from the workspace."""
        task_dir = self._root / task_name
        if task_dir.exists() and task_dir.is_dir():
            shutil.rmtree(task_dir)

    def garbage_collect(self, failed_tasks: set[str]) -> None:
        """Remove workspace artifacts from failed tasks.

        Cleans up:
        - Task subdirectories for failed tasks
        - Temporary context files (.agentos_context/) for failed tasks
        """
        for task_name in failed_tasks:
            self.cleanup_task(task_name)

        # Clean up context files for failed tasks
        ctx_dir = self._root / ".agentos_context"
        if ctx_dir.exists():
            for task_name in failed_tasks:
                ctx_file = ctx_dir / f"{task_name}.json"
                if ctx_file.exists():
                    ctx_file.unlink()

    def _is_contained(self, resolved: Path) -> bool:
        """Check if a resolved path is inside the workspace root."""
        try:
            resolved.relative_to(self._root)
            return True
        except ValueError:
            return False

    def _record(
        self,
        path: str,
        operation: FileOperation,
        agent_id: str,
        task_id: str,
        size_bytes: int,
    ) -> None:
        """Record a file operation in the manifest and emit an event."""
        entry = FileManifestEntry(
            path=path,
            operation=operation,
            agent_id=agent_id,
            task_id=task_id,
            size_bytes=size_bytes,
        )
        self._manifest.append(entry)

        event_type = {
            FileOperation.CREATED: EventType.FILE_CREATED,
            FileOperation.MODIFIED: EventType.FILE_MODIFIED,
            FileOperation.DELETED: EventType.FILE_MODIFIED,  # No FILE_DELETED event type yet
        }[operation]

        self._event_log.append(Event(
            event_type=event_type,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "path": path,
                "operation": str(operation),
                "agent_id": agent_id,
                "task_id": task_id,
                "size_bytes": size_bytes,
            },
        ))
