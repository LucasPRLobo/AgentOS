"""Discussion threads — structured conversations at decision points.

Every decision in the workspace happens through a discussion: the
coordinator opens a thread, the human participates, and when they
agree, the decision is recorded and work proceeds.

Discussion types:
- kickoff: Project start — goals, priorities, constraints
- task_spec: Before execution — approach, scope, assignment
- check_in: Mid-execution — progress, direction, issues
- review: After completion — evaluate, accept, refine
- replan: Plan needs changing — discuss new direction
- escalation: Agent stuck — discuss resolution
"""

from __future__ import annotations

import logging
import threading
from enum import StrEnum

from pydantic import BaseModel, Field

from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import (
    BoardPost,
    BoardSection,
    DirectMessage,
    MessagePriority,
    SpeechAct,
    _uuid,
    _utc_now_iso,
)
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType

logger = logging.getLogger(__name__)


class DiscussionType(StrEnum):
    KICKOFF = "kickoff"
    TASK_SPEC = "task_spec"
    CHECK_IN = "check_in"
    REVIEW = "review"
    REPLAN = "replan"
    ESCALATION = "escalation"


class DiscussionStatus(StrEnum):
    OPEN = "open"           # Awaiting human response
    ACTIVE = "active"       # Back-and-forth in progress
    RESOLVED = "resolved"   # Agreement reached
    DEFERRED = "deferred"   # Parked for later


class DiscussionThread(BaseModel):
    """A structured conversation at a decision point."""

    thread_id: str = Field(default_factory=_uuid)
    discussion_type: DiscussionType
    status: DiscussionStatus = DiscussionStatus.OPEN
    title: str
    context: str = ""
    participants: list[str] = Field(default_factory=lambda: ["coordinator", "human"])
    messages: list[dict] = Field(default_factory=list)
    decision: str | None = None
    decision_rationale: str | None = None
    related_task_id: str | None = None
    opening_message: str = ""
    options: list[str] | None = None
    created_at: str = Field(default_factory=_utc_now_iso)
    resolved_at: str | None = None


