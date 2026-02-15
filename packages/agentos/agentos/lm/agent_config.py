"""Agent configuration — settings for the AgentRunner loop."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    """Configuration for the AgentRunner executor."""

    system_prompt: str = Field(
        default=(
            "You are an AI agent with access to tools. "
            "Respond with a JSON object containing your action.\n"
            "For tool calls: "
            '{"action": "tool_call", "tool": "<name>", "input": {...}, "reasoning": "..."}\n'
            "When done: "
            '{"action": "finish", "result": "...", "reasoning": "..."}'
        ),
        description="System prompt for the agent",
    )
    max_steps: int = Field(default=50, gt=0, description="Maximum agent steps")
    max_consecutive_errors: int = Field(
        default=3, gt=0, description="Maximum consecutive parse/execution errors before halting"
    )
