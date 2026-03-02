"""Platform settings — local configuration persistence."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_DIR = os.path.expanduser("~/.agentos")
_SETTINGS_FILE = "settings.json"


class PlatformSettings(BaseModel):
    """User-configurable platform settings, persisted to local filesystem."""

    # Model provider API keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Ollama configuration
    ollama_base_url: str = "http://localhost:11434"

    # Managed proxy (optional)
    managed_proxy_url: str | None = None
    managed_proxy_key: str | None = None

    # Default model for NL generation and other platform-level LLM calls
    default_model: str = "gpt-4o-mini"

    # Directories
    workspace_dir: str = Field(
        default_factory=lambda: os.path.expanduser("~/.agentos/workspaces")
    )
    workflows_dir: str = Field(
        default_factory=lambda: os.path.expanduser("~/.agentos/workflows")
    )

    # Integration tokens
    google_oauth_token: str | None = None
    slack_bot_token: str | None = None

    def mask_keys(self) -> dict:
        """Return settings with API keys masked for display."""
        data = self.model_dump()
        for key in ("openai_api_key", "anthropic_api_key", "managed_proxy_key",
                     "google_oauth_token", "slack_bot_token"):
            val = data.get(key)
            if val:
                data[key] = val[:8] + "..." + val[-4:] if len(val) > 12 else "****"
        return data

    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    def has_managed(self) -> bool:
        return bool(self.managed_proxy_url)


class SettingsManager:
    """Manages loading and saving platform settings from local filesystem."""

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = Path(config_dir or _DEFAULT_DIR)

    @property
    def _settings_path(self) -> Path:
        return self._config_dir / _SETTINGS_FILE

    def load(self) -> PlatformSettings:
        """Load settings from disk. Returns defaults if file doesn't exist."""
        if not self._settings_path.exists():
            return PlatformSettings()
        try:
            data = json.loads(self._settings_path.read_text())
            return PlatformSettings.model_validate(data)
        except Exception as exc:
            logger.warning("Failed to load settings from %s: %s", self._settings_path, exc)
            return PlatformSettings()

    def save(self, settings: PlatformSettings) -> None:
        """Save settings to disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(
            settings.model_dump_json(indent=2) + "\n"
        )

    def update(self, updates: dict) -> PlatformSettings:
        """Load current settings, apply updates, save, and return."""
        settings = self.load()
        updated = settings.model_copy(update={
            k: v for k, v in updates.items() if v is not None
        })
        self.save(updated)
        return updated
