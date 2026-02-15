"""Context window manager — token-aware prompt assembly."""

from __future__ import annotations

import json
import logging
from typing import Any

from agentos.lm.provider import LMMessage, ModelCapabilities

logger = logging.getLogger(__name__)

# Approximate characters per token (conservative for most tokenizers)
_CHARS_PER_TOKEN = 4


class ContextManager:
    """Manages the context window budget for an agent.

    Assembles prompts within the model's context window, prioritizing
    components by importance:
    1. System prompt (never trimmed)
    2. Tool schemas (never trimmed)
    3. Current upstream output (compressed if needed)
    4. Recent conversation history (sliding window)
    5. Memory context (trimmed first)
    """

    def __init__(
        self,
        model: str,
        capabilities: ModelCapabilities,
        *,
        output_reserve_ratio: float = 0.25,
    ) -> None:
        self._model = model
        self._capabilities = capabilities
        # Reserve tokens for output generation
        self._output_reserve = int(
            min(capabilities.max_output_tokens, capabilities.context_window * output_reserve_ratio)
        )
        self._context_budget = capabilities.context_window - self._output_reserve

    @property
    def context_budget(self) -> int:
        """Total token budget for the input prompt."""
        return self._context_budget

    @property
    def output_reserve(self) -> int:
        """Tokens reserved for model output."""
        return self._output_reserve

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a string.

        Uses tiktoken for OpenAI models if available, otherwise falls
        back to a character-based heuristic.
        """
        if self._capabilities.provider == "openai":
            try:
                import tiktoken
                enc = tiktoken.encoding_for_model(self._model)
                return len(enc.encode(text))
            except (ImportError, KeyError):
                pass

        # Heuristic: ~4 characters per token
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def estimate_messages_tokens(self, messages: list[LMMessage]) -> int:
        """Estimate total tokens for a list of messages."""
        total = 0
        for msg in messages:
            # Each message has ~4 tokens overhead (role, formatting)
            total += 4 + self.estimate_tokens(msg.content)
        return total

    def available_tokens(
        self,
        system_prompt: str,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> int:
        """Return remaining tokens after fixed components (system + tools)."""
        used = self.estimate_tokens(system_prompt)
        if tool_schemas:
            used += self.estimate_tokens(json.dumps(tool_schemas))
        return max(0, self._context_budget - used)

    def build_prompt(
        self,
        system_prompt: str,
        *,
        tool_schemas: list[dict[str, Any]] | None = None,
        upstream_output: str | None = None,
        conversation_history: list[LMMessage] | None = None,
        memory_context: str | None = None,
    ) -> list[LMMessage]:
        """Assemble a prompt within the context window budget.

        Priority (highest first):
        1. System prompt (never trimmed)
        2. Tool schemas (appended to system prompt, never trimmed)
        3. Upstream output from previous agents (compressed if needed)
        4. Recent conversation history (newest kept, oldest dropped)
        5. Memory context (trimmed first)

        Returns:
            Ordered list of LMMessage objects ready for the provider.
        """
        messages: list[LMMessage] = []

        # 1. System prompt (always included, never trimmed)
        system_parts = [system_prompt]
        if tool_schemas:
            system_parts.append(
                "\n\nAvailable tools:\n" + json.dumps(tool_schemas, indent=2)
            )
        system_text = "\n".join(system_parts)
        messages.append(LMMessage(role="system", content=system_text))

        # Track remaining budget
        remaining = self._context_budget - self.estimate_tokens(system_text)

        # 5. Memory context (lowest priority — allocated first, trimmed first)
        memory_msg: LMMessage | None = None
        if memory_context and remaining > 0:
            mem_tokens = self.estimate_tokens(memory_context)
            # Allocate at most 10% of remaining budget to memory
            max_mem = int(remaining * 0.10)
            if mem_tokens > max_mem:
                # Truncate memory
                max_chars = max_mem * _CHARS_PER_TOKEN
                memory_context = memory_context[:max_chars] + "\n[... memory truncated]"
                mem_tokens = max_mem
            memory_msg = LMMessage(
                role="user",
                content=f"[Context from memory]\n{memory_context}",
            )
            remaining -= mem_tokens

        # 3. Upstream output (high priority)
        upstream_msg: LMMessage | None = None
        if upstream_output and remaining > 0:
            upstream_tokens = self.estimate_tokens(upstream_output)
            # Allocate up to 40% of remaining budget for upstream
            max_upstream = int(remaining * 0.60)
            if upstream_tokens > max_upstream:
                from agentos.runtime.data_contracts import compress_for_context

                max_chars = max_upstream * _CHARS_PER_TOKEN
                upstream_output = compress_for_context(upstream_output, max_chars)
                upstream_tokens = self.estimate_tokens(upstream_output)
            upstream_msg = LMMessage(
                role="user",
                content=f"[Output from previous agent]\n{upstream_output}",
            )
            remaining -= upstream_tokens

        # 4. Conversation history (sliding window, newest first)
        history_msgs: list[LMMessage] = []
        if conversation_history and remaining > 0:
            # Walk from newest to oldest, include what fits
            for msg in reversed(conversation_history):
                msg_tokens = 4 + self.estimate_tokens(msg.content)
                if msg_tokens > remaining:
                    break
                history_msgs.insert(0, msg)
                remaining -= msg_tokens

        # Assemble in order: system → memory → upstream → history
        if memory_msg:
            messages.append(memory_msg)
        if upstream_msg:
            messages.append(upstream_msg)
        messages.extend(history_msgs)

        return messages
