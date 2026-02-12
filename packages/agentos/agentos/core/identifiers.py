"""Core identifier types for AgentOS."""

from __future__ import annotations

import uuid
from typing import NewType

RunId = NewType("RunId", str)
TaskId = NewType("TaskId", str)
ToolCallId = NewType("ToolCallId", str)
ArtifactId = NewType("ArtifactId", str)


def generate_id() -> str:
    """Generate a unique identifier (UUID4)."""
    return str(uuid.uuid4())


def generate_run_id() -> RunId:
    """Generate a new RunId."""
    return RunId(generate_id())


def generate_task_id() -> TaskId:
    """Generate a new TaskId."""
    return TaskId(generate_id())


def generate_tool_call_id() -> ToolCallId:
    """Generate a new ToolCallId."""
    return ToolCallId(generate_id())


def generate_artifact_id() -> ArtifactId:
    """Generate a new ArtifactId."""
    return ArtifactId(generate_id())
