"""Cross-run memory schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    FINDING = "finding"
    DECISION = "decision"
    GATE_FEEDBACK = "gate_feedback"
    ERROR_PATTERN = "error_pattern"
    TOOL_PREFERENCE = "tool_preference"


class MemoryEntry(BaseModel):
    """A single memory extracted from a completed workflow."""

    memory_id: str
    workflow_id: str
    task_id: str
    memory_type: MemoryType
    content: str = Field(description="The memory content")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    ttl_hours: int | None = Field(default=None, description="Time-to-live in hours, None=forever")
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    last_accessed: datetime | None = None
    access_count: int = Field(default=0, ge=0)


class MemoryQuery(BaseModel):
    """Query parameters for memory retrieval."""

    tags: list[str] = Field(default_factory=list)
    memory_type: MemoryType | None = None
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1)


class MemoryConfig(BaseModel):
    """Configuration for cross-run memory."""

    enabled: bool = Field(default=False)
    decay_rate: float = Field(default=0.05, ge=0.0, le=1.0, description="Confidence decay per day")
    min_confidence: float = Field(default=0.1, ge=0.0, le=1.0, description="Below this, memory is pruned")
    max_entries: int = Field(default=10000, ge=1)
    default_ttl_hours: int | None = Field(default=None, description="Default TTL for new memories")
