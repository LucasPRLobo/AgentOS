"""Communication schemas — messages, board posts, and board state.

Based on FIPA ACL speech acts for message typing and Claude Code Teams
mailbox pattern for direct messaging.  See docs/COMMS_RESEARCH_AND_PLAN.md
for design rationale.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SpeechAct(StrEnum):
    """Communication intent, based on FIPA ACL performatives.

    Each message carries a speech act that describes the *intent* of the
    sender, allowing the system (and recipients) to route, prioritise,
    and track messages intelligently.
    """

    INFORM = "inform"          # Sharing a fact — no response expected
    REQUEST = "request"        # Asking for action / information — response expected
    PROPOSE = "propose"        # Suggesting a direction — accept / reject expected
    ACCEPT = "accept"          # Accepting a prior proposal or request
    REJECT = "reject"          # Rejecting with rationale
    CONFIRM = "confirm"        # Confirming a previous inform
    ALERT = "alert"            # System-generated warning
    DIRECTIVE = "directive"    # Human authority instruction — must follow
    STATUS = "status"          # Progress update


class MessagePriority(StrEnum):
    """Delivery urgency for messages."""

    LOW = "low"            # Batch-deliverable, not time-sensitive
    NORMAL = "normal"      # Deliver at next boundary
    HIGH = "high"          # Deliver at next boundary, highlight in context
    CRITICAL = "critical"  # Deliver immediately — may interrupt agent


class BoardSection(StrEnum):
    """Named sections of the workspace board."""

    ANNOUNCEMENT = "announcement"
    STATUS = "status"
    POST = "post"
    DECISION = "decision"
    QUESTION = "question"
    ALERT = "alert"


# ---------------------------------------------------------------------------
# Direct Messaging
# ---------------------------------------------------------------------------

class DirectMessage(BaseModel):
    """A message between participants in the workspace.

    Supports threading via *thread_id* / *reply_to* (modelled after FIPA
    ``conversation-id`` / ``in-reply-to``).
    """

    message_id: str = Field(default_factory=_uuid)
    thread_id: str | None = Field(
        default=None,
        description="Conversation thread this message belongs to",
    )
    reply_to: str | None = Field(
        default=None,
        description="Message ID this is a reply to (FIPA in-reply-to)",
    )
    reply_by: str | None = Field(
        default=None,
        description="Deadline for a response (ISO datetime, FIPA reply-by)",
    )

    # Addressing --------------------------------------------------------
    sender_type: Literal["agent", "human", "system"] = "agent"
    sender_id: str = Field(description="Agent ID, human user ID, or 'system'")
    recipient_type: Literal["agent", "human"] = "agent"
    recipient_id: str = Field(description="Recipient agent or human ID")

    # Content -----------------------------------------------------------
    content: str = Field(description="Natural language message body")
    speech_act: SpeechAct = Field(default=SpeechAct.INFORM)
    structured_data: dict[str, Any] | None = Field(
        default=None,
        description="Optional structured payload (review criteria, handoff manifest, etc.)",
    )
    attachments: list[str] | None = Field(
        default=None,
        description="Workspace file paths attached to this message",
    )

    # Metadata ----------------------------------------------------------
    priority: MessagePriority = Field(default=MessagePriority.NORMAL)
    workflow_id: str = Field(description="Workflow this message belongs to")
    timestamp: str = Field(default_factory=_utc_now_iso)

    # Delivery tracking -------------------------------------------------
    delivered: bool = Field(default=False)
    delivered_at: str | None = Field(default=None)
    acknowledged: bool = Field(default=False)
    acknowledged_at: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

class BoardPost(BaseModel):
    """A single post on the workspace board."""

    post_id: str = Field(default_factory=_uuid)
    section: BoardSection = Field(default=BoardSection.POST)

    # Authorship --------------------------------------------------------
    author_type: Literal["agent", "human", "system"] = "agent"
    author_id: str = Field(description="Who created this post")

    # Content -----------------------------------------------------------
    content: str = Field(description="Natural language post content")
    speech_act: SpeechAct = Field(default=SpeechAct.INFORM)
    structured_data: dict[str, Any] | None = Field(default=None)

    # State -------------------------------------------------------------
    pinned: bool = Field(default=False)
    resolved: bool = Field(default=False)
    resolved_by: str | None = Field(default=None)

    # Timing ------------------------------------------------------------
    timestamp: str = Field(default_factory=_utc_now_iso)
    expires_at: str | None = Field(
        default=None,
        description="Auto-archive after this ISO datetime",
    )

    # Provenance (if promoted from a direct message) --------------------
    source_message_id: str | None = Field(default=None)
    source_thread_id: str | None = Field(default=None)


class AgentStatus(BaseModel):
    """Status of an agent as shown on the board roster."""

    agent_id: str
    agent_name: str = Field(default="")
    role: str = Field(default="")
    state: Literal[
        "running", "waiting", "pending",
        "succeeded", "failed", "idle",
    ] = "pending"
    current_task: str | None = Field(default=None)
    progress_summary: str | None = Field(
        default=None,
        description="Human-readable progress, e.g. '70% complete'",
    )
    last_active: str = Field(default_factory=_utc_now_iso)


class BoardState(BaseModel):
    """Complete snapshot of the workspace board at a point in time."""

    workflow_id: str
    version: int = Field(default=0, description="Increments on every mutation")
    announcements: list[BoardPost] = Field(default_factory=list)
    team_status: list[AgentStatus] = Field(default_factory=list)
    recent_posts: list[BoardPost] = Field(
        default_factory=list,
        description="Newest first, capped at max_recent_posts",
    )
    decisions: list[BoardPost] = Field(default_factory=list)
    open_questions: list[BoardPost] = Field(default_factory=list)
    alerts: list[BoardPost] = Field(default_factory=list)
    last_updated: str = Field(default_factory=_utc_now_iso)
