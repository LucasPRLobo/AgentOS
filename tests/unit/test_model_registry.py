"""Tests for the model capability registry."""

import pytest

from agentos.lm.model_registry import (
    get_all_capabilities,
    get_capabilities,
    get_capabilities_or_none,
    list_known_models,
    list_models_by_provider,
    register_model,
)
from agentos.lm.provider import ModelCapabilities


class TestGetCapabilities:
    """Test get_capabilities returns correct data for known models."""

    def test_known_openai_model(self) -> None:
        caps = get_capabilities("gpt-4o")
        assert caps.provider == "openai"
        assert caps.context_window == 128_000
        assert caps.supports_tool_use is True
        assert caps.supports_structured_output is True

    def test_known_anthropic_model(self) -> None:
        caps = get_capabilities("claude-sonnet-4-5-20250929")
        assert caps.provider == "anthropic"
        assert caps.context_window == 200_000
        assert caps.supports_vision is True

    def test_known_ollama_model(self) -> None:
        caps = get_capabilities("llama3.2:latest")
        assert caps.provider == "ollama"
        assert caps.cost_per_1k_input == 0.0
        assert caps.cost_per_1k_output == 0.0

    def test_unknown_model_returns_defaults(self) -> None:
        caps = get_capabilities("totally-unknown-model-xyz")
        assert caps.provider == "unknown"
        assert caps.context_window == 8_192
        assert caps.supports_structured_output is False


class TestGetCapabilitiesOrNone:
    def test_known_model_returns_caps(self) -> None:
        caps = get_capabilities_or_none("gpt-4o-mini")
        assert caps is not None
        assert caps.provider == "openai"

    def test_unknown_model_returns_none(self) -> None:
        assert get_capabilities_or_none("nonexistent") is None


class TestRegisterModel:
    def test_register_new_model(self) -> None:
        caps = ModelCapabilities(
            context_window=16_000,
            provider="custom",
            display_name="Custom Model",
        )
        register_model("custom-test-model", caps)
        assert get_capabilities("custom-test-model") is caps

        # Clean up
        from agentos.lm import model_registry
        model_registry._REGISTRY.pop("custom-test-model", None)

    def test_overwrite_existing(self) -> None:
        original = get_capabilities("gpt-4o")
        new_caps = ModelCapabilities(context_window=999, provider="openai")
        register_model("gpt-4o", new_caps)
        assert get_capabilities("gpt-4o").context_window == 999

        # Restore
        register_model("gpt-4o", original)


class TestListModels:
    def test_list_known_models(self) -> None:
        models = list_known_models()
        assert isinstance(models, list)
        assert "gpt-4o" in models
        assert "claude-sonnet-4-5-20250929" in models
        assert models == sorted(models)  # Should be sorted

    def test_list_by_provider_openai(self) -> None:
        models = list_models_by_provider("openai")
        assert all("gpt" in m or m.startswith("o") for m in models)
        assert len(models) >= 3  # At least gpt-4o, gpt-4o-mini, o1, o3-mini

    def test_list_by_provider_anthropic(self) -> None:
        models = list_models_by_provider("anthropic")
        assert all(m.startswith("claude-") for m in models)
        assert len(models) >= 2

    def test_list_by_provider_ollama(self) -> None:
        models = list_models_by_provider("ollama")
        assert len(models) >= 3

    def test_list_by_unknown_provider(self) -> None:
        models = list_models_by_provider("nonexistent")
        assert models == []


class TestGetAllCapabilities:
    def test_returns_dict(self) -> None:
        all_caps = get_all_capabilities()
        assert isinstance(all_caps, dict)
        assert len(all_caps) >= 10

    def test_values_are_capabilities(self) -> None:
        for name, caps in get_all_capabilities().items():
            assert isinstance(caps, ModelCapabilities)
            assert isinstance(name, str)
