"""Tests for platform settings storage and management."""

import json
import tempfile
from pathlib import Path

import pytest

from agentplatform.settings import PlatformSettings, SettingsManager


class TestPlatformSettings:
    """Test PlatformSettings model."""

    def test_defaults(self) -> None:
        s = PlatformSettings()
        assert s.openai_api_key is None
        assert s.anthropic_api_key is None
        assert s.ollama_base_url == "http://localhost:11434"
        assert s.managed_proxy_url is None
        assert s.default_model == "gpt-4o-mini"

    def test_has_openai(self) -> None:
        assert PlatformSettings().has_openai() is False
        assert PlatformSettings(openai_api_key="sk-123").has_openai() is True

    def test_has_anthropic(self) -> None:
        assert PlatformSettings().has_anthropic() is False
        assert PlatformSettings(anthropic_api_key="sk-ant").has_anthropic() is True

    def test_has_managed(self) -> None:
        assert PlatformSettings().has_managed() is False
        assert PlatformSettings(managed_proxy_url="http://x").has_managed() is True

    def test_mask_keys_long(self) -> None:
        s = PlatformSettings(
            openai_api_key="sk-1234567890abcdef",
            anthropic_api_key="sk-ant-abcdef123456",
        )
        masked = s.mask_keys()
        # Long keys: first 8 chars + "..." + last 4 chars
        assert masked["openai_api_key"].startswith("sk-12345")
        assert "..." in masked["openai_api_key"]
        assert masked["openai_api_key"].endswith("cdef")
        assert "1234567890abcdef" not in masked["openai_api_key"]

    def test_mask_keys_short(self) -> None:
        s = PlatformSettings(openai_api_key="short")
        masked = s.mask_keys()
        assert masked["openai_api_key"] == "****"

    def test_mask_keys_none(self) -> None:
        s = PlatformSettings()
        masked = s.mask_keys()
        assert masked["openai_api_key"] is None

    def test_model_dump_roundtrip(self) -> None:
        s = PlatformSettings(
            openai_api_key="key",
            default_model="gpt-4o",
        )
        data = json.loads(s.model_dump_json())
        restored = PlatformSettings.model_validate(data)
        assert restored.openai_api_key == "key"
        assert restored.default_model == "gpt-4o"


class TestSettingsManager:
    """Test SettingsManager load/save/update cycle."""

    @pytest.fixture()
    def tmp_dir(self, tmp_path: Path) -> Path:
        """Return a temporary directory for settings."""
        return tmp_path / "config"

    def test_load_defaults_when_no_file(self, tmp_dir: Path) -> None:
        sm = SettingsManager(str(tmp_dir))
        s = sm.load()
        assert s.openai_api_key is None
        assert s.default_model == "gpt-4o-mini"

    def test_save_and_load(self, tmp_dir: Path) -> None:
        sm = SettingsManager(str(tmp_dir))
        original = PlatformSettings(
            openai_api_key="sk-test",
            default_model="gpt-4o",
        )
        sm.save(original)

        loaded = sm.load()
        assert loaded.openai_api_key == "sk-test"
        assert loaded.default_model == "gpt-4o"

    def test_update_partial(self, tmp_dir: Path) -> None:
        sm = SettingsManager(str(tmp_dir))
        # Save initial
        sm.save(PlatformSettings(default_model="gpt-4o-mini"))

        # Update only one field
        updated = sm.update({"openai_api_key": "sk-new"})
        assert updated.openai_api_key == "sk-new"
        assert updated.default_model == "gpt-4o-mini"  # Preserved

    def test_update_ignores_none(self, tmp_dir: Path) -> None:
        sm = SettingsManager(str(tmp_dir))
        sm.save(PlatformSettings(openai_api_key="sk-old"))

        updated = sm.update({"openai_api_key": None, "default_model": "gpt-4o"})
        assert updated.openai_api_key == "sk-old"  # None is filtered out
        assert updated.default_model == "gpt-4o"

    def test_creates_directory(self, tmp_dir: Path) -> None:
        sm = SettingsManager(str(tmp_dir))
        assert not tmp_dir.exists()
        sm.save(PlatformSettings())
        assert tmp_dir.exists()
        assert (tmp_dir / "settings.json").exists()

    def test_load_corrupt_file_returns_defaults(self, tmp_dir: Path) -> None:
        tmp_dir.mkdir(parents=True)
        (tmp_dir / "settings.json").write_text("not json{{{")

        sm = SettingsManager(str(tmp_dir))
        s = sm.load()
        assert s.default_model == "gpt-4o-mini"  # Defaults

    def test_file_persists_across_managers(self, tmp_dir: Path) -> None:
        sm1 = SettingsManager(str(tmp_dir))
        sm1.save(PlatformSettings(anthropic_api_key="sk-ant"))

        sm2 = SettingsManager(str(tmp_dir))
        loaded = sm2.load()
        assert loaded.anthropic_api_key == "sk-ant"
