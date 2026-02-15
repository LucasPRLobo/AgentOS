"""Tests for WorkflowDefinition data model."""

import json

import pytest

from agentos.schemas.budget import BudgetSpec
from agentos.schemas.workflow import (
    AdvancedModelConfig,
    DataContract,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeConfig,
    WorkflowVariable,
)


def _make_node(node_id: str = "n1", model: str = "gpt-4o-mini") -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        role="researcher",
        display_name="Researcher",
        config=WorkflowNodeConfig(model=model),
    )


class TestWorkflowNodeConfig:
    def test_defaults(self) -> None:
        cfg = WorkflowNodeConfig(model="gpt-4o-mini")
        assert cfg.persona_preset == "analytical"
        assert cfg.tools == []
        assert cfg.budget is None
        assert cfg.max_steps == 50
        assert cfg.advanced is None

    def test_with_budget(self) -> None:
        budget = BudgetSpec(
            max_tokens=10_000,
            max_tool_calls=10,
            max_time_seconds=60.0,
            max_recursion_depth=1,
        )
        cfg = WorkflowNodeConfig(model="gpt-4o", budget=budget)
        assert cfg.budget.max_tokens == 10_000

    def test_with_advanced(self) -> None:
        adv = AdvancedModelConfig(temperature=0.2, max_output_tokens=1024)
        cfg = WorkflowNodeConfig(model="gpt-4o", advanced=adv)
        assert cfg.advanced.temperature == 0.2


class TestWorkflowDefinition:
    def test_minimal(self) -> None:
        wf = WorkflowDefinition(
            name="Test Workflow",
            nodes=[_make_node()],
        )
        assert wf.name == "Test Workflow"
        assert len(wf.nodes) == 1
        assert wf.edges == []
        assert wf.variables == []
        assert wf.id  # Auto-generated

    def test_with_edges(self) -> None:
        wf = WorkflowDefinition(
            name="Pipeline",
            nodes=[_make_node("n1"), _make_node("n2")],
            edges=[WorkflowEdge(source="n1", target="n2")],
        )
        assert len(wf.edges) == 1
        assert wf.edges[0].source == "n1"

    def test_with_data_contract(self) -> None:
        contract = DataContract(
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
            input_schema={"type": "object", "required": ["summary"]},
        )
        edge = WorkflowEdge(source="n1", target="n2", data_contract=contract)
        assert edge.data_contract.output_schema["type"] == "object"

    def test_with_variables(self) -> None:
        wf = WorkflowDefinition(
            name="Parameterized",
            nodes=[_make_node()],
            variables=[WorkflowVariable(name="topic", default="AI")],
        )
        assert wf.variables[0].name == "topic"

    def test_json_roundtrip(self) -> None:
        wf = WorkflowDefinition(
            name="Roundtrip Test",
            nodes=[_make_node("a"), _make_node("b")],
            edges=[WorkflowEdge(source="a", target="b")],
            domain_pack="labos",
        )
        data = json.loads(wf.model_dump_json())
        restored = WorkflowDefinition.model_validate(data)
        assert restored.name == wf.name
        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1
        assert restored.domain_pack == "labos"

    def test_auto_generated_fields(self) -> None:
        wf = WorkflowDefinition(name="Auto", nodes=[_make_node()])
        assert wf.id
        assert wf.created_at
        assert wf.updated_at
        assert wf.version == "1.0.0"
