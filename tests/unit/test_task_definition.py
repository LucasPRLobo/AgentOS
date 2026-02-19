"""Unit tests for TaskDefinition schema and integration with WorkflowNodeConfig."""

from __future__ import annotations

import json

import pytest

from agentos.schemas.workflow import (
    TaskDefinition,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowNodeConfig,
)


class TestTaskDefinitionModel:
    def test_default_construction(self) -> None:
        td = TaskDefinition()
        assert td.objective == ""
        assert td.deliverables == []
        assert td.acceptance_criteria == []
        assert td.inputs == {}
        assert td.context_files == []

    def test_full_construction(self) -> None:
        td = TaskDefinition(
            objective="Write a report",
            deliverables=["report.md"],
            acceptance_criteria=["Has 5+ sections", "Well-formatted"],
            inputs={"topic": "AI agents"},
            context_files=["outline.md"],
        )
        assert td.objective == "Write a report"
        assert len(td.deliverables) == 1
        assert len(td.acceptance_criteria) == 2
        assert td.inputs["topic"] == "AI agents"
        assert td.context_files == ["outline.md"]

    def test_serialization_roundtrip(self) -> None:
        td = TaskDefinition(
            objective="Analyze data",
            deliverables=["analysis.md", "charts.png"],
            acceptance_criteria=["Includes summary"],
            inputs={"dataset": "sales.csv"},
            context_files=["config.json"],
        )
        data = json.loads(td.model_dump_json())
        restored = TaskDefinition.model_validate(data)
        assert restored == td


class TestWorkflowNodeConfigWithTask:
    def test_config_without_task(self) -> None:
        config = WorkflowNodeConfig(model="gpt-4o")
        assert config.task is None

    def test_config_with_task(self) -> None:
        config = WorkflowNodeConfig(
            model="gpt-4o",
            task=TaskDefinition(objective="Write report"),
        )
        assert config.task is not None
        assert config.task.objective == "Write report"

    def test_config_task_none_explicit(self) -> None:
        config = WorkflowNodeConfig(model="gpt-4o", task=None)
        assert config.task is None

    def test_config_serialization_with_task(self) -> None:
        config = WorkflowNodeConfig(
            model="gpt-4o",
            task=TaskDefinition(
                objective="Draft outline",
                deliverables=["outline.md"],
            ),
        )
        data = json.loads(config.model_dump_json())
        restored = WorkflowNodeConfig.model_validate(data)
        assert restored.task is not None
        assert restored.task.objective == "Draft outline"
        assert restored.task.deliverables == ["outline.md"]

    def test_config_serialization_without_task(self) -> None:
        config = WorkflowNodeConfig(model="gpt-4o")
        data = json.loads(config.model_dump_json())
        restored = WorkflowNodeConfig.model_validate(data)
        assert restored.task is None


class TestTemplateParsingCompat:
    """Ensure existing templates (which lack the task field) still parse."""

    def test_template_json_without_task(self) -> None:
        raw = {
            "model": "gpt-4o-mini",
            "system_prompt": "Do something.",
            "persona_preset": "analytical",
            "tools": ["file_write"],
            "budget": None,
            "max_steps": 10,
            "advanced": None,
        }
        config = WorkflowNodeConfig.model_validate(raw)
        assert config.task is None

    def test_bundled_templates_still_parse(self) -> None:
        from agentplatform.template_store import TemplateStore

        store = TemplateStore()
        for summary in store.list():
            wf = store.get(summary.id)
            for node in wf.nodes:
                # Should not raise — task defaults to None
                assert node.config is not None


class TestTaskDefinitionInWorkflow:
    def test_full_workflow_with_tasks(self) -> None:
        wf = WorkflowDefinition(
            name="Pipeline",
            nodes=[
                WorkflowNode(
                    id="a",
                    role="custom",
                    display_name="Outliner",
                    config=WorkflowNodeConfig(
                        model="gpt-4o",
                        task=TaskDefinition(
                            objective="Create outline",
                            deliverables=["outline.md"],
                            acceptance_criteria=["At least 5 sections"],
                        ),
                    ),
                ),
                WorkflowNode(
                    id="b",
                    role="custom",
                    display_name="Writer",
                    config=WorkflowNodeConfig(model="gpt-4o"),
                ),
            ],
        )
        assert wf.nodes[0].config.task is not None
        assert wf.nodes[0].config.task.objective == "Create outline"
        assert wf.nodes[1].config.task is None

        # Roundtrip
        data = json.loads(wf.model_dump_json())
        restored = WorkflowDefinition.model_validate(data)
        assert restored.nodes[0].config.task is not None
        assert restored.nodes[1].config.task is None
