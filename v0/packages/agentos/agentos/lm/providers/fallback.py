"""Fallback provider — wraps a primary provider with automatic failover."""

from __future__ import annotations

import logging
from typing import Any

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse

logger = logging.getLogger(__name__)


class FallbackProvider(BaseLMProvider):
    """Wraps a primary provider with fallback to a backup on failure.

    On any exception from the primary provider (rate limits, API errors,
    timeouts), automatically retries with the fallback provider.
    """

    def __init__(
        self,
        primary: BaseLMProvider,
        fallback: BaseLMProvider,
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def name(self) -> str:
        return f"fallback({self._primary.name}|{self._fallback.name})"

    def get_model_name(self) -> str:
        return self._primary.get_model_name()

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        try:
            return self._primary.complete(messages)
        except Exception as exc:
            logger.warning(
                "Primary provider '%s' failed: %s. Falling back to '%s'.",
                self._primary.name,
                exc,
                self._fallback.name,
            )
            return self._fallback.complete(messages)

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        try:
            return self._primary.generate_structured(
                messages, schema=schema, tool_schemas=tool_schemas
            )
        except Exception as exc:
            logger.warning(
                "Primary provider '%s' structured call failed: %s. "
                "Falling back to '%s'.",
                self._primary.name,
                exc,
                self._fallback.name,
            )
            return self._fallback.generate_structured(
                messages, schema=schema, tool_schemas=tool_schemas
            )
