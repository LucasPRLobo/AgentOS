"""Tests for visual workflow builder backend."""

from __future__ import annotations

import json

import pytest
import yaml

from agentos.dashboard.builder import WorkflowBuilder, WorkflowTemplate


VALID_WORKFLOW_YAML = yaml.dump({
    "name": "test-workflow",
    "version": "1.0",
    "agents": {
        "researcher": {
            "adapter": "tier1",
            "model": "claude-sonnet-4-20250514",
            "role": "Research assistant",
        }
    },
    "tasks": {
        "research": {
            "name": "research",
            "agent": "researcher",
            "description": "Do research",
        }
    },
}, default_flow_style=False)


@pytest.fixture
def builder() -> WorkflowBuilder:
    return WorkflowBuilder()


class TestCRUD:
    def test_create_template(self, builder):
        t = builder.create_template("My Workflow", VALID_WORKFLOW_YAML, "A test workflow")
        assert t.name == "My Workflow"
        assert t.description == "A test workflow"
        assert t.template_id
        assert t.created_at

    def test_get_template(self, builder):
        t = builder.create_template("WF1", VALID_WORKFLOW_YAML)
        retrieved = builder.get_template(t.template_id)
        assert retrieved is not None
        assert retrieved.name == "WF1"
        assert retrieved.workflow_yaml == VALID_WORKFLOW_YAML

    def test_get_nonexistent(self, builder):
        assert builder.get_template("nonexistent") is None

    def test_list_templates(self, builder):
        builder.create_template("WF1", VALID_WORKFLOW_YAML)
        builder.create_template("WF2", VALID_WORKFLOW_YAML)
        templates = builder.list_templates()
        assert len(templates) == 2

    def test_update_template(self, builder):
        t = builder.create_template("WF1", VALID_WORKFLOW_YAML)
        updated = builder.update_template(t.template_id, name="Updated WF")
        assert updated is not None
        assert updated.name == "Updated WF"
        assert updated.workflow_yaml == VALID_WORKFLOW_YAML

    def test_update_nonexistent(self, builder):
        assert builder.update_template("nonexistent", name="X") is None

    def test_update_yaml(self, builder):
        t = builder.create_template("WF1", VALID_WORKFLOW_YAML)
        new_yaml = VALID_WORKFLOW_YAML.replace("test-workflow", "updated-workflow")
        updated = builder.update_template(t.template_id, workflow_yaml=new_yaml)
        assert "updated-workflow" in updated.workflow_yaml

    def test_delete_template(self, builder):
        t = builder.create_template("WF1", VALID_WORKFLOW_YAML)
        assert builder.delete_template(t.template_id) is True
        assert builder.get_template(t.template_id) is None

    def test_delete_nonexistent(self, builder):
        assert builder.delete_template("nonexistent") is False

    def test_template_to_dict(self, builder):
        t = builder.create_template("WF1", VALID_WORKFLOW_YAML, "desc")
        d = t.to_dict()
        assert d["name"] == "WF1"
        assert d["description"] == "desc"
        assert "template_id" in d


class TestValidation:
    def test_valid_workflow(self, builder):
        result = builder.validate_workflow(VALID_WORKFLOW_YAML)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_yaml(self, builder):
        result = builder.validate_workflow("{{invalid yaml")
        assert result.valid is False
        assert any("YAML" in e or "parse" in e for e in result.errors)

    def test_not_a_mapping(self, builder):
        result = builder.validate_workflow("- item1\n- item2")
        assert result.valid is False
        assert any("mapping" in e for e in result.errors)

    def test_missing_required_field(self, builder):
        result = builder.validate_workflow("version: '1.0'\n")
        assert result.valid is False

    def test_validation_result_to_dict(self, builder):
        result = builder.validate_workflow(VALID_WORKFLOW_YAML)
        d = result.to_dict()
        assert d["valid"] is True
        assert d["errors"] == []


class TestYAMLJSONRoundTrip:
    def test_yaml_to_json(self, builder):
        json_str = builder.yaml_to_json(VALID_WORKFLOW_YAML)
        data = json.loads(json_str)
        assert data["name"] == "test-workflow"

    def test_json_to_yaml(self, builder):
        data = {"name": "test-workflow", "version": "1.0", "agents": {}, "tasks": {}}
        json_str = json.dumps(data)
        yaml_str = builder.json_to_yaml(json_str)
        restored = yaml.safe_load(yaml_str)
        assert restored["name"] == "test-workflow"

    def test_round_trip_yaml_json_yaml(self, builder):
        json_str = builder.yaml_to_json(VALID_WORKFLOW_YAML)
        yaml_str = builder.json_to_yaml(json_str)
        original = yaml.safe_load(VALID_WORKFLOW_YAML)
        restored = yaml.safe_load(yaml_str)
        assert original == restored

    def test_round_trip_json_yaml_json(self, builder):
        data = {"name": "wf", "version": "1.0", "agents": {}, "tasks": {}}
        json_str = json.dumps(data)
        yaml_str = builder.json_to_yaml(json_str)
        json_str2 = builder.yaml_to_json(yaml_str)
        assert json.loads(json_str) == json.loads(json_str2)
