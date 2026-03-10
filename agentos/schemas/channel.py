"""Message channel schemas for inter-agent communication."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ChannelMode(StrEnum):
    BROADCAST = "broadcast"  # All subscribers receive every message
    QUEUE = "queue"  # Round-robin delivery to one subscriber


class ChannelConfig(BaseModel):
    """Configuration for a named message channel within a workflow."""

    name: str = Field(description="Unique channel name within the workflow")
    mode: ChannelMode = Field(default=ChannelMode.BROADCAST)
    max_buffer: int = Field(default=100, ge=1, description="Max undelivered messages")


class ChannelMessage(BaseModel):
    """A message sent through a channel."""

    channel: str = Field(description="Channel name")
    sender_task_id: str
    sender_agent_id: str
    content: dict = Field(default_factory=dict, description="Structured message payload")
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
