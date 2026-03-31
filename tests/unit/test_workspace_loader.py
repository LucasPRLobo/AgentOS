"""Tests for workspace YAML loader."""

import pytest
import yaml

from agentos.workspace.loader import load_workspace_config, load_workspace_config_from_dict
from agentos.workspace.schemas import TeamMode


@pytest.fixture
def yaml_file(tmp_path):
    data = {
        "workspace": {
            "name": "Test Project",
            "goal": "Build something",
            "team_mode": "dynamic",
            "team": [
                {"name": "agent-a", "type": "agent", "specialization": "Research"},
                {"name": "lucas", "type": "human", "roles": ["lead"]},
            ],
            "documents": ["./data/input.csv"],
        }
    }
    path = tmp_path / "workspace.yaml"
    path.write_text(yaml.dump(data))
    # Create the referenced document
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "input.csv").write_text("a,b,c")
    return path


class TestLoadFromFile:
    def test_loads(self, yaml_file):
        cfg = load_workspace_config(yaml_file)
        assert cfg.name == "Test Project"
        assert cfg.team_mode == TeamMode.SUGGEST  # "dynamic" → "suggest"
        assert len(cfg.team) == 2

    def test_resolves_document_paths(self, yaml_file):
        cfg = load_workspace_config(yaml_file)
        assert len(cfg.documents) == 1
        assert cfg.documents[0].endswith("input.csv")


class TestLoadFromDict:
    def test_basic(self):
        cfg = load_workspace_config_from_dict({
            "name": "t",
            "goal": "g",
            "team_mode": "locked",
        })
        assert cfg.team_mode == TeamMode.LOCKED

    def test_dynamic_alias(self):
        cfg = load_workspace_config_from_dict({"name": "t", "goal": "g", "team_mode": "dynamic"})
        assert cfg.team_mode == TeamMode.SUGGEST

    def test_auto_alias(self):
        cfg = load_workspace_config_from_dict({"name": "t", "goal": "g", "team_mode": "auto"})
        assert cfg.team_mode == TeamMode.AUTO_FULL

    def test_defaults(self):
        cfg = load_workspace_config_from_dict({"name": "t", "goal": "g"})
        assert cfg.coordinator.enabled is True
        assert cfg.team == []
