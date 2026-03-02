"""Tests for LM provider — LMMessage, LMResponse, BaseLMProvider."""

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse


class MockLMProvider(BaseLMProvider):
    """Deterministic mock LM provider for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses) if responses else ["Hello"]
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        return LMResponse(
            content=content,
            tokens_used=len(content),
            prompt_tokens=sum(len(m.content) for m in messages),
            completion_tokens=len(content),
        )


class TestLMMessage:
    def test_creation(self) -> None:
        msg = LMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_serialization_roundtrip(self) -> None:
        msg = LMMessage(role="system", content="You are helpful")
        data = msg.model_dump_json()
        restored = LMMessage.model_validate_json(data)
        assert restored.role == msg.role
        assert restored.content == msg.content

    def test_all_roles(self) -> None:
        for role in ("system", "user", "assistant"):
            msg = LMMessage(role=role, content="test")
            assert msg.role == role


class TestLMResponse:
    def test_creation(self) -> None:
        resp = LMResponse(content="Hi", tokens_used=5)
        assert resp.content == "Hi"
        assert resp.tokens_used == 5
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0

    def test_full_fields(self) -> None:
        resp = LMResponse(
            content="answer",
            tokens_used=100,
            prompt_tokens=80,
            completion_tokens=20,
        )
        assert resp.prompt_tokens == 80
        assert resp.completion_tokens == 20

    def test_serialization_roundtrip(self) -> None:
        resp = LMResponse(content="test", tokens_used=10, prompt_tokens=5, completion_tokens=5)
        data = resp.model_dump_json()
        restored = LMResponse.model_validate_json(data)
        assert restored.content == resp.content
        assert restored.tokens_used == resp.tokens_used

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(Exception):
            LMResponse(content="x", tokens_used=-1)


class TestMockLMProvider:
    def test_name(self) -> None:
        provider = MockLMProvider()
        assert provider.name == "mock"

    def test_basic_complete(self) -> None:
        provider = MockLMProvider(["FINAL = 42"])
        messages = [LMMessage(role="user", content="test")]
        response = provider.complete(messages)
        assert response.content == "FINAL = 42"
        assert response.tokens_used == len("FINAL = 42")

    def test_sequential_responses(self) -> None:
        provider = MockLMProvider(["first", "second", "third"])
        msg = [LMMessage(role="user", content="go")]
        assert provider.complete(msg).content == "first"
        assert provider.complete(msg).content == "second"
        assert provider.complete(msg).content == "third"

    def test_repeats_last_response(self) -> None:
        provider = MockLMProvider(["only"])
        msg = [LMMessage(role="user", content="go")]
        assert provider.complete(msg).content == "only"
        assert provider.complete(msg).content == "only"
