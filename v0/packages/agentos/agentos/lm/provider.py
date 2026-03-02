"""LM provider — abstract interface for language model backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class LMMessage(BaseModel):
    """A single message in an LM conversation."""

    role: str = Field(description="Message role: system, user, or assistant")
    content: str = Field(description="Message content")


class LMResponse(BaseModel):
    """Response from an LM provider."""

    content: str = Field(description="Generated text")
    tokens_used: int = Field(ge=0, description="Total tokens consumed")
    prompt_tokens: int = Field(ge=0, default=0, description="Input prompt tokens")
    completion_tokens: int = Field(
        ge=0, default=0, description="Output completion tokens"
    )


@dataclass(frozen=True)
class ModelCapabilities:
    """Describes the capabilities and pricing of a specific model."""

    context_window: int = 8192
    max_output_tokens: int = 4096
    supports_structured_output: bool = False
    supports_tool_use: bool = False
    supports_vision: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    provider: str = "unknown"
    display_name: str = ""


class BaseLMProvider(ABC):
    """Abstract base class for language model providers.

    Domain layers provide concrete implementations (OpenAI, Anthropic, local).
    AgentOS defines only the contract.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai-gpt4', 'anthropic-claude')."""

    @abstractmethod
    def complete(self, messages: list[LMMessage]) -> LMResponse:
        """Generate a completion from a list of messages."""

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        """Generate structured output using native API features.

        Providers that support native structured output (function calling,
        tool_use, JSON mode) should override this method. The default
        implementation falls back to ``complete()``.

        Args:
            messages: Conversation history.
            schema: JSON Schema for the desired output structure.
            tool_schemas: Available tool definitions in provider-native format.

        Returns:
            LMResponse with structured content.
        """
        return self.complete(messages)

    def get_model_name(self) -> str:
        """Return the underlying model identifier (e.g., 'gpt-4o')."""
        return self.name
