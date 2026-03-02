"""Tool call record schema."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ToolCallRecord(BaseModel):
    """Immutable record of a single tool invocation."""

    tool_name: str
    tool_version: str = "0.0.0"
    input_hash: str = Field(description="SHA-256 of serialized input")
    output_hash: str = Field(default="", description="SHA-256 of serialized output")
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = None
    success: bool = False
