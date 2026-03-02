"""Artifact metadata schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.core.identifiers import ArtifactId, TaskId


class ArtifactMeta(BaseModel):
    """Metadata for a produced artifact."""

    id: ArtifactId
    path: str = Field(description="Relative path or URI of the artifact")
    sha256: str = Field(description="SHA-256 hash of the artifact content")
    produced_by_task: TaskId
    mime_type: str = "application/octet-stream"
