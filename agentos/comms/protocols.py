"""Communication protocol schemas — structured exchanges between participants.

Based on FIPA interaction protocols, adapted for LLM agent workspaces.
Protocols formalize common patterns (consultation, review, escalation)
so the system can track, enforce, and auto-resolve them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProtocolType(StrEnum):
    CONSULTATION = "consultation"
    REVIEW = "review"
    ESCALATION = "escalation"


class ProtocolState(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    IN_REVIEW = "in_review"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Consultation: "I need expert input"
# ---------------------------------------------------------------------------

class ConsultationProtocol(BaseModel):
    """Tracks a question→answer exchange between two participants."""

    protocol_id: str = Field(default_factory=_uuid)
    protocol_type: ProtocolType = Field(default=ProtocolType.CONSULTATION)
    requester_id: str
    expert_id: str
    question: str
    response: str | None = None
    state: ProtocolState = Field(default=ProtocolState.OPEN)
    timeout_minutes: int = Field(default=30)
    created_at: str = Field(default_factory=_utc_now_iso)
    resolved_at: str | None = None


# ---------------------------------------------------------------------------
# Review: "Check my work"
# ---------------------------------------------------------------------------

class ReviewRound(BaseModel):
    """A single round in a review cycle."""

    round_number: int
    verdict: str = ""  # approve, revise, reject
    issues: list[dict[str, Any]] = Field(default_factory=list)
    feedback: str | None = None
    timestamp: str = Field(default_factory=_utc_now_iso)


class ReviewProtocol(BaseModel):
    """Tracks a submit→review→revise cycle."""

    protocol_id: str = Field(default_factory=_uuid)
    protocol_type: ProtocolType = Field(default=ProtocolType.REVIEW)
    author_id: str
    reviewer_id: str
    artifact_path: str
    criteria: list[str] = Field(default_factory=list)
    state: ProtocolState = Field(default=ProtocolState.OPEN)
    rounds: list[ReviewRound] = Field(default_factory=list)
    max_rounds: int = Field(default=3)
    created_at: str = Field(default_factory=_utc_now_iso)
    resolved_at: str | None = None


# ---------------------------------------------------------------------------
# Escalation: "I can't resolve this"
# ---------------------------------------------------------------------------

class EscalationProtocol(BaseModel):
    """Tracks an escalation from an agent to the human/coordinator."""

    protocol_id: str = Field(default_factory=_uuid)
    protocol_type: ProtocolType = Field(default=ProtocolType.ESCALATION)
    escalator_id: str
    target_id: str = Field(default="human")
    issue: str
    context: dict[str, Any] | None = None
    resolution: str | None = None
    state: ProtocolState = Field(default=ProtocolState.OPEN)
    priority: str = Field(default="high")
    timeout_minutes: int = Field(default=60)
    created_at: str = Field(default_factory=_utc_now_iso)
    resolved_at: str | None = None
