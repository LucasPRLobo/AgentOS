"""Task state machine and task node definition."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from agentos.core.identifiers import TaskId, generate_task_id


class TaskState(StrEnum):
    """Task lifecycle states."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TaskNode:
    """A single unit of work in a workflow.

    Wraps a callable with lifecycle state tracking and dependency edges.
    """

    def __init__(
        self,
        name: str,
        callable: Callable[..., Any],
        *,
        task_id: TaskId | None = None,
        depends_on: list[TaskNode] | None = None,
    ) -> None:
        self.id: TaskId = task_id or generate_task_id()
        self.name = name
        self.callable = callable
        self.state: TaskState = TaskState.PENDING
        self.result: Any = None
        self.error: Exception | None = None
        self.depends_on: list[TaskNode] = depends_on or []

    @property
    def is_ready(self) -> bool:
        """True if all dependencies have succeeded and this task is pending."""
        if self.state != TaskState.PENDING:
            return False
        return all(d.state == TaskState.SUCCEEDED for d in self.depends_on)

    def __repr__(self) -> str:
        return f"TaskNode(name={self.name!r}, state={self.state.value})"
