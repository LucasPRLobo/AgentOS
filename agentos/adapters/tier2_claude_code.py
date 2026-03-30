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
from agentos.schemas.agent import ClaudeCodeConfig
from agentos.adapters.tier2_shared import (
    DEFAULT_TIMEOUT,
    MAX_MANIFEST_RETRIES,
    build_prompt,
    extract_manifest_from_text,
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
    claude_code_config: ClaudeCodeConfig | None = None,
) -> list[str]:
    """Build the claude CLI command."""
    # Apply max_turns override from config before building command
    if claude_code_config and claude_code_config.max_turns:
        max_turns = claude_code_config.max_turns

    cmd = [
        "claude",
        "--print",
        "--output-format", output_format,
        "--max-turns", str(max_turns),
    ]
    # stream-json requires --verbose in --print mode
    if output_format == "stream-json":
        cmd.append("--verbose")

    # Permission mode
    if claude_code_config and claude_code_config.permission_mode:
        # Block dangerous permission modes — governance platform never bypasses
        if claude_code_config.permission_mode not in ("bypassPermissions",):
            cmd.extend(["--permission-mode", claude_code_config.permission_mode])

    # Append system prompt
    if claude_code_config and claude_code_config.append_system_prompt:
        cmd.extend(["--append-system-prompt", claude_code_config.append_system_prompt])

    # MCP configuration
    if claude_code_config and claude_code_config.mcp_config:
        for mcp in claude_code_config.mcp_config:
            cmd.extend(["--mcp-config", mcp])
        if len(claude_code_config.mcp_config) > 0:
            cmd.append("--strict-mcp-config")

    # Model override
    if claude_code_config and claude_code_config.model:
        cmd.extend(["--model", claude_code_config.model])

    # Additional directories
    if claude_code_config and claude_code_config.add_dirs:
        for d in claude_code_config.add_dirs:
            cmd.extend(["--add-dir", d])

    cmd.extend(["-p", prompt])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    else:
        # SECURITY: If no tools are specified, restrict to a safe baseline.
        # Without --allowedTools, Claude Code gives the agent ALL tools
        # including Bash, which violates the governance model.
        cmd.extend(["--allowedTools", "Read,Write,Edit,Glob,Grep"])

    # Disabled slash commands
    if claude_code_config and claude_code_config.disabled_commands:
        cmd.extend(["--disallowedCommands", ",".join(claude_code_config.disabled_commands)])

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
    event_emitter: Callable[[dict[str, Any]], None] | None = None,
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
                # Emit structured events to event log
                if event_emitter is not None:
                    event_emitter(event)
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


# Environment variables safe to pass to agent subprocesses.
_ENV_WHITELIST = {
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "TMP", "TEMP", "XDG_RUNTIME_DIR", "XDG_DATA_HOME",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
    # Claude Code needs its API key to function
    "ANTHROPIC_API_KEY",
    # Node.js / Claude Code runtime
    "NODE_PATH", "NODE_OPTIONS", "npm_config_prefix",
}


