"""Anthropic provider — BYOK provider with tool_use structured output."""

from __future__ import annotations

import json
import logging
from typing import Any

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseLMProvider):
    """LM provider backed by the Anthropic API.

    Supports structured output via tool_use blocks.

    Requires the ``anthropic`` package: ``pip install anthropic``.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 120,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicProvider. "
                "Install it with: pip install anthropic"
            ) from e

        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = self._create_client()

    def _create_client(self) -> Any:
        import anthropic

        kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return anthropic.Anthropic(**kwargs)

    @property
    def name(self) -> str:
        return f"anthropic-{self._model}"

    def get_model_name(self) -> str:
        return self._model

    def _split_system(
        self, messages: list[LMMessage]
    ) -> tuple[str, list[dict[str, str]]]:
        """Separate system message from conversation (Anthropic API requirement)."""
        system = ""
        api_messages: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                api_messages.append({"role": m.role, "content": m.content})
        return system, api_messages

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        """Generate a completion using the Anthropic messages API."""
        system, api_messages = self._split_system(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)

        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return LMResponse(
            content=content,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        """Generate structured output using Anthropic's tool_use feature.

        If ``tool_schemas`` are provided, passes them as tools.
        If only ``schema`` is provided, wraps it as a single tool definition
        to force structured JSON output.
        Falls back to ``complete()`` if neither is provided.
        """
        if not tool_schemas and not schema:
            return self.complete(messages)

        system, api_messages = self._split_system(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if system:
            kwargs["system"] = system

        if tool_schemas:
            # Convert OpenAI-style tool schemas to Anthropic format
            kwargs["tools"] = self._convert_tool_schemas(tool_schemas)
        elif schema:
            # Wrap the schema as a single tool to force structured output
            kwargs["tools"] = [
                {
                    "name": "structured_output",
                    "description": "Provide your response in the required structured format.",
                    "input_schema": schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        response = self._client.messages.create(**kwargs)

        # Extract content — prefer tool_use blocks, fall back to text
        content = ""
        for block in response.content:
            if block.type == "tool_use":
                content = json.dumps(block.input)
                break
            elif block.type == "text":
                content += block.text

        return LMResponse(
            content=content,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )

    @staticmethod
    def _convert_tool_schemas(
        openai_schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool schemas to Anthropic format.

        OpenAI format: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Anthropic format: {"name": ..., "input_schema": ...}
        """
        anthropic_tools = []
        for tool in openai_schemas:
            if "function" in tool:
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object"}),
                })
            else:
                # Already in a compatible format
                anthropic_tools.append(tool)
        return anthropic_tools
