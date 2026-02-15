"""OpenAI provider — BYOK provider with function calling and structured output."""

from __future__ import annotations

import json
import logging
from typing import Any

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLMProvider):
    """LM provider backed by the OpenAI API.

    Supports structured output via ``response_format`` (JSON mode)
    and tool calling via the ``tools`` parameter.

    Requires the ``openai`` package: ``pip install openai``.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 120,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "The 'openai' package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from e

        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = self._create_client()

    def _create_client(self) -> Any:
        import openai

        kwargs: dict[str, Any] = {"timeout": self._timeout}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return openai.OpenAI(**kwargs)

    @property
    def name(self) -> str:
        return f"openai-{self._model}"

    def get_model_name(self) -> str:
        return self._model

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        """Generate a completion using the OpenAI chat API."""
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens

        response = self._client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage

        return LMResponse(
            content=content,
            tokens_used=(usage.total_tokens if usage else 0),
            prompt_tokens=(usage.prompt_tokens if usage else 0),
            completion_tokens=(usage.completion_tokens if usage else 0),
        )

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        """Generate structured output using OpenAI's native features.

        If ``tool_schemas`` are provided, uses the ``tools`` parameter
        for function calling. Otherwise, if ``schema`` is provided,
        uses ``response_format`` with JSON schema.
        Falls back to ``complete()`` if neither is provided.
        """
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens

        if tool_schemas:
            # Use function calling / tools API
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        elif schema:
            # Use JSON mode with response_format
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                },
            }

        response = self._client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        usage = response.usage

        # Extract content from tool calls or message
        if choice.message.tool_calls:
            # Return the first tool call's arguments as content
            tool_call = choice.message.tool_calls[0]
            content = json.dumps({
                "tool_call_id": tool_call.id,
                "function_name": tool_call.function.name,
                "arguments": tool_call.function.arguments,
            })
        else:
            content = choice.message.content or ""

        return LMResponse(
            content=content,
            tokens_used=(usage.total_tokens if usage else 0),
            prompt_tokens=(usage.prompt_tokens if usage else 0),
            completion_tokens=(usage.completion_tokens if usage else 0),
        )
