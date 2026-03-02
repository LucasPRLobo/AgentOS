"""Core error hierarchy for AgentOS."""

from __future__ import annotations


class AgentOSError(Exception):
    """Base exception for all AgentOS errors."""


class BudgetExceededError(AgentOSError):
    """Raised when a budget limit (tokens, tool calls, time, etc.) is exceeded."""


class ToolValidationError(AgentOSError):
    """Raised when tool input or output fails schema validation."""


class TaskExecutionError(AgentOSError):
    """Raised when a task fails during execution."""


class PermissionDeniedError(AgentOSError):
    """Raised when an operation is denied by the permissions engine."""


class REPLExecutionError(AgentOSError):
    """Raised when code execution in the REPL environment fails."""
