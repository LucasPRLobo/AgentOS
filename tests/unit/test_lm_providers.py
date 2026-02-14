"""Tests for LM providers — fallback, managed, and provider factory routing."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse


# ── Helpers ───────────────────────────────────────────────────────────

class _StubProvider(BaseLMProvider):
    """A stub provider that returns fixed responses."""

    def __init__(self, name: str = "stub", response: str = "ok") -> None:
        self._name = name
        self._response = response
        self.call_count = 0

    @property
    def name(self) -> str:
        return self._name

    def get_model_name(self) -> str:
        return self._name

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        self.call_count += 1
        return LMResponse(
            content=self._response,
            tokens_used=10,
            prompt_tokens=5,
            completion_tokens=5,
        )

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        self.call_count += 1
        return LMResponse(
            content=json.dumps({"result": self._response}),
            tokens_used=10,
            prompt_tokens=5,
            completion_tokens=5,
        )


class _FailingProvider(BaseLMProvider):
    """A provider that always raises."""

    @property
    def name(self) -> str:
        return "failing"

    def get_model_name(self) -> str:
        return "failing"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        raise RuntimeError("Provider failed")

    def generate_structured(
        self,
        messages: list[LMMessage],
        *,
        schema: dict[str, Any] | None = None,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> LMResponse:
        raise RuntimeError("Provider structured failed")


SAMPLE_MESSAGES = [LMMessage(role="user", content="Hello")]


# ── FallbackProvider Tests ────────────────────────────────────────────

class TestFallbackProvider:
    """Test the FallbackProvider wrapping pattern."""

    def test_primary_succeeds(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        primary = _StubProvider("primary", "primary response")
        fallback = _StubProvider("fallback", "fallback response")
        provider = FallbackProvider(primary, fallback)

        result = provider.complete(SAMPLE_MESSAGES)
        assert result.content == "primary response"
        assert primary.call_count == 1
        assert fallback.call_count == 0

    def test_fallback_on_primary_failure(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        primary = _FailingProvider()
        fallback = _StubProvider("fallback", "fallback response")
        provider = FallbackProvider(primary, fallback)

        result = provider.complete(SAMPLE_MESSAGES)
        assert result.content == "fallback response"
        assert fallback.call_count == 1

    def test_structured_fallback(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        primary = _FailingProvider()
        fallback = _StubProvider("fallback", "structured")
        provider = FallbackProvider(primary, fallback)

        result = provider.generate_structured(SAMPLE_MESSAGES, schema={"type": "object"})
        assert "structured" in result.content

    def test_name_format(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        provider = FallbackProvider(
            _StubProvider("a"), _StubProvider("b")
        )
        assert provider.name == "fallback(a|b)"

    def test_get_model_name_from_primary(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        provider = FallbackProvider(
            _StubProvider("primary-model"), _StubProvider("fallback-model")
        )
        assert provider.get_model_name() == "primary-model"

    def test_both_fail_raises(self) -> None:
        from agentos.lm.providers.fallback import FallbackProvider

        provider = FallbackProvider(_FailingProvider(), _FailingProvider())
        with pytest.raises(RuntimeError, match="Provider failed"):
            provider.complete(SAMPLE_MESSAGES)


# ── ManagedProxyProvider Tests ────────────────────────────────────────

class TestManagedProxyProvider:
    """Test the ManagedProxyProvider with a local HTTP server."""

    @pytest.fixture()
    def mock_server(self) -> tuple[HTTPServer, str]:
        """Start a local HTTP server mimicking OpenAI chat completions."""

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                content_len = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_len))

                response = {
                    "choices": [
                        {"message": {"content": f"echo:{body['model']}"}}
                    ],
                    "usage": {
                        "total_tokens": 42,
                        "prompt_tokens": 20,
                        "completion_tokens": 22,
                    },
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            def log_message(self, format: str, *args: Any) -> None:
                pass  # Suppress logs during tests

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server, f"http://127.0.0.1:{port}"
        server.shutdown()

    def test_complete(self, mock_server: tuple[HTTPServer, str]) -> None:
        from agentos.lm.providers.managed import ManagedProxyProvider

        _, url = mock_server
        provider = ManagedProxyProvider(model="test-model", proxy_url=url)

        result = provider.complete(SAMPLE_MESSAGES)
        assert result.content == "echo:test-model"
        assert result.tokens_used == 42

    def test_auth_header(self, mock_server: tuple[HTTPServer, str]) -> None:
        from agentos.lm.providers.managed import ManagedProxyProvider

        _, url = mock_server
        provider = ManagedProxyProvider(
            model="test-model", proxy_url=url, proxy_key="secret-key"
        )
        # Should not raise (auth header accepted)
        result = provider.complete(SAMPLE_MESSAGES)
        assert result.content == "echo:test-model"

    def test_name_format(self) -> None:
        from agentos.lm.providers.managed import ManagedProxyProvider

        provider = ManagedProxyProvider(model="gpt-4o", proxy_url="http://x")
        assert provider.name == "managed-gpt-4o"

    def test_connection_failure(self) -> None:
        from agentos.lm.providers.managed import ManagedProxyProvider

        # Use a port that nothing is listening on
        provider = ManagedProxyProvider(
            model="test", proxy_url="http://127.0.0.1:1", timeout=1
        )
        with pytest.raises(RuntimeError, match="Failed to connect"):
            provider.complete(SAMPLE_MESSAGES)


# ── Provider Factory Routing Tests ────────────────────────────────────

class TestProviderFactoryRouting:
    """Test the _make_provider_factory routing logic."""

    def test_openai_model_routing(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings(openai_api_key="sk-test-key")
        factory = _make_provider_factory(settings)

        with patch("agentos.lm.providers.openai.OpenAIProvider") as mock_cls:
            mock_cls.return_value = _StubProvider("openai")
            provider = factory("gpt-4o")
            mock_cls.assert_called_once_with(model="gpt-4o", api_key="sk-test-key")

    def test_anthropic_model_routing(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings(anthropic_api_key="sk-ant-test")
        factory = _make_provider_factory(settings)

        with patch("agentos.lm.providers.anthropic.AnthropicProvider") as mock_cls:
            mock_cls.return_value = _StubProvider("anthropic")
            provider = factory("claude-sonnet-4-5-20250929")
            mock_cls.assert_called_once_with(
                model="claude-sonnet-4-5-20250929", api_key="sk-ant-test"
            )

    def test_managed_proxy_routing(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings(
            managed_proxy_url="http://proxy.example.com",
            managed_proxy_key="key123",
        )
        factory = _make_provider_factory(settings)

        with patch("agentos.lm.providers.managed.ManagedProxyProvider") as mock_cls:
            mock_cls.return_value = _StubProvider("managed")
            provider = factory("some-custom-model")
            mock_cls.assert_called_once_with(
                model="some-custom-model",
                proxy_url="http://proxy.example.com",
                proxy_key="key123",
            )

    def test_openai_without_key_raises(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings()  # No API keys
        factory = _make_provider_factory(settings)

        with pytest.raises(RuntimeError, match="OpenAI API key required"):
            factory("gpt-4o")

    def test_anthropic_without_key_raises(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings()
        factory = _make_provider_factory(settings)

        with pytest.raises(RuntimeError, match="Anthropic API key required"):
            factory("claude-sonnet-4-5-20250929")

    def test_o1_routes_to_openai(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings(openai_api_key="sk-test")
        factory = _make_provider_factory(settings)

        with patch("agentos.lm.providers.openai.OpenAIProvider") as mock_cls:
            mock_cls.return_value = _StubProvider("openai")
            factory("o1")
            mock_cls.assert_called_once_with(model="o1", api_key="sk-test")

    def test_o3_mini_routes_to_openai(self) -> None:
        from agentplatform.settings import PlatformSettings
        from agentplatform.server import _make_provider_factory

        settings = PlatformSettings(openai_api_key="sk-test")
        factory = _make_provider_factory(settings)

        with patch("agentos.lm.providers.openai.OpenAIProvider") as mock_cls:
            mock_cls.return_value = _StubProvider("openai")
            factory("o3-mini")
            mock_cls.assert_called_once_with(model="o3-mini", api_key="sk-test")
