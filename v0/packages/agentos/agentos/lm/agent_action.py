"""Agent action parsing — extract structured actions from LM responses."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentActionType(StrEnum):
    """Types of actions an agent can take."""

    TOOL_CALL = "tool_call"
    FINISH = "finish"


class AgentAction(BaseModel):
    """Parsed action from an LM response."""

    action: AgentActionType
    tool: str | None = Field(default=None, description="Tool name for tool_call actions")
    input: dict[str, Any] | None = Field(
        default=None, description="Tool input for tool_call actions"
    )
    result: str | None = Field(default=None, description="Final result for finish actions")
    reasoning: str = Field(default="", description="LM's reasoning for this action")


# Common LLM mistakes for action names → canonical values
_ACTION_ALIASES: dict[str, str] = {
    "tool_call": "tool_call",
    "finish": "finish",
    "finished": "finish",
    "finishing": "finish",
    "done": "finish",
    "complete": "finish",
    "completed": "finish",
    "call": "tool_call",
    "use_tool": "tool_call",
    "call_tool": "tool_call",
}


def _extract_first_json_object(text: str) -> str:
    """Extract the first balanced JSON object from text.

    Handles cases where the LLM outputs multiple JSON objects separated
    by semicolons, newlines, or other text.
    """
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # Fallback: return from first brace to last brace
    end = text.rfind("}")
    if end > start:
        return text[start : end + 1]
    return text


def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize common LLM output quirks before Pydantic validation."""
    # Normalize action name
    action = data.get("action", "")
    if isinstance(action, str):
        normalized = _ACTION_ALIASES.get(action.lower().strip())
        if normalized:
            data["action"] = normalized
        elif action not in ("tool_call", "finish"):
            # If the action looks like a tool name, treat it as a tool_call
            data = {
                "action": "tool_call",
                "tool": action,
                "input": data.get("input", {}),
                "reasoning": data.get("reasoning", ""),
            }

    # If result is a dict, serialize it to JSON string
    if "result" in data and isinstance(data["result"], dict):
        data["result"] = json.dumps(data["result"])

    # If input is a JSON string, parse it
    if "input" in data and isinstance(data["input"], str):
        try:
            data["input"] = json.loads(data["input"])
        except (json.JSONDecodeError, ValueError):
            data["input"] = {}

    return data


def parse_agent_action(content: str) -> AgentAction:
    """Extract an AgentAction from LM response text.

    Handles raw JSON or JSON wrapped in markdown code blocks.
    Resilient to common small-LLM mistakes:
    - Multiple JSON objects (takes the first one)
    - Action name aliases ("finishing" → "finish")
    - Dict result values (serialized to JSON string)
    - String input values (parsed to dict)

    Raises ValueError if the response cannot be parsed.
    """
    text = content.strip()

    # Try to extract JSON from markdown code blocks
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()

    # Extract the first balanced JSON object
    text = _extract_first_json_object(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse agent action JSON: {e}\nContent: {content}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    if "action" not in data:
        raise ValueError("Missing 'action' field in agent response")

    data = _normalize_data(data)

    return AgentAction.model_validate(data)
