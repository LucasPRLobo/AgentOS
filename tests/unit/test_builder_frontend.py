"""Tests for visual workflow builder frontend components.

These tests verify:
1. Component files exist with correct structure
2. Builder backend YAML round-trip works with builder-generated data
3. Export format is valid for WorkflowDefinition parsing
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentos.dashboard.builder import WorkflowBuilder

FRONTEND_SRC = Path(__file__).parent.parent.parent / "agentos" / "dashboard" / "frontend" / "src"


class TestComponentFilesExist:
    def test_node_palette_exists(self):
        path = FRONTEND_SRC / "components" / "builder" / "NodePalette.tsx"
        assert path.exists()
        content = path.read_text()
        assert "NodePalette" in content
        assert "PaletteItem" in content
        assert "draggable" in content

    def test_canvas_exists(self):
        path = FRONTEND_SRC / "components" / "builder" / "Canvas.tsx"
        assert path.exists()
        content = path.read_text()
        assert "Canvas" in content
        assert "CanvasNode" in content
        assert "CanvasEdge" in content

    def test_property_panel_exists(self):
        path = FRONTEND_SRC / "components" / "builder" / "PropertyPanel.tsx"
        assert path.exists()
        content = path.read_text()
        assert "PropertyPanel" in content
        assert "useBuilder" in content
        assert "DELETE_TASK" in content

    def test_export_import_exists(self):
        path = FRONTEND_SRC / "components" / "builder" / "ExportImport.tsx"
        assert path.exists()
        content = path.read_text()
        assert "ExportImport" in content
        assert "onImport" in content

    def test_builder_page_exists(self):
        path = FRONTEND_SRC / "pages" / "BuilderPage.tsx"
        assert path.exists()
        content = path.read_text()
        assert "BuilderPage" in content
        assert "NodePalette" in content
        assert "Canvas" in content
        assert "PropertyPanel" in content

    def test_app_has_builder_route(self):
        path = FRONTEND_SRC / "App.tsx"
        content = path.read_text()
        assert "/builder" in content
        assert "BuilderPage" in content


class TestPaletteItems:
    """Verify NodePalette has the expected node types."""

    def test_palette_has_task_type(self):
        content = (FRONTEND_SRC / "components" / "builder" / "NodePalette.tsx").read_text()
        assert "'task'" in content

    def test_palette_has_gate_type(self):
        content = (FRONTEND_SRC / "components" / "builder" / "NodePalette.tsx").read_text()
        assert "'gate'" in content

    def test_palette_has_adversarial_type(self):
        content = (FRONTEND_SRC / "components" / "builder" / "NodePalette.tsx").read_text()
        assert "'adversarial'" in content

    def test_palette_has_filter(self):
        content = (FRONTEND_SRC / "components" / "builder" / "NodePalette.tsx").read_text()
        assert "palette-filter" in content


class TestCanvasInteractions:
    """Verify Canvas supports drag, select, and edge rendering."""

    def test_canvas_has_drag_handlers(self):
        content = (FRONTEND_SRC / "components" / "builder" / "Canvas.tsx").read_text()
        assert "onDrop" in content
        assert "onDragOver" in content
        assert "onMouseMove" in content
        assert "onMouseUp" in content

    def test_canvas_renders_edges(self):
        content = (FRONTEND_SRC / "components" / "builder" / "Canvas.tsx").read_text()
        assert "state.edges" in content
        assert "canvas-arrow" in content

    def test_canvas_renders_nodes(self):
        content = (FRONTEND_SRC / "components" / "builder" / "Canvas.tsx").read_text()
        assert "tasks.map" in content
        assert "canvas-node" in content

    def test_canvas_supports_selection(self):
        content = (FRONTEND_SRC / "components" / "builder" / "Canvas.tsx").read_text()
        assert "SELECT_NODE" in content


class TestBuilderBackendWithFrontendData:
    """Test that builder-generated YAML structures pass backend validation."""

    def test_minimal_workflow_from_builder(self):
        builder = WorkflowBuilder()
        yaml_str = yaml.dump({
            "name": "builder-workflow",
            "version": "1.0",
            "agents": {"agent1": {"adapter": "tier1", "model": "claude-sonnet-4-20250514", "role": "helper"}},
            "tasks": {
                "task_1": {"name": "task_1", "agent": "agent1", "description": "A task"},
            },
        })
        result = builder.validate_workflow(yaml_str)
        assert result.valid is True

    def test_workflow_with_edges_as_depends_on(self):
        builder = WorkflowBuilder()
        yaml_str = yaml.dump({
            "name": "builder-dag",
            "version": "1.0",
            "agents": {"agent1": {"adapter": "tier1", "model": "claude-sonnet-4-20250514", "role": "helper"}},
            "tasks": {
                "step_1": {"name": "step_1", "agent": "agent1", "description": "First"},
                "step_2": {"name": "step_2", "agent": "agent1", "description": "Second", "depends_on": ["step_1"]},
            },
        })
        result = builder.validate_workflow(yaml_str)
        assert result.valid is True

    def test_json_yaml_roundtrip_preserves_structure(self):
        original = {
            "name": "roundtrip-test",
            "version": "1.0",
            "agents": {},
            "tasks": {"t1": {"name": "t1", "description": "test"}},
        }
        json_str = json.dumps(original)
        yaml_str = WorkflowBuilder.json_to_yaml(json_str)
        json_str2 = WorkflowBuilder.yaml_to_json(yaml_str)
        restored = json.loads(json_str2)
        assert original == restored

    def test_store_and_retrieve_builder_template(self):
        builder = WorkflowBuilder()
        yaml_str = yaml.dump({"name": "template-test", "version": "1.0", "agents": {}, "tasks": {}})
        template = builder.create_template("Builder Template", yaml_str, "Created via builder")
        retrieved = builder.get_template(template.template_id)
        assert retrieved is not None
        assert retrieved.name == "Builder Template"
        parsed = yaml.safe_load(retrieved.workflow_yaml)
        assert parsed["name"] == "template-test"
