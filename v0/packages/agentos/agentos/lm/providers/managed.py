"""Managed proxy provider — routes requests through a platform-managed endpoint."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse

logger = logging.getLogger(__name__)


class ManagedProxyProvider(BaseLMProvider):
    """Routes LLM requests through a managed proxy endpoint.

    For deployments where the platform operator provides model access
    and users don't need their own API keys. Uses a simple HTTP API
    compatible with the OpenAI chat completions format.

    No external dependencies — uses ``urllib.request``.
    """

    def __init__(
        self,
        model: str,
        proxy_url: str,
        proxy_key: str | None = None,
        timeout: int = 120,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> None:
        self._model = model
        self._proxy_url = proxy_url.rstrip("/")
        self._proxy_key = proxy_key
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def name(self) -> str:
        return f"managed-{self._model}"

    def get_model_name(self) -> str:
        return self._model

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        """Generate a completion via the managed proxy."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens

        data = self._post("/v1/chat/completions", payload)

        choice = data["choices"][0]
        content = choice["message"]["content"] or ""
        usage = data.get("usage", {})

        return LMResponse(
            content=content,
            tokens_used=usage.get("total_tokens", 0),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to the proxy endpoint."""
        url = f"{self._proxy_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._proxy_key:
            headers["Authorization"] = f"Bearer {self._proxy_key}"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(
                f"Managed proxy returned HTTP {e.code}: {body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Failed to connect to managed proxy at {url}: {e}"
            ) from e
