"""LM provider — abstract interface for language model backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

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
