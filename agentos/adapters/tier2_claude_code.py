"""Tier 2 adapter — Claude Code CLI integration.

Launches Claude Code as a subprocess, monitors from outside the tool loop.
AgentOS does NOT intercept individual tool calls. Enforcement is at the
orchestration layer: workspace scoping, budget monitoring, structured
output validation post-hoc.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from agentos.adapters.base import AgentAdapter
from agentos.kernel.budget_manager import BudgetManager
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)

# Maximum retries when manifest.json is missing or invalid.
MAX_MANIFEST_RETRIES = 2

# Default timeout for a single Claude Code invocation (seconds).
DEFAULT_TIMEOUT = 120


def _build_prompt(
    task_description: str,
    role: str,
    predecessor_context: list[TaskOutput],
) -> str:
    """Assemble the full prompt sent to Claude Code via -p flag."""
    parts = []

    if role:
        parts.append(f"## Role\n{role}")

    parts.append(f"## Task\n{task_description}")

    if predecessor_context:
        parts.append("## Predecessor task outputs")
        for ctx in predecessor_context:
            parts.append(f"### Task: {ctx.task_id}")
            parts.append(f"Status: {ctx.status}")
            parts.append(f"Summary: {ctx.summary}")
            if ctx.key_findings:
                parts.append("Findings:")
                for f in ctx.key_findings:
                    parts.append(f"  - [{f.confidence}] {f.finding}")
            if ctx.open_questions:
                parts.append("Open questions:")
                for q in ctx.open_questions:
                    parts.append(f"  - {q}")
            parts.append("")

    parts.append(
        "## Output requirement\n"
        "When you are done, create a file called `manifest.json` in the "
        "current directory with this exact JSON structure:\n"
        "```json\n"
        "{\n"
        '  "summary": "1-3 sentence summary of what you accomplished",\n'
        '  "findings": [\n'
        '    {"finding": "what you found", "confidence": "high|medium|low", '
        '"sources": ["optional source refs"]}\n'
        "  ],\n"
        '  "open_questions": ["any unresolved questions"],\n'
        '  "files_produced": ["list of files you created or modified"]\n'
        "}\n"
        "```\n"
        "This manifest is REQUIRED. Do not skip it."
    )

    return "\n\n".join(parts)


def _write_predecessor_context(workspace: Path, predecessors: list[TaskOutput]) -> None:
    """Write predecessor TaskOutput manifests to workspace for reference."""
    if not predecessors:
        return
    ctx_dir = workspace / ".agentos_context"
    ctx_dir.mkdir(exist_ok=True)
    for ctx in predecessors:
        path = ctx_dir / f"{ctx.task_id}.json"
        path.write_text(ctx.model_dump_json(indent=2))


def _build_command(
    prompt: str,
    allowed_tools: list[str],
) -> list[str]:
    """Build the claude CLI command."""
    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "-p", prompt,
    ]
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    return cmd


def _build_env() -> dict[str, str]:
    """Build subprocess environment with anti-nesting guard stripped."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def _parse_usage(output: dict[str, Any]) -> tuple[int, float]:
    """Extract token count and cost from Claude Code JSON output.

    Returns (total_tokens, estimated_cost_usd).
    """
    # Claude Code JSON output may have various structures
    usage = output.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total = input_tokens + output_tokens

    cost = output.get("cost_usd", 0.0)
    if not cost and total:
        # Rough estimate if cost not provided
        cost = total * 3.0 / 1_000_000  # ~sonnet pricing

    return total, cost