class DiscussionManager:
    """Manages discussion threads for a workspace.

    Discussions are the primary collaboration mechanism between the
    coordinator and the human. Every decision goes through a discussion.
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        bus: MessageBus,
        board_manager=None,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._bus = bus
        self._board = board_manager
        self._threads: dict[str, DiscussionThread] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    def open(
        self,
        discussion_type: DiscussionType,
        title: str,
        opening_message: str,
        context: str = "",
        participants: list[str] | None = None,
        options: list[str] | None = None,
        related_task_id: str | None = None,
    ) -> str:
        """Open a new discussion thread. Returns thread_id.

        Posts the opening message to the board and sends a direct
        message to the human participant.
        """
        thread = DiscussionThread(
            discussion_type=discussion_type,
            title=title,
            context=context,
            participants=participants or ["coordinator", "human"],
            opening_message=opening_message,
            options=options,
            related_task_id=related_task_id,
        )

        # Add opening message to the thread
        opening = {
            "sender_id": "coordinator",
            "sender_type": "agent",
            "content": opening_message,
            "speech_act": "request",
            "timestamp": _utc_now_iso(),
        }
        thread.messages.append(opening)

        with self._lock:
            self._threads[thread.thread_id] = thread

        # Post to board
        if self._board is not None:
            section = BoardSection.QUESTION if discussion_type in (
                DiscussionType.KICKOFF, DiscussionType.TASK_SPEC, DiscussionType.REPLAN,
            ) else BoardSection.POST

            board_content = f"[{discussion_type}] {title}\n\n{opening_message}"
            if options:
                board_content += "\n\nOptions:\n" + "\n".join(
                    f"  {chr(97 + i)}) {opt}" for i, opt in enumerate(options)
                )

            self._board.post(BoardPost(
                section=section,
                author_type="agent",
                author_id="coordinator",
                content=board_content,
                speech_act=SpeechAct.REQUEST,
            ))

        # Send direct message to human
        self._bus.send(DirectMessage(
            sender_type="agent",
            sender_id="coordinator",
            recipient_type="human",
            recipient_id="human",
            content=opening_message,
            speech_act=SpeechAct.REQUEST,
            priority=MessagePriority.HIGH,
            workflow_id=self._workflow_id,
        ))

        self._emit(EventType.DISCUSSION_OPENED, {
            "thread_id": thread.thread_id,
            "discussion_type": discussion_type,
            "title": title,
            "related_task_id": related_task_id,
        })

        return thread.thread_id

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        thread_id: str,
        sender_id: str,
        content: str,
        sender_type: str = "human",
        speech_act: str = "inform",
    ) -> None:
        """Add a message to a discussion thread."""
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise ValueError(f"Unknown discussion: {thread_id}")
            if thread.status in (DiscussionStatus.RESOLVED, DiscussionStatus.DEFERRED):
                raise ValueError(f"Discussion {thread_id} is already {thread.status}")

            thread.messages.append({
                "sender_id": sender_id,
                "sender_type": sender_type,
                "content": content,
                "speech_act": speech_act,
                "timestamp": _utc_now_iso(),
            })
            # Move to ACTIVE once human responds
            if sender_type == "human" and thread.status == DiscussionStatus.OPEN:
                thread.status = DiscussionStatus.ACTIVE

        self._emit(EventType.DISCUSSION_MESSAGE, {
            "thread_id": thread_id,
            "sender_id": sender_id,
            "sender_type": sender_type,
            "content_preview": content[:120],
        })

    # ------------------------------------------------------------------
    # Resolve
    # ------------------------------------------------------------------

    def resolve(
        self,
        thread_id: str,
        decision: str,
        rationale: str = "",
    ) -> None:
        """Resolve a discussion with a decision."""
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise ValueError(f"Unknown discussion: {thread_id}")
            thread.status = DiscussionStatus.RESOLVED
            thread.decision = decision
            thread.decision_rationale = rationale
            thread.resolved_at = _utc_now_iso()

        # Post decision to board
        if self._board is not None:
            self._board.post(BoardPost(
                section=BoardSection.DECISION,
                author_type="system",
                author_id="system",
                content=f"Decision: {decision}" + (f"\nRationale: {rationale}" if rationale else ""),
                speech_act=SpeechAct.CONFIRM,
            ))

        self._emit(EventType.DISCUSSION_RESOLVED, {
            "thread_id": thread_id,
            "decision": decision,
            "rationale": rationale[:200],
        })

    # ------------------------------------------------------------------
    # Defer
    # ------------------------------------------------------------------

    def defer(self, thread_id: str, reason: str = "") -> None:
        """Defer a discussion for later."""
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise ValueError(f"Unknown discussion: {thread_id}")
            thread.status = DiscussionStatus.DEFERRED

        self._emit(EventType.DISCUSSION_DEFERRED, {
            "thread_id": thread_id,
            "reason": reason[:200],
        })

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_open(self) -> list[DiscussionThread]:
        """Get all open/active discussions needing attention."""
        with self._lock:
            return [
                t for t in self._threads.values()
                if t.status in (DiscussionStatus.OPEN, DiscussionStatus.ACTIVE)
            ]

    def get_for_task(self, task_id: str) -> list[DiscussionThread]:
        """Get discussions related to a specific task."""
        with self._lock:
            return [
                t for t in self._threads.values()
                if t.related_task_id == task_id
            ]

    def get_thread(self, thread_id: str) -> DiscussionThread:
        """Get a specific discussion thread."""
        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None:
                raise ValueError(f"Unknown discussion: {thread_id}")
            return thread

    def has_open_discussions(self) -> bool:
        """Quick check: any discussions needing human input?"""
        with self._lock:
            return any(
                t.status in (DiscussionStatus.OPEN, DiscussionStatus.ACTIVE)
                for t in self._threads.values()
            )

    def get_all(self) -> list[DiscussionThread]:
        """Get all discussions (for audit/display)."""
        with self._lock:
            return list(self._threads.values())

    def get_resolved_decisions(self) -> list[dict]:
        """Get all decisions from resolved discussions."""
        with self._lock:
            return [
                {
                    "thread_id": t.thread_id,
                    "type": t.discussion_type,
                    "title": t.title,
                    "decision": t.decision,
                    "rationale": t.decision_rationale,
                    "resolved_at": t.resolved_at,
                }
                for t in self._threads.values()
                if t.status == DiscussionStatus.RESOLVED and t.decision
            ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, event_type: EventType, payload: dict) -> None:
        self._event_log.append(Event(
            event_type=event_type,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload=payload,
        ))
