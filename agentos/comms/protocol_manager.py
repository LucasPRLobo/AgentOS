"""ProtocolManager — tracks structured communication exchanges.

Manages the lifecycle of consultation, review, and escalation protocols.
Detects timeouts and auto-escalates unresolved exchanges.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from agentos.comms.protocols import (
    ConsultationProtocol,
    EscalationProtocol,
    ProtocolState,
    ProtocolType,
    ReviewProtocol,
    ReviewRound,
)
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType

logger = logging.getLogger(__name__)

# Type alias for any protocol
Protocol = ConsultationProtocol | ReviewProtocol | EscalationProtocol


class ProtocolManager:
    """Tracks structured communication exchanges.

    Monitors open protocols, detects timeouts, and logs protocol
    state changes as events.
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
        self._protocols: dict[str, Protocol] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Start protocols
    # ------------------------------------------------------------------

    def start_consultation(
        self,
        requester_id: str,
        expert_id: str,
        question: str,
        timeout_minutes: int = 30,
    ) -> str:
        """Start a consultation protocol.  Returns protocol_id."""
        proto = ConsultationProtocol(
            requester_id=requester_id,
            expert_id=expert_id,
            question=question,
            timeout_minutes=timeout_minutes,
        )
        with self._lock:
            self._protocols[proto.protocol_id] = proto

        self._emit(EventType.PROTOCOL_STARTED, {
            "protocol_id": proto.protocol_id,
            "protocol_type": "consultation",
            "requester_id": requester_id,
            "expert_id": expert_id,
            "question_preview": question[:120],
        })
        return proto.protocol_id

    def start_review(
        self,
        author_id: str,
        reviewer_id: str,
        artifact_path: str,
        criteria: list[str] | None = None,
        max_rounds: int = 3,
    ) -> str:
        """Start a review protocol.  Returns protocol_id."""
        proto = ReviewProtocol(
            author_id=author_id,
            reviewer_id=reviewer_id,
            artifact_path=artifact_path,
            criteria=criteria or [],
            max_rounds=max_rounds,
            state=ProtocolState.IN_REVIEW,
        )
        with self._lock:
            self._protocols[proto.protocol_id] = proto

        self._emit(EventType.PROTOCOL_STARTED, {
            "protocol_id": proto.protocol_id,
            "protocol_type": "review",
            "author_id": author_id,
            "reviewer_id": reviewer_id,
            "artifact_path": artifact_path,
        })
        return proto.protocol_id

    def start_escalation(
        self,
        escalator_id: str,
        issue: str,
        target_id: str = "human",
        context: dict | None = None,
        timeout_minutes: int = 60,
    ) -> str:
        """Start an escalation protocol.  Returns protocol_id."""
        proto = EscalationProtocol(
            escalator_id=escalator_id,
            target_id=target_id,
            issue=issue,
            context=context,
            timeout_minutes=timeout_minutes,
        )
        with self._lock:
            self._protocols[proto.protocol_id] = proto

        self._emit(EventType.PROTOCOL_STARTED, {
            "protocol_id": proto.protocol_id,
            "protocol_type": "escalation",
            "escalator_id": escalator_id,
            "target_id": target_id,
            "issue_preview": issue[:120],
        })
        return proto.protocol_id

    # ------------------------------------------------------------------
    # Resolve protocols
    # ------------------------------------------------------------------

    def resolve_consultation(self, protocol_id: str, response: str) -> None:
        """Record the expert's response to a consultation."""
        with self._lock:
            proto = self._get(protocol_id, ConsultationProtocol)
            proto.response = response
            proto.state = ProtocolState.ANSWERED
            proto.resolved_at = datetime.now(UTC).isoformat()

        self._emit(EventType.PROTOCOL_RESOLVED, {
            "protocol_id": protocol_id,
            "protocol_type": "consultation",
            "state": "answered",
        })

    def submit_review_round(
        self,
        protocol_id: str,
        verdict: str,
        issues: list[dict] | None = None,
        feedback: str | None = None,
    ) -> None:
        """Record a review round verdict."""
        with self._lock:
            proto = self._get(protocol_id, ReviewProtocol)
            round_num = len(proto.rounds) + 1
            proto.rounds.append(ReviewRound(
                round_number=round_num,
                verdict=verdict,
                issues=issues or [],
                feedback=feedback,
            ))

            if verdict == "approve":
                proto.state = ProtocolState.APPROVED
                proto.resolved_at = datetime.now(UTC).isoformat()
            elif verdict == "reject":
                proto.state = ProtocolState.REJECTED
                proto.resolved_at = datetime.now(UTC).isoformat()
            elif verdict == "revise":
                if round_num >= proto.max_rounds:
                    proto.state = ProtocolState.REJECTED
                    proto.resolved_at = datetime.now(UTC).isoformat()
                else:
                    proto.state = ProtocolState.REVISION_REQUESTED

        self._emit(EventType.PROTOCOL_RESOLVED, {
            "protocol_id": protocol_id,
            "protocol_type": "review",
            "round": round_num,
            "verdict": verdict,
            "state": proto.state,
        })

    def resolve_escalation(self, protocol_id: str, resolution: str) -> None:
        """Record the resolution of an escalation."""
        with self._lock:
            proto = self._get(protocol_id, EscalationProtocol)
            proto.resolution = resolution
            proto.state = ProtocolState.RESOLVED
            proto.resolved_at = datetime.now(UTC).isoformat()

        self._emit(EventType.PROTOCOL_RESOLVED, {
            "protocol_id": protocol_id,
            "protocol_type": "escalation",
            "state": "resolved",
        })

    # ------------------------------------------------------------------
    # Timeout detection
    # ------------------------------------------------------------------

    def check_timeouts(self) -> list[str]:
        """Check for timed-out protocols.  Returns list of protocol_ids."""
        now = datetime.now(UTC)
        timed_out: list[str] = []

        with self._lock:
            for pid, proto in self._protocols.items():
                if self._is_terminal(proto):
                    continue

                timeout_min = getattr(proto, "timeout_minutes", 0)
                if timeout_min <= 0:
                    continue

                created = datetime.fromisoformat(proto.created_at)
                if now - created > timedelta(minutes=timeout_min):
                    proto.state = ProtocolState.TIMEOUT
                    proto.resolved_at = now.isoformat()
                    timed_out.append(pid)

        for pid in timed_out:
            self._emit(EventType.PROTOCOL_TIMEOUT, {
                "protocol_id": pid,
                "protocol_type": str(self._protocols[pid].protocol_type),
            })

        return timed_out

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_protocol(self, protocol_id: str) -> Protocol:
        """Get a protocol by ID."""
        with self._lock:
            if protocol_id not in self._protocols:
                raise ValueError(f"Unknown protocol: {protocol_id}")
            return self._protocols[protocol_id]

    def get_open_protocols(self, participant_id: str | None = None) -> list[Protocol]:
        """Get all open (non-terminal) protocols, optionally filtered."""
        with self._lock:
            results = []
            for proto in self._protocols.values():
                if self._is_terminal(proto):
                    continue
                if participant_id is not None:
                    if not self._involves(proto, participant_id):
                        continue
                results.append(proto)
            return results

    def get_all_protocols(self) -> list[Protocol]:
        """All protocols (for audit)."""
        with self._lock:
            return list(self._protocols.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, protocol_id: str, expected_type: type) -> Protocol:
        """Get and type-check a protocol (caller holds lock)."""
        proto = self._protocols.get(protocol_id)
        if proto is None:
            raise ValueError(f"Unknown protocol: {protocol_id}")
        if not isinstance(proto, expected_type):
            raise TypeError(
                f"Protocol {protocol_id} is {type(proto).__name__}, "
                f"expected {expected_type.__name__}"
            )
        return proto

    @staticmethod
    def _is_terminal(proto: Protocol) -> bool:
        return proto.state in (
            ProtocolState.ANSWERED,
            ProtocolState.APPROVED,
            ProtocolState.REJECTED,
            ProtocolState.RESOLVED,
            ProtocolState.TIMEOUT,
        )

    @staticmethod
    def _involves(proto: Protocol, participant_id: str) -> bool:
        if isinstance(proto, ConsultationProtocol):
            return participant_id in (proto.requester_id, proto.expert_id)
        if isinstance(proto, ReviewProtocol):
            return participant_id in (proto.author_id, proto.reviewer_id)
        if isinstance(proto, EscalationProtocol):
            return participant_id in (proto.escalator_id, proto.target_id)
        return False

    def _emit(self, event_type: EventType, payload: dict) -> None:
        self._event_log.append(
            Event(
                event_type=event_type,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload=payload,
            )
        )