def _build_env() -> dict[str, str]:
    """Build a restricted environment for agent subprocesses."""
    env = {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}
    # Anti-nesting guard: prevent Claude Code from thinking it's inside itself
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
        event_log: Any | None = None,
        seq: Any | None = None,
        workflow_id: str | None = None,
        claude_code_config: ClaudeCodeConfig | None = None,
        message_bus: Any | None = None,
        board_manager: Any | None = None,
    ) -> None:
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._timeout = timeout
        self._max_turns = max_turns
        self._claude_code_config = claude_code_config
        self._process: subprocess.Popen | None = None
        self._terminated = False
        # Allow injecting a mock for subprocess.run in tests
        self._run_subprocess = run_subprocess or subprocess.run
        self._log_fn = log_fn
        self._sandbox = sandbox_handle

        # Communication components (optional — Phase 2)
        self._message_bus = message_bus
        self._board_manager = board_manager
        # Event log integration for dashboard streaming
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        # Stream events only when log_fn is set and no mock is injected
        self._use_streaming = log_fn is not None and run_subprocess is None
        # Tracks tools the agent actually used (populated during streaming)
        self.last_tools_used: set[str] = set()

    def _make_event_emitter(self, task_id: str) -> Callable[[dict[str, Any]], None] | None:
        """Build a callback that emits AGENT_TOOL_CALL / AGENT_TEXT_OUTPUT events."""
        if self._event_log is None or self._seq is None or self._workflow_id is None:
            return None

        from agentos.schemas.events import Event, EventType

        def emitter(stream_event: dict[str, Any]) -> None:
            etype = stream_event.get("type", "")
            if etype != "assistant":
                return
            for block in stream_event.get("message", {}).get("content", []):
                btype = block.get("type", "")
                if btype == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    summary = json.dumps(inp)[:200] if inp else ""
                    self._event_log.append(Event(
                        event_type=EventType.AGENT_TOOL_CALL,
                        workflow_id=self._workflow_id,
                        seq=self._seq.next(),
                        payload={
                            "agent_id": self._agent_id,
                            "task_id": task_id,
                            "tool_name": name,
                            "tool_input_summary": summary,
                        },
                    ))
                elif btype == "text":
                    text = block.get("text", "").strip()
                    if text:
                        self._event_log.append(Event(
                            event_type=EventType.AGENT_TEXT_OUTPUT,
                            workflow_id=self._workflow_id,
                            seq=self._seq.next(),
                            payload={
                                "agent_id": self._agent_id,
                                "task_id": task_id,
                                "text_preview": text[:200],
                            },
                        ))

        return emitter

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

        # --- Communication setup (Phase 2) ---
        self._setup_comms(workspace)

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

        # Append comms prompt if communication is enabled
        if self._board_manager is not None or self._message_bus is not None:
            from agentos.adapters.tier2_shared import write_comms_prompt_addition
            prompt += write_comms_prompt_addition()

        # Inject MCP comms server config if comms are enabled
        config = self._get_comms_config(workspace)
        out_fmt = "stream-json" if self._use_streaming else "json"
        cmd = _build_command(prompt, allowed_tools, output_format=out_fmt,
                             max_turns=self._max_turns,
                             claude_code_config=config)
        env = _build_env()

        total_tokens = 0
        total_cost = 0.0
        api_calls = 0
        raw_output: dict[str, Any] = {}
        raw_text_output: str = ""
        self.last_tools_used = set()
        event_emitter = self._make_event_emitter(task_id="")

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
                        event_emitter=event_emitter,
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
            raw_text_output = result.stdout or ""

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
            # Route outbox messages through comms system
            self._finalize_comms(workspace)

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
                    claude_code_config=self._claude_code_config,
                )

        # All retries exhausted — try fallback extraction from raw output
        elapsed = time.monotonic() - start_time
        metrics = TaskMetrics(
            tokens_consumed=total_tokens,
            api_calls_made=api_calls,
            execution_time_seconds=round(elapsed, 2),
            estimated_cost_usd=total_cost,
        )

        if raw_text_output:
            inferred = extract_manifest_from_text(raw_text_output)
            if inferred is not None:
                output = manifest_to_task_output(
                    inferred, task_id="", agent_id=self._agent_id, metrics=metrics,
                )
                output.summary = f"[inferred manifest] {output.summary}"
                return output

        return TaskOutput(
            task_id="",
            agent_id=self._agent_id,
            status=TaskStatus.FAILED,
            summary="Agent did not produce a valid manifest.json after retries.",
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Communication helpers (Phase 2)
    # ------------------------------------------------------------------

    def _setup_comms(self, workspace: Path) -> None:
        """Write comms state to workspace before agent launch."""
        if self._board_manager is None and self._message_bus is None:
            return

        from agentos.comms.comms_state import write_comms_state

        pending: list = []
        if self._message_bus is not None:
            pending = self._message_bus.receive(self._agent_id)

        if self._board_manager is not None:
            # Also write the board.md file for non-MCP fallback
            from agentos.adapters.tier2_shared import write_board_state
            write_board_state(workspace, self._board_manager)

            write_comms_state(
                workspace,
                board_manager=self._board_manager,
                pending_messages=pending,
                agent_id=self._agent_id,
                workflow_id=self._workflow_id or "",
            )
        elif pending:
            from agentos.adapters.tier2_shared import write_inbox
            write_inbox(workspace, pending)

    def _get_comms_config(self, workspace: Path) -> ClaudeCodeConfig | None:
        """Return a ClaudeCodeConfig with MCP comms server injected."""
        if self._board_manager is None and self._message_bus is None:
            return self._claude_code_config

        import sys

        mcp_json = json.dumps({
            "mcpServers": {
                "agentos-comms": {
                    "command": sys.executable,
                    "args": ["-m", "agentos.comms.mcp_server", "--workspace", str(workspace)],
                    "env": {},
                }
            }
        })

        if self._claude_code_config is None:
            return ClaudeCodeConfig(mcp_config=[mcp_json])

        # Clone the config and add our MCP server
        config = self._claude_code_config.model_copy(deep=True)
        config.mcp_config = list(config.mcp_config) + [mcp_json]
        return config

    def _finalize_comms(self, workspace: Path) -> None:
        """Read outbox and route messages through comms system after task."""
        if self._board_manager is None and self._message_bus is None:
            return

        from agentos.adapters.tier2_shared import read_outbox
        from agentos.comms.schemas import (
            BoardPost,
            BoardSection,
            DirectMessage,
            MessagePriority,
            SpeechAct,
        )

        outbox_msgs = read_outbox(workspace)
        for msg_data in outbox_msgs:
            target = msg_data.get("to", "")
            content = msg_data.get("content", "")
            if not content:
                continue

            if target == "board" and self._board_manager is not None:
                self._board_manager.post(BoardPost(
                    section=BoardSection(msg_data.get("section", "post")),
                    author_type="agent",
                    author_id=self._agent_id,
                    content=content,
                    speech_act=SpeechAct(msg_data.get("speech_act", "inform")),
                ))
            elif self._message_bus is not None:
                self._message_bus.send(DirectMessage(
                    sender_type="agent",
                    sender_id=self._agent_id,
                    recipient_type="human" if target == "human" else "agent",
                    recipient_id=target,
                    content=content,
                    speech_act=SpeechAct(msg_data.get("speech_act", "inform")),
                    priority=MessagePriority(msg_data.get("priority", "normal")),
                    workflow_id=self._workflow_id or "",
                ))

    async def terminate(self) -> None:
        """Signal the adapter to stop and terminate any running process."""
        self._terminated = True
        if self._process is not None:
            self._process.terminate()