def _parse_manifest(workspace: Path) -> dict[str, Any] | None:
    """Read and parse manifest.json from the workspace.

    Returns None if the file doesn't exist or is invalid JSON.
    """
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _manifest_to_task_output(
    manifest: dict[str, Any],
    task_id: str,
    agent_id: str,
    metrics: TaskMetrics,
) -> TaskOutput:
    """Convert a parsed manifest dict to a TaskOutput."""
    findings = []
    for f in manifest.get("findings", []):
        if isinstance(f, dict):
            findings.append(Finding(
                finding=f.get("finding", ""),
                confidence=Confidence(f.get("confidence", "medium")),
                sources=f.get("sources", []),
            ))

    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.SUCCEEDED,
        summary=manifest.get("summary", "Task completed."),
        key_findings=findings,
        open_questions=manifest.get("open_questions", []),
        metrics=metrics,
    )


class ClaudeCodeAdapter(AgentAdapter):
    """Tier 2 adapter for Claude Code CLI.

    Launches Claude Code as a subprocess, monitors from outside the tool loop.
    AgentOS does NOT intercept individual tool calls.

    Enforcement model:
    - Task assignment: structured prompt with role + task + output requirement
    - Workspace scoping: Claude Code runs in scoped directory (cwd)
    - Budget: monitor token usage from JSON output, enforce time limits
    - Output: agent instructed to produce manifest.json, validated post-hoc
    - Retry: up to MAX_MANIFEST_RETRIES if manifest is missing/invalid
    """

    @property
    def tier(self) -> int:
        return 2

    def __init__(
        self,
        budget_manager: BudgetManager,
        agent_id: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        run_subprocess: Any | None = None,
    ) -> None:
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._timeout = timeout
        self._process: subprocess.Popen | None = None
        self._terminated = False
        # Allow injecting a mock for subprocess.run in tests
        self._run_subprocess = run_subprocess or subprocess.run

    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Launch Claude Code, collect output, validate manifest."""
        if self._terminated:
            return TaskOutput(
                task_id="",
                agent_id=self._agent_id,
                status=TaskStatus.FAILED,
                summary="Adapter was terminated before execution.",
            )

        start_time = time.monotonic()

        # Write predecessor context files into workspace
        _write_predecessor_context(workspace, predecessor_context)

        prompt = _build_prompt(task_description, role, predecessor_context)
        cmd = _build_command(prompt, allowed_tools)
        env = _build_env()

        total_tokens = 0
        total_cost = 0.0
        api_calls = 0
        raw_output: dict[str, Any] = {}

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
                    env=env,
                )
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start_time
                return TaskOutput(
                    task_id="",
                    agent_id=self._agent_id,
                    status=TaskStatus.FAILED,
                    summary=f"Claude Code timed out after {self._timeout}s.",
                    metrics=TaskMetrics(
                        execution_time_seconds=round(elapsed, 2),
                    ),
                )

            api_calls += 1

            # Parse JSON output for usage metrics
            try:
                raw_output = json.loads(result.stdout) if result.stdout.strip() else {}
            except json.JSONDecodeError:
                raw_output = {}

            tokens, cost = _parse_usage(raw_output)
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
                    summary=f"Claude Code exited with code {result.returncode}.",
                    metrics=TaskMetrics(
                        tokens_consumed=total_tokens,
                        api_calls_made=api_calls,
                        execution_time_seconds=round(elapsed, 2),
                        estimated_cost_usd=total_cost,
                    ),
                )

            # Validate manifest
            manifest = _parse_manifest(workspace)
            if manifest is not None:
                metrics = TaskMetrics(
                    tokens_consumed=total_tokens,
                    api_calls_made=api_calls,
                    execution_time_seconds=round(elapsed, 2),
                    estimated_cost_usd=total_cost,
                )
                return _manifest_to_task_output(
                    manifest, task_id="", agent_id=self._agent_id, metrics=metrics,
                )

            # Manifest missing/invalid — retry with a focused prompt
            if attempt < MAX_MANIFEST_RETRIES:
                cmd = _build_command(
                    "You forgot to create manifest.json. Please create it now "
                    "with the structure specified in the previous instructions. "
                    "The file must be valid JSON in the current directory.",
                    allowed_tools,
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
