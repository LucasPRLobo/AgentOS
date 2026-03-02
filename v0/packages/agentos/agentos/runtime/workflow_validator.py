"""Workflow validation engine — checks WorkflowDefinition before execution."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from agentos.schemas.workflow import WorkflowDefinition


class ValidationIssue(BaseModel):
    """A single validation problem found in a workflow."""

    node_id: str | None = None
    edge_index: int | None = None
    severity: str = Field(description="'error' or 'warning'")
    message: str


def validate_workflow(
    workflow: WorkflowDefinition,
    *,
    available_tools: set[str] | None = None,
    available_models: set[str] | None = None,
) -> list[ValidationIssue]:
    """Validate a workflow definition's structure and configuration.

    Returns a list of issues (empty = valid). Issues with severity 'error'
    block execution; 'warning' issues are informational.

    Checks performed:
    - At least one node exists
    - No duplicate node IDs
    - All edge sources/targets reference valid nodes
    - No cycles in the graph
    - No orphaned nodes (except single-node workflows)
    - All node tool references exist (if available_tools provided)
    - All node model references exist (if available_models provided)
    - Budget specs have positive values (if specified)
    - Data contracts have valid JSON Schema structure (basic check)
    """
    issues: list[ValidationIssue] = []

    # At least one node
    if not workflow.nodes:
        issues.append(ValidationIssue(
            severity="error",
            message="Workflow must have at least one node",
        ))
        return issues

    # Duplicate node IDs
    node_ids = set[str]()
    for node in workflow.nodes:
        if node.id in node_ids:
            issues.append(ValidationIssue(
                node_id=node.id,
                severity="error",
                message=f"Duplicate node ID: '{node.id}'",
            ))
        node_ids.add(node.id)

    # Edge references
    for i, edge in enumerate(workflow.edges):
        if edge.source not in node_ids:
            issues.append(ValidationIssue(
                edge_index=i,
                severity="error",
                message=f"Edge source '{edge.source}' not found in nodes",
            ))
        if edge.target not in node_ids:
            issues.append(ValidationIssue(
                edge_index=i,
                severity="error",
                message=f"Edge target '{edge.target}' not found in nodes",
            ))
        if edge.source == edge.target:
            issues.append(ValidationIssue(
                edge_index=i,
                severity="error",
                message=f"Self-loop on node '{edge.source}'",
            ))

    # Cycle detection (Kahn's algorithm)
    issues.extend(_check_cycles(workflow, node_ids))

    # Orphaned nodes (no edges at all, in multi-node workflows)
    if len(workflow.nodes) > 1 and workflow.edges:
        connected = set[str]()
        for edge in workflow.edges:
            connected.add(edge.source)
            connected.add(edge.target)
        for node in workflow.nodes:
            if node.id not in connected:
                issues.append(ValidationIssue(
                    node_id=node.id,
                    severity="warning",
                    message=f"Node '{node.display_name}' has no connections",
                ))

    # Tool references
    if available_tools is not None:
        for node in workflow.nodes:
            for tool_name in node.config.tools:
                if tool_name not in available_tools:
                    issues.append(ValidationIssue(
                        node_id=node.id,
                        severity="error",
                        message=f"Unknown tool '{tool_name}' on node '{node.display_name}'",
                    ))

    # Model references
    if available_models is not None:
        for node in workflow.nodes:
            if node.config.model not in available_models:
                issues.append(ValidationIssue(
                    node_id=node.id,
                    severity="warning",
                    message=f"Unknown model '{node.config.model}' on node '{node.display_name}'",
                ))

    # Budget validation
    for node in workflow.nodes:
        if node.config.budget is not None:
            budget = node.config.budget
            if budget.max_tokens <= 0:
                issues.append(ValidationIssue(
                    node_id=node.id,
                    severity="error",
                    message="Budget max_tokens must be positive",
                ))
            if budget.max_time_seconds <= 0:
                issues.append(ValidationIssue(
                    node_id=node.id,
                    severity="error",
                    message="Budget max_time_seconds must be positive",
                ))

    # Data contract basic validation
    for i, edge in enumerate(workflow.edges):
        if edge.data_contract is not None:
            dc = edge.data_contract
            if dc.output_schema is not None:
                issues.extend(_check_json_schema(dc.output_schema, i, "output_schema"))
            if dc.input_schema is not None:
                issues.extend(_check_json_schema(dc.input_schema, i, "input_schema"))

    return issues


def _check_cycles(
    workflow: WorkflowDefinition, node_ids: set[str]
) -> list[ValidationIssue]:
    """Detect cycles using Kahn's algorithm."""
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in workflow.edges:
        if edge.source in node_ids and edge.target in node_ids:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited < len(node_ids):
        return [ValidationIssue(
            severity="error",
            message="Workflow graph contains a cycle",
        )]
    return []


def _check_json_schema(
    schema: dict[str, Any], edge_index: int, field: str
) -> list[ValidationIssue]:
    """Basic structural check on a JSON Schema dict."""
    issues: list[ValidationIssue] = []
    if not isinstance(schema, dict):
        issues.append(ValidationIssue(
            edge_index=edge_index,
            severity="error",
            message=f"Data contract {field} must be a JSON object",
        ))
    elif "type" not in schema:
        issues.append(ValidationIssue(
            edge_index=edge_index,
            severity="warning",
            message=f"Data contract {field} missing 'type' field",
        ))
    return issues
