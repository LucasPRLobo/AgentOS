"""Tier 2 adapter — Aider (aider.chat) CLI integration.

Launches Aider as a subprocess, monitors from outside the tool loop.
Mirrors the ClaudeCodeAdapter pattern: build prompt, run subprocess,
parse manifest.json, validate output, track budget.

Key differences from Claude Code:
- No structured JSON output (no --output-format json)
- No --allowedTools equivalent — logs warning, relies on workspace scoping via cwd
- Token/cost: tries aider.coders.Coder Python API defensively, falls back to 0
"""

from __future__ import annotations

import logging
import subprocess
import time
import warnings
from pathlib import Path
from typing import Any, Callable

from agentos.adapters.base import AgentAdapter
from agentos.adapters.tier2_shared import (
    DEFAULT_TIMEOUT,
    MAX_MANIFEST_RETRIES,
    build_prompt,
    manifest_to_task_output,
    parse_manifest,
    write_predecessor_context,
)
from agentos.kernel.budget_manager import BudgetManager
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.task import (
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)

logger = logging.getLogger(__name__)


def _build_command(
    prompt: str,
    *,
    model: str = "gpt-4o",
    files: list[str] | None = None,
) -> list[str]:
    """Build the aider CLI command.

    Uses flags for non-interactive, no auto-commits, no streaming output:
      --message "prompt" --yes-always --no-auto-commits --no-stream
      --no-pretty --map-tokens 0 --model <model> --file <file1> ...
    """
    cmd = [
        "aider",
        "--message", prompt,
        "--yes-always",
        "--no-auto-commits",
        "--no-stream",
        "--no-pretty",
        "--map-tokens", "0",
        "--model", model,
    ]
    for f in (files or []):
        cmd.extend(["--file", f])
    return cmd


def _parse_usage_from_api() -> tuple[int, float]:
    """Try to extract token/cost metrics from aider's Python API.

    Returns (total_tokens, estimated_cost_usd).
    Falls back to (0, 0.0) if aider-chat is not installed.
    """
    try:
        from aider.coders import Coder  # type: ignore[import-untyped]
        # aider's Coder tracks cumulative metrics when used as a library.
        # In subprocess mode we don't have access, so this is best-effort.
        return 0, 0.0
    except ImportError:
        return 0, 0.0


