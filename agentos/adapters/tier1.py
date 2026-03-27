"""Tier 1 adapter — API-controlled agent with tool-calling loop."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic

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

logger = logging.getLogger(__name__)

# Maximum tool-call loop iterations to prevent runaway agents.
MAX_ITERATIONS = 50


def _build_system_prompt(
    role: str,
    predecessor_context: list[TaskOutput],
    allowed_tools: list[str],
) -> str:
    """Assemble the system prompt from role, context, and constraints."""
    parts = [role]

    if predecessor_context:
        parts.append("\n## Predecessor task outputs\n")
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

    if allowed_tools:
        parts.append(f"\nYou may only use these tools: {', '.join(allowed_tools)}")

    return "\n".join(parts)


# Built-in tool definitions for the Tier 1 tool-calling loop.
# These are the tools AgentOS offers to the agent through the API.
TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "file_read": {
        "name": "file_read",
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to read"},
            },
            "required": ["path"],
        },
    },
    "file_write": {
        "name": "file_write",
        "description": "Write content to a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to write"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["path", "content"],
        },
    },
    "shell_exec": {
        "name": "shell_exec",
        "description": "Execute a shell command in the workspace directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
            },
            "required": ["command"],
        },
    },
    "web_search": {
        "name": "web_search",
        "description": "Search the web for information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    "task_complete": {
        "name": "task_complete",
        "description": "Signal that the task is complete. Provide a structured summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "1-3 sentence summary"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                            },
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["finding", "confidence"],
                    },
                    "description": "Key findings",
                },
                "open_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Unresolved questions",
                },
            },
            "required": ["summary"],
        },
    },
}


# Communication tools — available when a MessageBus is provided.
COMMS_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "send_message": {
        "name": "send_message",
        "description": (
            "Send a direct message to a team member or the human manager. "
            "Use this to ask questions, share findings, or request help."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient agent name or 'human'",
                },
                "content": {"type": "string", "description": "Your message"},
                "speech_act": {
                    "type": "string",
                    "enum": ["inform", "request", "propose"],
                    "description": "Intent of your message",
                    "default": "inform",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "default": "normal",
                },
            },
            "required": ["to", "content"],
        },
    },
    "post_to_board": {
        "name": "post_to_board",
        "description": (
            "Post a message to the workspace board visible to all team "
            "members. Use this to share important findings, ask the team "
            "a question, or record a decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Post content"},
                "section": {
                    "type": "string",
                    "enum": ["post", "question", "decision"],
                    "default": "post",
                },
                "speech_act": {
                    "type": "string",
                    "enum": ["inform", "request", "propose"],
                    "default": "inform",
                },
            },
            "required": ["content"],
        },
    },
    "read_board": {
        "name": "read_board",
        "description": (
            "Read the full workspace board — announcements, team status, "
            "recent posts, decisions, open questions, and alerts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
}


def _filter_tools(
    allowed: list[str],
    include_comms: bool = False,
) -> list[dict[str, Any]]:
    """Return only the tool definitions matching the allowlist.

    task_complete is always included — it's the agent's way to signal done.
    When *include_comms* is ``True``, communication tools are added.
    """
    tools = []
    for name in allowed:
        if name in TOOL_DEFINITIONS:
            tools.append(TOOL_DEFINITIONS[name])
    # Always include task_complete
    if "task_complete" not in allowed:
        tools.append(TOOL_DEFINITIONS["task_complete"])
    # Add communication tools when a message bus is present
    if include_comms:
        for defn in COMMS_TOOL_DEFINITIONS.values():
            tools.append(defn)
    return tools


class Tier1Adapter(AgentAdapter):
    """API-controlled Tier 1 adapter using the Anthropic Messages API.

    AgentOS fully controls the tool-calling loop:
    1. Sends the task prompt with tool definitions.
    2. Receives model response (text or tool_use blocks).
    3. Executes allowed tool calls, feeds results back.
    4. Repeats until the agent calls task_complete or budget is exceeded.
    5. Returns a structured TaskOutput.
    """

    @property
    def tier(self) -> int:
        return 1

    def __init__(
        self,
        client: Anthropic,
        model: str,
        budget_manager: BudgetManager,
        agent_id: str,
        *,
        tool_handler: Any | None = None,
        message_bus: Any | None = None,
        board_manager: Any | None = None,
        ambient_injector: Any | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._tool_handler = tool_handler
        self._terminated = False

        # Communication components (optional — comms features activate when set)
        self._message_bus = message_bus
        self._board_manager = board_manager
        self._ambient_injector = ambient_injector
        self._last_board_version: int | None = None

    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Run the tool-calling loop and return structured output."""
        start_time = time.monotonic()
        has_comms = self._message_bus is not None

        system = _build_system_prompt(role, predecessor_context, allowed_tools)
        tools = _filter_tools(allowed_tools, include_comms=has_comms)
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": task_description},
        ]

        total_tokens = 0
        total_api_calls = 0
        task_complete_result: dict[str, Any] | None = None

        for _ in range(MAX_ITERATIONS):
            if self._terminated:
                break

            # --- Ambient awareness: inject board + pending messages ---
            if has_comms:
                self._inject_comms(messages)

            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=tools,
            )

            total_api_calls += 1
            total_tokens += (response.usage.input_tokens + response.usage.output_tokens)

            elapsed = time.monotonic() - start_time
            self._budget_manager.apply(
                self._agent_id,
                BudgetDelta(
                    tokens=response.usage.input_tokens + response.usage.output_tokens,
                    api_calls=1,
                    time_seconds=elapsed,
                    cost_usd=_estimate_cost(
                        self._model,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    ),
                ),
            )

            if response.stop_reason == "end_turn":
                # Model finished without calling any tool — extract text as summary
                text = _extract_text(response)
                task_complete_result = {"summary": text}
                break

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "task_complete":
                    task_complete_result = block.input
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Task completion acknowledged.",
                    })
                    break

                # Execute the tool via handler (or return stub)
                result = self._handle_tool(block.name, block.input, workspace)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            # Append assistant response + tool results for next turn
            messages.append({"role": "assistant", "content": response.content})
            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            if task_complete_result is not None:
                break

        elapsed = time.monotonic() - start_time

        return _build_task_output(
            task_id="",  # Filled by caller
            agent_id=self._agent_id,
            result=task_complete_result,
            metrics=TaskMetrics(
                tokens_consumed=total_tokens,
                api_calls_made=total_api_calls,
                execution_time_seconds=round(elapsed, 2),
                estimated_cost_usd=0.0,
            ),
        )

    async def terminate(self) -> None:
        """Signal the adapter to stop at the next iteration."""
        self._terminated = True

    def _handle_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        workspace: Path,
    ) -> str:
        """Dispatch a tool call. Uses custom handler if provided, else returns stub."""
        # --- Communication tools (handled before custom handler) ---
        if tool_name in COMMS_TOOL_DEFINITIONS:
            return self._handle_comms_tool(tool_name, tool_input)

        if self._tool_handler is not None:
            return self._tool_handler(tool_name, tool_input, workspace)

        # Default stub responses for tools without a handler
        if tool_name == "file_read":
            path = workspace / tool_input["path"]
            if path.exists():
                return path.read_text()
            return f"Error: file not found: {tool_input['path']}"

        if tool_name == "file_write":
            path = workspace / tool_input["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tool_input["content"])
            return f"Written to {tool_input['path']}"

        if tool_name == "shell_exec":
            return f"[stub] shell_exec not available in this context: {tool_input['command']}"

        if tool_name == "web_search":
            return f"[stub] web_search not available in this context: {tool_input['query']}"

        return f"Unknown tool: {tool_name}"

    # ------------------------------------------------------------------
    # Communication helpers
    # ------------------------------------------------------------------

    def _inject_comms(self, messages: list[dict[str, Any]]) -> None:
        """Inject board state and pending messages into the conversation.

        Called at each iteration boundary — this is how the agent
        "glances at the board" (Google ADK yield/resume pattern).
        """
        if self._ambient_injector is None and self._message_bus is None:
            return

        pending_msgs = None
        if self._message_bus is not None:
            pending_msgs = self._message_bus.receive(self._agent_id)
            if not pending_msgs:
                pending_msgs = None

        injection: str | None = None
        if self._ambient_injector is not None:
            injection = self._ambient_injector.build_injection(
                agent_id=self._agent_id,
                pending_messages=pending_msgs,
                last_seen_board_version=self._last_board_version,
            )
            if injection:
                state = self._board_manager.get_state() if self._board_manager else None
                if state:
                    self._last_board_version = state.version
        elif pending_msgs:
            # No ambient injector but we have a message bus — inject msgs only
            from agentos.comms.ambient_context import AmbientContextInjector
            injection = AmbientContextInjector.format_message_injection(pending_msgs)

        if injection:
            messages.append({"role": "user", "content": injection})

    def _handle_comms_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> str:
        """Handle communication tool calls."""
        if tool_name == "send_message":
            if self._message_bus is None:
                return "Communication not available in this workflow."
            from agentos.comms.schemas import DirectMessage, MessagePriority, SpeechAct

            msg = DirectMessage(
                sender_type="agent",
                sender_id=self._agent_id,
                recipient_type="human" if tool_input["to"] == "human" else "agent",
                recipient_id=tool_input["to"],
                content=tool_input["content"],
                speech_act=SpeechAct(tool_input.get("speech_act", "inform")),
                priority=MessagePriority(tool_input.get("priority", "normal")),
                workflow_id=self._message_bus._workflow_id,
            )
            mid = self._message_bus.send(msg)
            return f"Message sent to {tool_input['to']} (id: {mid})"

        if tool_name == "post_to_board":
            if self._board_manager is None:
                return "Board not available in this workflow."
            from agentos.comms.schemas import BoardPost, BoardSection, SpeechAct

            post = BoardPost(
                section=BoardSection(tool_input.get("section", "post")),
                author_type="agent",
                author_id=self._agent_id,
                content=tool_input["content"],
                speech_act=SpeechAct(tool_input.get("speech_act", "inform")),
            )
            pid = self._board_manager.post(post)
            return f"Posted to board section '{post.section}' (id: {pid})"

        if tool_name == "read_board":
            if self._board_manager is None:
                return "Board not available in this workflow."
            return self._board_manager.render_compact(max_tokens=500)

        return f"Unknown comms tool: {tool_name}"


def _extract_text(response: Any) -> str:
    """Extract text content from a Messages API response."""
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts) if parts else "Task completed."


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Rough cost estimate based on model pricing."""
    # Prices per 1M tokens (approximate)
    pricing: dict[str, tuple[float, float]] = {
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-haiku-4-5-20251001": (0.80, 4.0),
        "claude-opus-4-6": (15.0, 75.0),
    }
    input_rate, output_rate = pricing.get(model, (3.0, 15.0))
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def _build_task_output(
    task_id: str,
    agent_id: str,
    result: dict[str, Any] | None,
    metrics: TaskMetrics,
) -> TaskOutput:
    """Build a TaskOutput from the task_complete call or fallback."""
    if result is None:
        return TaskOutput(
            task_id=task_id,
            agent_id=agent_id,
            status=TaskStatus.FAILED,
            summary="Agent did not produce a task_complete call.",
            metrics=metrics,
        )

    findings = []
    for f in result.get("findings", []):
        findings.append(Finding(
            finding=f["finding"],
            confidence=Confidence(f["confidence"]),
            sources=f.get("sources", []),
        ))

    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.SUCCEEDED,
        summary=result.get("summary", "Task completed."),
        key_findings=findings,
        open_questions=result.get("open_questions", []),
        metrics=metrics,
    )
