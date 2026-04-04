"""PersistentProcess — long-lived Claude Code process with stdin/stdout NDJSON.

Instead of launching a new subprocess per task, one process stays alive
for the entire workspace. Tasks, DMs, and commands are sent as messages
on stdin. The system prompt is loaded once; subsequent turns get cache
hits (~10% cost).

Protocol:
  stdin  → NDJSON lines: {"type":"user","message":{"role":"user","content":"..."}}\n
  stdout ← NDJSON lines: {"type":"assistant",...}, {"type":"result",...}
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class PersistentProcess:
    """A long-lived Claude Code process that accepts multiple turns via stdin."""

    def __init__(
        self,
        agent_id: str,
        cmd: list[str],
        cwd: str,
        on_tool_call: Callable | None = None,
        on_result: Callable | None = None,
        on_text: Callable | None = None,
    ):
        self.agent_id = agent_id
        self.state: str = "idle"
        self.current_task_id: str | None = None

        self._on_tool_call = on_tool_call   # fn(agent_id, name, input)
        self._on_result = on_result         # fn(agent_id, result_dict)
        self._on_text = on_text             # fn(agent_id, text)

        self._result_event = threading.Event()
        self._last_result: dict | None = None
        self._turn_text: str = ""

        # Launch process
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, cwd=cwd,
        )
        logger.info("PersistentProcess %s launched (pid=%d)", agent_id, self.proc.pid)

        # Background stdout reader
        self._reader = threading.Thread(
            target=self._read_stdout, daemon=True, name=f"stdout-{agent_id}",
        )
        self._reader.start()

        # Drain stderr
        threading.Thread(
            target=self._drain_stderr, daemon=True, name=f"stderr-{agent_id}",
        ).start()

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_message(self, content: str) -> None:
        """Send a user message to the process. Non-blocking."""
        if not self.is_alive:
            logger.warning("Cannot send to dead process %s", self.agent_id)
            return

        msg = {
            "type": "user",
            "message": {"role": "user", "content": content},
        }
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            logger.error("Failed to write to %s stdin: %s", self.agent_id, exc)
            return

        self._result_event.clear()
        self._last_result = None
        self._turn_text = ""

    # ------------------------------------------------------------------
    # Wait
    # ------------------------------------------------------------------

    def wait_for_result(self, timeout: float = 600) -> dict | None:
        """Block until the current turn completes. Returns result dict or None."""
        got_result = self._result_event.wait(timeout=timeout)
        if not got_result:
            logger.warning("Timeout waiting for %s result after %.0fs", self.agent_id, timeout)
        return self._last_result

    @property
    def turn_text(self) -> str:
        """The accumulated text output from the current/last turn."""
        return self._turn_text

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return self.proc.poll() is None

    @property
    def is_busy(self) -> bool:
        return self.state in ("working", "responding")

    @property
    def pid(self) -> int:
        return self.proc.pid

    # ------------------------------------------------------------------
    # Stdout reader (background thread)
    # ------------------------------------------------------------------

    def _read_stdout(self) -> None:
        """Continuously read stdout, parse NDJSON, dispatch events."""
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")

            if etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    btype = block.get("type", "")
                    if btype == "tool_use":
                        name = block.get("name", "")
                        inp = block.get("input", {})
                        if self._on_tool_call:
                            self._on_tool_call(self.agent_id, name, inp)
                    elif btype == "text":
                        text = block.get("text", "")
                        self._turn_text += text
                        if self._on_text:
                            self._on_text(self.agent_id, text)

            elif etype == "result":
                self._last_result = event
                if self._on_result:
                    self._on_result(self.agent_id, event)
                self._result_event.set()

        # Process exited — stdout closed
        logger.info("PersistentProcess %s stdout closed (pid=%d)", self.agent_id, self.proc.pid)

    def _drain_stderr(self) -> None:
        """Drain stderr to prevent pipe deadlock."""
        for line in self.proc.stderr:
            pass  # Discard stderr

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close stdin → process exits cleanly."""
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        logger.info("PersistentProcess %s closed", self.agent_id)

    def kill(self) -> None:
        """Force-kill the process."""
        self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
