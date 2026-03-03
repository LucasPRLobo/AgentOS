"""Workspace schemas — scoped directories and file tracking."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FileOperation(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


class WorkspaceConfig(BaseModel):
    """Configuration for a scoped workspace."""

    root: str = Field(description="Root directory path")
    allowed_patterns: list[str] = Field(default_factory=lambda: ["**"])
    read_only: bool = False


class FileManifestEntry(BaseModel):
    """Record of a file operation within a workspace."""

    path: str
    operation: FileOperation
    agent_id: str
    task_id: str
    size_bytes: int
    timestamp: datetime = Field(default_factory=datetime.now)
