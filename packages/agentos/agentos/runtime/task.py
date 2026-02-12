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

    Wraps a callable with lifecycle state tracking.
    """

    def __init__(
        self,
        name: str,
        callable: Callable[..., Any],
        *,
        task_id: TaskId | None = None,
    ) -> None:
        self.id: TaskId = task_id or generate_task_id()
        self.name = name
        self.callable = callable
        self.state: TaskState = TaskState.PENDING
        self.result: Any = None
        self.error: Exception | None = None

    def __repr__(self) -> str:
        return f"TaskNode(name={self.name!r}, state={self.state.value})"
