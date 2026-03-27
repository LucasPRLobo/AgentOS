"""MessageBus — direct messaging between workspace participants.

Routes point-to-point messages between agents and humans with threading,
priority, delivery tracking, and full event-log auditability.

Design based on Claude Code Teams mailbox pattern + FIPA ACL threading.
See docs/COMMS_RESEARCH_AND_PLAN.md §6 for details.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import UTC, datetime

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


class MessageBus:
    """Central message routing for workspace communication.

    Handles direct messages between any participants (agent↔agent,
    agent↔human, human↔agent).  All messages are logged as events.

    Thread-safe — multiple agents can send/receive concurrently.
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

        # message_id → DirectMessage
        self._messages: dict[str, DirectMessage] = {}
        # recipient_id → [message_id, ...]  (undelivered, in arrival order)
        self._inboxes: dict[str, list[str]] = defaultdict(list)
        # thread_id → [message_id, ...]  (in chronological order)
        self._threads: dict[str, list[str]] = defaultdict(list)

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(self, message: DirectMessage) -> str:
        """Send a direct message.  Returns *message_id*.

        Logs a ``DIRECT_MESSAGE_SENT`` event.
        """
        with self._lock:
            self._messages[message.message_id] = message
            self._inboxes[message.recipient_id].append(message.message_id)

            # Maintain thread index
            if message.thread_id:
                self._threads[message.thread_id].append(message.message_id)

        self._event_log.append(
            Event(
                event_type=EventType.DIRECT_MESSAGE_SENT,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "message_id": message.message_id,
                    "thread_id": message.thread_id,
                    "sender_type": message.sender_type,
                    "sender_id": message.sender_id,
                    "recipient_type": message.recipient_type,
                    "recipient_id": message.recipient_id,
                    "speech_act": message.speech_act,
                    "priority": message.priority,
                    "content_preview": message.content[:120],
                },
            )
        )
        return message.message_id

    def reply(
        self,
        reply_to_id: str,
        sender_type: str,
        sender_id: str,
        content: str,
        speech_act: SpeechAct = SpeechAct.INFORM,
        priority: MessagePriority = MessagePriority.NORMAL,
        structured_data: dict | None = None,
    ) -> str:
        """Reply to an existing message.

        Automatically sets ``thread_id`` and ``reply_to``.  If the original
        message has no thread, a new thread is created.
        """
        with self._lock:
            original = self._messages.get(reply_to_id)
            if original is None:
                raise ValueError(f"Unknown message: {reply_to_id}")

            # Determine thread — use existing or create new
            thread_id = original.thread_id
            if thread_id is None:
                thread_id = _uuid()
                # Back-fill the original message into the new thread
                original.thread_id = thread_id
                self._threads[thread_id].append(original.message_id)

                self._event_log.append(
                    Event(
                        event_type=EventType.THREAD_CREATED,
                        workflow_id=self._workflow_id,
                        seq=self._seq.next(),
                        payload={
                            "thread_id": thread_id,
                            "initial_message_id": original.message_id,
                        },
                    )
                )

        reply_msg = DirectMessage(
            thread_id=thread_id,
            reply_to=reply_to_id,
            sender_type=sender_type,
            sender_id=sender_id,
            recipient_type=original.sender_type if original.sender_type != "system" else "agent",
            recipient_id=original.sender_id,
            content=content,
            speech_act=speech_act,
            priority=priority,
            structured_data=structured_data,
            workflow_id=self._workflow_id,
        )
        return self.send(reply_msg)

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def receive(
        self,
        recipient_id: str,
        priority_min: MessagePriority = MessagePriority.LOW,
        mark_delivered: bool = True,
    ) -> list[DirectMessage]:
        """Get pending (undelivered) messages for *recipient_id*.

        Only returns messages whose priority is >= *priority_min*.
        If *mark_delivered* is ``True``, marks returned messages as delivered
        and logs ``DIRECT_MESSAGE_DELIVERED`` events.
        """
        priority_order = list(MessagePriority)
        min_idx = priority_order.index(priority_min)

        now = _utc_now_iso()
        delivered: list[DirectMessage] = []

        with self._lock:
            remaining: list[str] = []
            for mid in self._inboxes.get(recipient_id, []):
                msg = self._messages.get(mid)
                if msg is None or msg.delivered:
                    continue
                if priority_order.index(msg.priority) < min_idx:
                    remaining.append(mid)
                    continue
                if mark_delivered:
                    msg.delivered = True
                    msg.delivered_at = now
                delivered.append(msg)

            if mark_delivered:
                # Keep only undelivered messages in the inbox
                self._inboxes[recipient_id] = [
                    mid for mid in self._inboxes.get(recipient_id, [])
                    if not self._messages[mid].delivered
                ] if recipient_id in self._inboxes else []

        # Log delivery events outside the lock
        for msg in delivered:
            self._event_log.append(
                Event(
                    event_type=EventType.DIRECT_MESSAGE_DELIVERED,
                    workflow_id=self._workflow_id,
                    seq=self._seq.next(),
                    payload={
                        "message_id": msg.message_id,
                        "recipient_id": recipient_id,
                        "sender_id": msg.sender_id,
                        "speech_act": msg.speech_act,
                    },
                )
            )

        return delivered

    def get_pending_count(self, recipient_id: str) -> int:
        """Cheap count of undelivered messages (no content loaded)."""
        with self._lock:
            return sum(
                1
                for mid in self._inboxes.get(recipient_id, [])
                if mid in self._messages and not self._messages[mid].delivered
            )

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------

    def get_thread(self, thread_id: str) -> list[DirectMessage]:
        """All messages in a thread, ordered chronologically."""
        with self._lock:
            msg_ids = self._threads.get(thread_id, [])
            return [
                self._messages[mid]
                for mid in msg_ids
                if mid in self._messages
            ]

    # ------------------------------------------------------------------
    # Acknowledgment
    # ------------------------------------------------------------------

    def acknowledge(self, message_id: str) -> None:
        """Mark a message as acknowledged by its recipient."""
        with self._lock:
            msg = self._messages.get(message_id)
            if msg is None:
                raise ValueError(f"Unknown message: {message_id}")
            msg.acknowledged = True
            msg.acknowledged_at = _utc_now_iso()

        self._event_log.append(
            Event(
                event_type=EventType.DIRECT_MESSAGE_ACKNOWLEDGED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "message_id": message_id,
                    "recipient_id": msg.recipient_id,
                },
            )
        )

    # ------------------------------------------------------------------
    # Board promotion
    # ------------------------------------------------------------------

    def promote_to_board(
        self,
        message_id: str,
        board_manager: object,
        section: str = "post",
    ) -> str:
        """Promote a direct message to a board post.

        *board_manager* must have a ``post(BoardPost) -> str`` method.
        Returns the new post_id.
        """
        with self._lock:
            msg = self._messages.get(message_id)
            if msg is None:
                raise ValueError(f"Unknown message: {message_id}")

        post = BoardPost(
            section=BoardSection(section),
            author_type=msg.sender_type,
            author_id=msg.sender_id,
            content=msg.content,
            speech_act=msg.speech_act,
            structured_data=msg.structured_data,
            source_message_id=msg.message_id,
            source_thread_id=msg.thread_id,
        )

        post_id = board_manager.post(post)  # type: ignore[union-attr]

        self._event_log.append(
            Event(
                event_type=EventType.MESSAGE_PROMOTED_TO_BOARD,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "message_id": message_id,
                    "post_id": post_id,
                    "section": section,
                },
            )
        )
        return post_id

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def get_all_messages(self) -> list[DirectMessage]:
        """Return all messages (for audit / compliance export)."""
        with self._lock:
            return list(self._messages.values())

    def get_messages_for_participant(
        self, participant_id: str,
    ) -> list[DirectMessage]:
        """All messages sent or received by a participant."""
        with self._lock:
            return [
                m for m in self._messages.values()
                if m.sender_id == participant_id
                or m.recipient_id == participant_id
            ]
