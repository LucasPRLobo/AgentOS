"""OllamaProvider — local LLM inference via Ollama HTTP API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse


class OllamaProvider(BaseLMProvider):
    """LM provider backed by a local Ollama instance.

    Uses ``urllib.request`` (no extra dependencies) to call the Ollama
    ``/api/chat`` endpoint.
    """

    def __init__(
        self,
        model: str = "llama3.2:latest",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def name(self) -> str:
        return f"ollama-{self._model}"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
        }

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read())

        content = data["message"]["content"]
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)

        return LMResponse(
            content=content,
            tokens_used=prompt_tokens + completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def is_available(self) -> bool:
        """Check whether the Ollama server is reachable."""
        try:
            urllib.request.urlopen(
                f"{self._base_url}/api/tags", timeout=5
            )
            return True
        except (urllib.error.URLError, OSError):
            return False
