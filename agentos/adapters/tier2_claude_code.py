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
import threading
import time
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

# Re-export for backward compatibility with existing tests.
_build_prompt = build_prompt
_write_predecessor_context = write_predecessor_context
_parse_manifest = parse_manifest
_manifest_to_task_output = manifest_to_task_output


def _build_command(
    prompt: str,
    allowed_tools: list[str],
    *,
    output_format: str = "json",
    max_turns: int = 30,
) -> list[str]:
    """Build the claude CLI command."""
    cmd = [
        "claude",
        "--print",
        "--output-format", output_format,
        "--max-turns", str(max_turns),
    ]
    # stream-json requires --verbose in --print mode
    if output_format == "stream-json":
        cmd.append("--verbose")
    cmd.extend(["-p", prompt])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    else:
        # SECURITY: If no tools are specified, restrict to a safe baseline.
        # Without --allowedTools, Claude Code gives the agent ALL tools
        # including Bash, which violates the governance model.
        cmd.extend(["--allowedTools", "Read,Write,Edit,Glob,Grep"])
    # Always block Agent and TodoWrite — these are Claude Code built-in tools
    # that spawn uncontrolled sub-agents or manage internal state we don't track.
    cmd.extend(["--disallowedTools", "Agent,TodoWrite,ToolSearch"])
    return cmd


def _extract_tool_names(event: dict[str, Any]) -> list[str]:
    """Extract tool names used in a stream event."""
    tools: list[str] = []
    if event.get("type") == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                if name:
                    tools.append(name)
    return tools


def _format_stream_event(event: dict[str, Any]) -> str | None:
    """Format a stream-json event as a human-readable log line, or None to skip."""
    etype = event.get("type", "")

    if etype == "assistant":
        msg = event.get("message", {})
        parts = []
        for block in msg.get("content", []):
            btype = block.get("type", "")
            if btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                if name in ("Read", "file_read"):
                    parts.append(f"Read {inp.get('file_path', inp.get('path', ''))}")
                elif name in ("Write", "file_write"):
                    parts.append(f"Write {inp.get('file_path', inp.get('path', ''))}")
                elif name in ("Bash", "shell_exec"):
                    parts.append(f"Bash: {inp.get('command', '')[:80]}")
                elif name in ("WebSearch", "web_search"):
                    parts.append(f"Search: {inp.get('query', '')[:80]}")
                elif name == "WebFetch":
                    parts.append(f"Fetch: {inp.get('url', '')[:60]}")
                else:
                    parts.append(name)
            elif btype == "text":
                text = block.get("text", "").strip()
                if text:
                    first_line = text.split("\n")[0][:120]
                    parts.append(first_line)
        return " | ".join(parts) if parts else None

    return None


def _run_streaming(
    cmd: list[str],
    cwd: str,
    env: dict[str, str],
    timeout: int,
    log_fn: Callable[[str], None],
    tools_used: set[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run claude CLI with stream-json, streaming events via log_fn.

    Returns a CompletedProcess whose ``stdout`` contains the JSON-encoded
    ``result`` event (compatible with the non-streaming code path).

    If ``tools_used`` is provided, tool names observed in stream events
    are added to it for post-hoc verification.
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )

    result_json = "{}"

    def _process_stdout():
        nonlocal result_json
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "result":
                result_json = line
            else:
                # Track tool usage for post-hoc verification
                if tools_used is not None:
                    for tool_name in _extract_tool_names(event):
                        tools_used.add(tool_name)
                formatted = _format_stream_event(event)
                if formatted:
                    log_fn(formatted)

    def _drain_stderr():
        for _ in proc.stderr:
            pass

    t_out = threading.Thread(target=_process_stdout, daemon=True)
    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        raise

    t_out.join(timeout=5)
    t_err.join(timeout=5)

    return subprocess.CompletedProcess(cmd, proc.returncode, result_json, "")


def _build_env() -> dict[str, str]:
    """Build subprocess environment with anti-nesting guard stripped."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


def _parse_usage(output: dict[str, Any]) -> tuple[int, float]:
    """Extract token count and cost from Claude Code JSON output.

    Returns (total_tokens, estimated_cost_usd).

    Handles two formats:
    - Real CLI: {"total_cost_usd": 0.123, "duration_ms": 45000, ...}
    - Mock/test: {"usage": {"input_tokens": ..., "output_tokens": ...}}
    """
    # Real Claude Code CLI output has total_cost_usd at top level
    if "total_cost_usd" in output:
        cost = output["total_cost_usd"]
        # Prefer actual token counts from usage block if available
        usage = output.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        if not tokens and cost:
            # Fallback: estimate tokens from cost (~$9/1M tokens average)
            tokens = int(cost * 1_000_000 / 9.0)
        return tokens, cost

    # Mock/test format with explicit usage block
    usage = output.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total = input_tokens + output_tokens

    cost = output.get("cost_usd", 0.0)
    if not cost and total:
        # Rough estimate if cost not provided
        cost = total * 3.0 / 1_000_000  # ~sonnet pricing

    return total, cost


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
        max_turns: int = 30,
        run_subprocess: Any | None = None,
        log_fn: Callable[[str], None] | None = None,
        sandbox_handle: Any | None = None,
    ) -> None:
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._timeout = timeout
        self._max_turns = max_turns
        self._process: subprocess.Popen | None = None
        self._terminated = False
        # Allow injecting a mock for subprocess.run in tests
        self._run_subprocess = run_subprocess or subprocess.run
        self._log_fn = log_fn
        self._sandbox = sandbox_handle
        # Stream events only when log_fn is set and no mock is injected
        self._use_streaming = log_fn is not None and run_subprocess is None
        # Tracks tools the agent actually used (populated during streaming)
        self.last_tools_used: set[str] = set()

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

        # Build workspace file index so agent doesn't waste turns exploring
        workspace_files: list[str] = []
        ws_root = workspace.parent  # workspace is ws_root/config.workspace/task_name
        if ws_root.exists():
            for p in sorted(ws_root.rglob("*")):
                if p.is_file() and ".agentos_context" not in str(p):
                    workspace_files.append(str(p))

        prompt = _build_prompt(
            task_description, role, predecessor_context,
            workspace_files=workspace_files if workspace_files else None,
        )
        out_fmt = "stream-json" if self._use_streaming else "json"
        cmd = _build_command(prompt, allowed_tools, output_format=out_fmt,
                             max_turns=self._max_turns)
        env = _build_env()

        total_tokens = 0
        total_cost = 0.0
        api_calls = 0
        raw_output: dict[str, Any] = {}
        self.last_tools_used = set()

        # Run with retries for manifest validation
        for attempt in range(1 + MAX_MANIFEST_RETRIES):
            if self._terminated:
                break

            try:
                if self._sandbox is not None and self._run_subprocess is subprocess.run:
                    # Use sandbox handle to run commands
                    result = self._sandbox.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=self._timeout,
                        env=env,
                    )
                elif self._use_streaming:
                    result = _run_streaming(
                        cmd, str(workspace), env,
                        self._timeout, self._log_fn,
                        tools_used=self.last_tools_used,
                    )
                else:
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
                    output_format=out_fmt,
                    max_turns=self._max_turns,
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
