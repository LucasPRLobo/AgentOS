"""Tests for the workflow validation engine."""

import pytest

from agentos.runtime.workflow_validator import ValidationIssue, validate_workflow
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.workflow import (
    DataContract,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeConfig,
)


def _node(nid: str, model: str = "gpt-4o-mini", tools: list[str] | None = None) -> WorkflowNode:
    return WorkflowNode(
        id=nid,
        role="agent",
        display_name=f"Agent {nid}",
        config=WorkflowNodeConfig(model=model, tools=tools or []),
    )


def _edge(src: str, tgt: str) -> WorkflowEdge:
    return WorkflowEdge(source=src, target=tgt)


class TestValidateWorkflow:
    def test_valid_linear(self) -> None:
        wf = WorkflowDefinition(
            name="Linear",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("a", "b"), _edge("b", "c")],
        )
        issues = validate_workflow(wf)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == []

    def test_valid_single_node(self) -> None:
        wf = WorkflowDefinition(name="Solo", nodes=[_node("a")])
        issues = validate_workflow(wf)
        assert [i for i in issues if i.severity == "error"] == []

    def test_empty_nodes_error(self) -> None:
        wf = WorkflowDefinition(name="Empty", nodes=[])
        issues = validate_workflow(wf)
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert "at least one node" in issues[0].message

    def test_duplicate_node_ids(self) -> None:
        wf = WorkflowDefinition(
            name="Dupes",
            nodes=[_node("a"), _node("a")],
        )
        issues = validate_workflow(wf)
        assert any("Duplicate node ID" in i.message for i in issues)

    def test_invalid_edge_source(self) -> None:
        wf = WorkflowDefinition(
            name="Bad Edge",
            nodes=[_node("a")],
            edges=[_edge("nonexistent", "a")],
        )
        issues = validate_workflow(wf)
        assert any("source 'nonexistent' not found" in i.message for i in issues)

    def test_invalid_edge_target(self) -> None:
        wf = WorkflowDefinition(
            name="Bad Edge",
            nodes=[_node("a")],
            edges=[_edge("a", "nonexistent")],
        )
        issues = validate_workflow(wf)
        assert any("target 'nonexistent' not found" in i.message for i in issues)

    def test_self_loop(self) -> None:
        wf = WorkflowDefinition(
            name="Self Loop",
            nodes=[_node("a")],
            edges=[_edge("a", "a")],
        )
        issues = validate_workflow(wf)
        assert any("Self-loop" in i.message for i in issues)

    def test_cycle_detection(self) -> None:
        wf = WorkflowDefinition(
            name="Cycle",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("a", "b"), _edge("b", "c"), _edge("c", "a")],
        )
        issues = validate_workflow(wf)
        assert any("cycle" in i.message.lower() for i in issues)

    def test_orphaned_node_warning(self) -> None:
        wf = WorkflowDefinition(
            name="Orphan",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("a", "b")],
        )
        issues = validate_workflow(wf)
        warnings = [i for i in issues if i.severity == "warning"]
        assert any("no connections" in w.message for w in warnings)

    def test_unknown_tool_error(self) -> None:
        wf = WorkflowDefinition(
            name="Bad Tool",
            nodes=[_node("a", tools=["web_search", "nonexistent_tool"])],
        )
        issues = validate_workflow(wf, available_tools={"web_search"})
        assert any("nonexistent_tool" in i.message for i in issues)

    def test_unknown_model_warning(self) -> None:
        wf = WorkflowDefinition(
            name="Bad Model",
            nodes=[_node("a", model="super-unknown-model")],
        )
        issues = validate_workflow(wf, available_models={"gpt-4o-mini"})
        assert any("super-unknown-model" in i.message for i in issues)

    def test_valid_data_contract(self) -> None:
        contract = DataContract(
            output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        )
        wf = WorkflowDefinition(
            name="Contract",
            nodes=[_node("a"), _node("b")],
            edges=[WorkflowEdge(source="a", target="b", data_contract=contract)],
        )
        issues = validate_workflow(wf)
        assert [i for i in issues if i.severity == "error"] == []

    def test_data_contract_missing_type_warning(self) -> None:
        contract = DataContract(
            output_schema={"properties": {"x": {"type": "string"}}},
        )
        wf = WorkflowDefinition(
            name="Contract Warning",
            nodes=[_node("a"), _node("b")],
            edges=[WorkflowEdge(source="a", target="b", data_contract=contract)],
        )
        issues = validate_workflow(wf)
        assert any("missing 'type'" in i.message for i in issues)

    def test_parallel_dag(self) -> None:
        """Diamond DAG: a → b, a → c, b → d, c → d."""
        wf = WorkflowDefinition(
            name="Diamond",
            nodes=[_node("a"), _node("b"), _node("c"), _node("d")],
            edges=[_edge("a", "b"), _edge("a", "c"), _edge("b", "d"), _edge("c", "d")],
        )
        issues = validate_workflow(wf)
        assert [i for i in issues if i.severity == "error"] == []