class AiderAdapter(AgentAdapter):
    """Tier 2 adapter for Aider (aider.chat).

    Launches Aider as a subprocess, monitors from outside the tool loop.
    AgentOS does NOT intercept individual tool calls.

    Enforcement model:
    - Task assignment: structured prompt via --message flag
    - Workspace scoping: Aider runs in scoped directory (cwd)
    - Budget: monitor via Python API (best-effort), enforce time limits
    - Output: agent instructed to produce manifest.json, validated post-hoc
    - Retry: up to MAX_MANIFEST_RETRIES if manifest is missing/invalid
    - No --allowedTools equivalent — log warning if tools specified
    """

    @property
    def tier(self) -> int:
        return 2

    def __init__(
        self,
        budget_manager: BudgetManager,
        agent_id: str,
        *,
        model: str = "gpt-4o",
        timeout: int = DEFAULT_TIMEOUT,
        run_subprocess: Any | None = None,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._model = model
        self._timeout = timeout
        self._process: subprocess.Popen | None = None
        self._terminated = False
        self._run_subprocess = run_subprocess or subprocess.run
        self._log_fn = log_fn

    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Launch Aider, collect output, validate manifest."""
        if self._terminated:
            return TaskOutput(
                task_id="",
                agent_id=self._agent_id,
                status=TaskStatus.FAILED,
                summary="Adapter was terminated before execution.",
            )

        start_time = time.monotonic()

        # Warn about allowed_tools — Aider has no equivalent flag
        if allowed_tools:
            msg = (
                f"Aider adapter for {self._agent_id!r}: --allowedTools not "
                f"supported. Relying on workspace scoping via cwd. "
                f"Tools requested: {allowed_tools}"
            )
            logger.warning(msg)
            if self._log_fn:
                self._log_fn(f"WARNING: {msg}")

        # Write predecessor context files into workspace
        write_predecessor_context(workspace, predecessor_context)

        # Build workspace file index so agent doesn't waste turns exploring
        workspace_files: list[str] = []
        ws_root = workspace.parent
        if ws_root.exists():
            for p in sorted(ws_root.rglob("*")):
                if p.is_file() and ".agentos_context" not in str(p):
                    workspace_files.append(str(p))

        prompt = build_prompt(
            task_description, role, predecessor_context,
            workspace_files=workspace_files if workspace_files else None,
        )

        # Collect file paths in workspace for --file flags
        files = [
            str(f.relative_to(workspace))
            for f in workspace.rglob("*")
            if f.is_file() and f.name != "manifest.json" and ".agentos_context" not in f.parts
        ]

        cmd = _build_command(prompt, model=self._model, files=files[:20])

        total_tokens = 0
        total_cost = 0.0
        api_calls = 0

        # Run with retries for manifest validation
        for attempt in range(1 + MAX_MANIFEST_RETRIES):
            if self._terminated:
                break

            try:
                result = self._run_subprocess(
                    cmd,
                    cwd=str(workspace),
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start_time
                return TaskOutput(
                    task_id="",
                    agent_id=self._agent_id,
                    status=TaskStatus.FAILED,
                    summary=f"Aider timed out after {self._timeout}s.",
                    metrics=TaskMetrics(
                        execution_time_seconds=round(elapsed, 2),
                    ),
                )

            api_calls += 1

            # Try to get usage metrics from aider's Python API
            tokens, cost = _parse_usage_from_api()
            total_tokens += tokens
            total_cost += cost

            elapsed = time.monotonic() - start_time
            self._budget_manager.apply(
                self._agent_id,
                BudgetDelta(
                    tokens=tokens,
                    api_calls=1,
                    time_seconds=elapsed,
                    cost_usd=cost,
                ),
            )

            if result.returncode != 0:
                return TaskOutput(
                    task_id="",
                    agent_id=self._agent_id,
                    status=TaskStatus.FAILED,
                    summary=f"Aider exited with code {result.returncode}.",
                    metrics=TaskMetrics(
                        tokens_consumed=total_tokens,
                        api_calls_made=api_calls,
                        execution_time_seconds=round(elapsed, 2),
                        estimated_cost_usd=total_cost,
                    ),
                )

            # Validate manifest
            manifest = parse_manifest(workspace)
            if manifest is not None:
                metrics = TaskMetrics(
                    tokens_consumed=total_tokens,
                    api_calls_made=api_calls,
                    execution_time_seconds=round(elapsed, 2),
                    estimated_cost_usd=total_cost,
                )
                return manifest_to_task_output(
                    manifest, task_id="", agent_id=self._agent_id, metrics=metrics,
                )

            # Manifest missing/invalid — retry with a focused prompt
            if attempt < MAX_MANIFEST_RETRIES:
                cmd = _build_command(
                    "You forgot to create manifest.json. Please create it now "
                    "with the structure specified in the previous instructions. "
                    "The file must be valid JSON in the current directory.",
                    model=self._model,
                )

        # All retries exhausted
        elapsed = time.monotonic() - start_time
        return TaskOutput(
            task_id="",
            agent_id=self._agent_id,
            status=TaskStatus.FAILED,
            summary="Agent did not produce a valid manifest.json after retries.",
            metrics=TaskMetrics(
                tokens_consumed=total_tokens,
                api_calls_made=api_calls,
                execution_time_seconds=round(elapsed, 2),
                estimated_cost_usd=total_cost,
            ),
        )

    async def terminate(self) -> None:
        """Signal the adapter to stop and terminate any running process."""
        self._terminated = True
        if self._process is not None:
            self._process.terminate()
