"""Model capability registry — static catalog of known model capabilities."""

from __future__ import annotations

from agentos.lm.provider import ModelCapabilities

# ── Known Model Capabilities ─────────────────────────────────────────────

_REGISTRY: dict[str, ModelCapabilities] = {
    # OpenAI models
    "gpt-4o": ModelCapabilities(
        context_window=128_000,
        max_output_tokens=16_384,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
        provider="openai",
        display_name="GPT-4o",
    ),
    "gpt-4o-mini": ModelCapabilities(
        context_window=128_000,
        max_output_tokens=16_384,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        provider="openai",
        display_name="GPT-4o mini",
    ),
    "o1": ModelCapabilities(
        context_window=200_000,
        max_output_tokens=100_000,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.06,
        provider="openai",
        display_name="o1",
    ),
    "o3-mini": ModelCapabilities(
        context_window=200_000,
        max_output_tokens=100_000,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=False,
        cost_per_1k_input=0.0011,
        cost_per_1k_output=0.0044,
        provider="openai",
        display_name="o3-mini",
    ),
    # Anthropic models
    "claude-sonnet-4-5-20250929": ModelCapabilities(
        context_window=200_000,
        max_output_tokens=8_192,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        provider="anthropic",
        display_name="Claude Sonnet 4.5",
    ),
    "claude-haiku-4-5-20251001": ModelCapabilities(
        context_window=200_000,
        max_output_tokens=8_192,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.0008,
        cost_per_1k_output=0.004,
        provider="anthropic",
        display_name="Claude Haiku 4.5",
    ),
    "claude-opus-4-6": ModelCapabilities(
        context_window=200_000,
        max_output_tokens=16_384,
        supports_structured_output=True,
        supports_tool_use=True,
        supports_vision=True,
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.075,
        provider="anthropic",
        display_name="Claude Opus 4.6",
    ),
    # Local / Ollama models (approximate)
    "llama3.2:latest": ModelCapabilities(
        context_window=8_192,
        max_output_tokens=4_096,
        supports_structured_output=False,
        supports_tool_use=False,
        supports_vision=False,
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        provider="ollama",
        display_name="Llama 3.2 (3B)",
    ),
    "llama3.1:8b": ModelCapabilities(
        context_window=131_072,
        max_output_tokens=4_096,
        supports_structured_output=False,
        supports_tool_use=False,
        supports_vision=False,
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        provider="ollama",
        display_name="Llama 3.1 (8B)",
    ),
    "mistral:latest": ModelCapabilities(
        context_window=32_768,
        max_output_tokens=4_096,
        supports_structured_output=False,
        supports_tool_use=False,
        supports_vision=False,
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        provider="ollama",
        display_name="Mistral (7B)",
    ),
    "qwen2.5:latest": ModelCapabilities(
        context_window=32_768,
        max_output_tokens=4_096,
        supports_structured_output=False,
        supports_tool_use=False,
        supports_vision=False,
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        provider="ollama",
        display_name="Qwen 2.5",
    ),
}

# ── Default capabilities for unknown models ──────────────────────────────

_DEFAULT = ModelCapabilities(
    context_window=8_192,
    max_output_tokens=4_096,
    supports_structured_output=False,
    supports_tool_use=False,
    supports_vision=False,
    cost_per_1k_input=0.0,
    cost_per_1k_output=0.0,
    provider="unknown",
    display_name="Unknown Model",
)


# ── Public API ───────────────────────────────────────────────────────────


def get_capabilities(model: str) -> ModelCapabilities:
    """Return capabilities for a model. Falls back to defaults if unknown."""
    return _REGISTRY.get(model, _DEFAULT)


def get_capabilities_or_none(model: str) -> ModelCapabilities | None:
    """Return capabilities for a model, or None if unknown."""
    return _REGISTRY.get(model)


def register_model(model: str, capabilities: ModelCapabilities) -> None:
    """Register or update capabilities for a model."""
    _REGISTRY[model] = capabilities


def list_known_models() -> list[str]:
    """Return all registered model identifiers."""
    return sorted(_REGISTRY.keys())


def list_models_by_provider(provider: str) -> list[str]:
    """Return model identifiers for a specific provider."""
    return sorted(k for k, v in _REGISTRY.items() if v.provider == provider)


def get_all_capabilities() -> dict[str, ModelCapabilities]:
    """Return the full registry as a dict."""
    return dict(_REGISTRY)
