"""Workflow run manager — start, cancel, and list active workflow runs."""

from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class RunManager:
    """Manages workflow run subprocesses.

    Spawns `agentos workflow run` as subprocesses, tracks them,
    and supports cancellation via SIGTERM.
    """

    def __init__(self) -> None:
        self._runs: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def start(
        self,
        workflow_yaml: str,
        *,
        live: bool = False,
        interactive: bool = False,
        db_path: str | None = None,
    ) -> str:
        """Start a workflow run as a subprocess.

        Args:
            workflow_yaml: YAML string to pass via stdin or temp file.
            live: Whether to use --live flag.
            interactive: Whether to use --interactive flag.
            db_path: Optional database path for the run.

        Returns:
            workflow_id placeholder (PID-based until real ID is available).
        """
        import tempfile

        # Write YAML to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix="agentos_run_"
        ) as f:
            f.write(workflow_yaml)
            yaml_path = f.name

        run_id = f"run-{uuid.uuid4().hex[:8]}"

        cmd = [sys.executable, "-m", "agentos.cli.main", "workflow", "run", yaml_path]
        cmd.extend(["--workflow-id", run_id])
        if live:
            cmd.append("--live")
        if interactive:
            cmd.append("--interactive")
        if db_path:
            cmd.extend(["--db", db_path])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with self._lock:
            self._runs[run_id] = proc

        logger.info("Started workflow run %s (PID %d)", run_id, proc.pid)
        return run_id

    def cancel(self, run_id: str) -> bool:
        """Cancel a running workflow by sending SIGTERM.

        Returns True if the process was found and signalled.
        """
        with self._lock:
            proc = self._runs.get(run_id)
        if proc is None:
            return False

        try:
            proc.send_signal(signal.SIGTERM)
            logger.info("Sent SIGTERM to run %s (PID %d)", run_id, proc.pid)
            return True
        except OSError:
            return False

    def list_active(self) -> list[dict[str, Any]]:
        """List all active (running) workflow runs."""
        self._reap()
        with self._lock:
            return [
                {"run_id": rid, "pid": proc.pid}
                for rid, proc in self._runs.items()
                if proc.poll() is None
            ]

    def _reap(self) -> None:
        """Remove finished processes from tracking."""
        with self._lock:
            finished = [
                rid for rid, proc in self._runs.items()
                if proc.poll() is not None
            ]
            for rid in finished:
                del self._runs[rid]
