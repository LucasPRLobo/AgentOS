"""Tests for the workflow compiler (WorkflowDefinition → DAG)."""

from unittest.mock import MagicMock, patch

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.dag import DAGWorkflow
from agentos.runtime.domain_registry import (
    DomainPackManifest,
    DomainRegistry,
    ToolManifestEntry,
)
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.workspace import Workspace, WorkspaceConfig
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeConfig,
)
from agentplatform.workflow_compiler import compile_workflow


class _StubProvider(BaseLMProvider):
    @property
    def name(self) -> str:
        return "stub"

    def get_model_name(self) -> str:
        return "stub-model"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        return LMResponse(content='{"action": "finish", "result": "done"}',
                          tokens_used=10, prompt_tokens=5, completion_tokens=5)


def _make_workflow(**kwargs) -> WorkflowDefinition:
    defaults = {
        "name": "Test",
        "nodes": [
            WorkflowNode(
                id="a", role="researcher", display_name="Researcher",
                config=WorkflowNodeConfig(model="stub-model"),
            ),
        ],
        "edges": [],
    }
    defaults.update(kwargs)
    return WorkflowDefinition(**defaults)


@pytest.fixture()
def event_log() -> SQLiteEventLog:
    return SQLiteEventLog(":memory:")


@pytest.fixture()
def workspace(tmp_path) -> Workspace:
    return Workspace(WorkspaceConfig(root=str(tmp_path)))


@pytest.fixture()
def registry() -> DomainRegistry:
    return DomainRegistry()


def _factory(model_name: str) -> BaseLMProvider:
    return _StubProvider()


class TestCompileWorkflow:
    def test_single_node(self, event_log, workspace, registry) -> None:
        wf = _make_workflow()
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=_factory,
        )
        assert isinstance(dag, DAGWorkflow)
        assert len(dag.tasks) == 1
        assert dag.tasks[0].name == "Researcher"

    def test_linear_dependencies(self, event_log, workspace, registry) -> None:
        wf = _make_workflow(
            nodes=[
                WorkflowNode(
                    id="a", role="researcher", display_name="Researcher",
                    config=WorkflowNodeConfig(model="stub"),
                ),
                WorkflowNode(
                    id="b", role="writer", display_name="Writer",
                    config=WorkflowNodeConfig(model="stub"),
                ),
            ],
            edges=[WorkflowEdge(source="a", target="b")],
        )
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=_factory,
        )
        assert len(dag.tasks) == 2
        # Writer depends on Researcher
        writer = dag.tasks[1]
        assert len(writer.depends_on) == 1
        assert writer.depends_on[0].name == "Researcher"

    def test_diamond_dag(self, event_log, workspace, registry) -> None:
        """a → b, a → c, b → d, c → d."""
        wf = _make_workflow(
            nodes=[
                WorkflowNode(id="a", role="start", display_name="Start",
                             config=WorkflowNodeConfig(model="stub")),
                WorkflowNode(id="b", role="path1", display_name="Path 1",
                             config=WorkflowNodeConfig(model="stub")),
                WorkflowNode(id="c", role="path2", display_name="Path 2",
                             config=WorkflowNodeConfig(model="stub")),
                WorkflowNode(id="d", role="merge", display_name="Merge",
                             config=WorkflowNodeConfig(model="stub")),
            ],
            edges=[
                WorkflowEdge(source="a", target="b"),
                WorkflowEdge(source="a", target="c"),
                WorkflowEdge(source="b", target="d"),
                WorkflowEdge(source="c", target="d"),
            ],
        )
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=_factory,
        )
        assert len(dag.tasks) == 4
        merge = dag.tasks[3]
        assert len(merge.depends_on) == 2

    def test_dag_name(self, event_log, workspace, registry) -> None:
        wf = _make_workflow(name="My Pipeline")
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=_factory,
        )
        assert dag.name == "My Pipeline"

    def test_provider_factory_called(self, event_log, workspace, registry) -> None:
        factory = MagicMock(return_value=_StubProvider())
        wf = _make_workflow(
            nodes=[
                WorkflowNode(
                    id="a", role="agent", display_name="Agent",
                    config=WorkflowNodeConfig(model="gpt-4o"),
                ),
            ],
        )
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=factory,
        )
        factory.assert_called_once_with("gpt-4o")
