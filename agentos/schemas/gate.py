"""Gate schemas — approval gates, input gates, and resolution tracking."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GateType(StrEnum):
    APPROVAL = "approval"
    INPUT = "input"


class GateResolution(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class GateState(BaseModel):
    """Current state of a gate, derived from events."""

    gate_id: str
    task_id: str
    gate_type: GateType
    prompt: str = ""
    pending: bool = True
    resolution: GateResolution | None = None
    feedback: str | None = None
    reviewer: str | None = None
