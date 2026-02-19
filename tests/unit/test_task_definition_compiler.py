"""Unit tests for TaskDefinition-aware prompt construction in workflow compiler."""

from __future__ import annotations

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.dag import DAGWorkflow
from agentos.runtime.domain_registry import DomainRegistry
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.workspace import Workspace, WorkspaceConfig
from agentos.schemas.workflow import (
    TaskDefinition,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeConfig,
)
from agentplatform.workflow_compiler import compile_workflow


class _CaptureProvider(BaseLMProvider):
    """Provider that captures the prompt sent to it."""

    def __init__(self) -> None:
        self.last_messages: list[LMMessage] = []

    @property
    def name(self) -> str:
        return "capture"

    def get_model_name(self) -> str:
        return "capture-model"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        self.last_messages = list(messages)
        return LMResponse(
            content='{"action": "finish", "result": "done"}',
            tokens_used=10, prompt_tokens=5, completion_tokens=5,
        )


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
    return _CaptureProvider()


class TestTaskDefinitionPrompt:
    def _compile_and_run(self, wf, event_log, workspace, registry):
        """Compile workflow and run the first task to capture the prompt."""
        provider = _CaptureProvider()
        dag = compile_workflow(
            wf,
            domain_registry=registry,
            event_log=event_log,
            workspace=workspace,
            provider_factory=lambda _: provider,
        )
        # Execute the first task to capture the prompt
        task = dag.tasks[0]
        task.callable()
        return provider.last_messages

    def test_structured_prompt_with_task(self, event_log, workspace, registry) -> None:
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Writer",
                    config=WorkflowNodeConfig(
                        model="stub",
                        task=TaskDefinition(
                            objective="Write a report",
                            deliverables=["report.md"],
                            acceptance_criteria=["Has 5+ sections", "Well-formatted"],
                            inputs={"topic": "AI Agents"},
                        ),
                    ),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        # The task description is the user message content
        user_msg = messages[-1].content
        assert "## Your Task" in user_msg
        assert "**Objective:** Write a report" in user_msg
        assert "**Deliverables:**" in user_msg
        assert "- report.md" in user_msg
        assert "**Acceptance Criteria (verify ALL before finishing):**" in user_msg
        assert "- Has 5+ sections" in user_msg
        assert "verify your output meets ALL criteria" in user_msg
        assert "**Inputs:**" in user_msg
        assert "- topic: AI Agents" in user_msg

    def test_no_task_backward_compat(self, event_log, workspace, registry) -> None:
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Writer",
                    config=WorkflowNodeConfig(model="stub"),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        user_msg = messages[-1].content
        assert "## Your Task" not in user_msg
        assert "**Objective:**" not in user_msg
        # Standard prompt elements still present
        assert "Writer" in user_msg

    def test_partial_task(self, event_log, workspace, registry) -> None:
        """Task with only objective set still works."""
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Agent",
                    config=WorkflowNodeConfig(
                        model="stub",
                        task=TaskDefinition(objective="Do something"),
                    ),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        user_msg = messages[-1].content
        assert "**Objective:** Do something" in user_msg
        assert "**Deliverables:**" not in user_msg  # empty list, not shown
        assert "**Acceptance Criteria" not in user_msg

    def test_deliverables_in_prompt(self, event_log, workspace, registry) -> None:
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Agent",
                    config=WorkflowNodeConfig(
                        model="stub",
                        task=TaskDefinition(
                            objective="Analyze",
                            deliverables=["analysis.md", "charts.png"],
                        ),
                    ),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        user_msg = messages[-1].content
        assert "- analysis.md" in user_msg
        assert "- charts.png" in user_msg

    def test_criteria_includes_self_check_instruction(self, event_log, workspace, registry) -> None:
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Agent",
                    config=WorkflowNodeConfig(
                        model="stub",
                        task=TaskDefinition(
                            objective="Write",
                            acceptance_criteria=["Includes summary"],
                        ),
                    ),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        user_msg = messages[-1].content
        assert "Before calling finish, verify your output meets ALL criteria" in user_msg

    def test_empty_task_definition(self, event_log, workspace, registry) -> None:
        """TaskDefinition with all defaults = no extra sections."""
        wf = WorkflowDefinition(
            name="Test",
            nodes=[
                WorkflowNode(
                    id="a", role="custom", display_name="Agent",
                    config=WorkflowNodeConfig(
                        model="stub",
                        task=TaskDefinition(),
                    ),
                ),
            ],
        )
        messages = self._compile_and_run(wf, event_log, workspace, registry)
        user_msg = messages[-1].content
        # With all empty defaults, no structured sections should appear
        assert "## Your Task" not in user_msg
