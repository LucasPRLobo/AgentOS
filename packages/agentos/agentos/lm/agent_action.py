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


def parse_agent_action(content: str) -> AgentAction:
    """Extract an AgentAction from LM response text.

    Handles raw JSON or JSON wrapped in markdown code blocks.
    Raises ValueError if the response cannot be parsed.
    """
    text = content.strip()

    # Try to extract JSON from markdown code blocks
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        text = md_match.group(1).strip()

    # Try to find a JSON object in the text
    # Look for the outermost {...}
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        text = text[brace_start : brace_end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse agent action JSON: {e}\nContent: {content}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    if "action" not in data:
        raise ValueError("Missing 'action' field in agent response")

    return AgentAction.model_validate(data)
