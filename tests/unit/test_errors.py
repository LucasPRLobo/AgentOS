"""Tests for core error hierarchy."""

import pytest

from agentos.core.errors import (
    AgentOSError,
    BudgetExceededError,
    PermissionDeniedError,
    TaskExecutionError,
    ToolValidationError,
)


class TestErrorHierarchy:
    def test_base_error_is_exception(self) -> None:
        assert issubclass(AgentOSError, Exception)

    def test_budget_exceeded_is_agentos_error(self) -> None:
        assert issubclass(BudgetExceededError, AgentOSError)

    def test_tool_validation_is_agentos_error(self) -> None:
        assert issubclass(ToolValidationError, AgentOSError)

    def test_task_execution_is_agentos_error(self) -> None:
        assert issubclass(TaskExecutionError, AgentOSError)

    def test_permission_denied_is_agentos_error(self) -> None:
        assert issubclass(PermissionDeniedError, AgentOSError)


class TestErrorRaising:
    def test_raise_budget_exceeded(self) -> None:
        with pytest.raises(BudgetExceededError, match="token limit"):
            raise BudgetExceededError("token limit")

    def test_raise_tool_validation(self) -> None:
        with pytest.raises(ToolValidationError, match="invalid input"):
            raise ToolValidationError("invalid input")

    def test_raise_task_execution(self) -> None:
        with pytest.raises(TaskExecutionError, match="task failed"):
            raise TaskExecutionError("task failed")

    def test_raise_permission_denied(self) -> None:
        with pytest.raises(PermissionDeniedError, match="not allowed"):
            raise PermissionDeniedError("not allowed")

    def test_catch_all_via_base(self) -> None:
        with pytest.raises(AgentOSError):
            raise BudgetExceededError("caught by base")
