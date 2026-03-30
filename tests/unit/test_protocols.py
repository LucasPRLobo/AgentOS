"""Tests for agentos.comms.protocols and protocol_manager."""

import time

import pytest

from agentos.comms.protocol_manager import ProtocolManager
from agentos.comms.protocols import (
    ConsultationProtocol,
    EscalationProtocol,
    ProtocolState,
    ProtocolType,
    ReviewProtocol,
    ReviewRound,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestConsultationSchema:
    def test_defaults(self):
        c = ConsultationProtocol(
            requester_id="a", expert_id="b", question="which source?",
        )
        assert c.protocol_type == ProtocolType.CONSULTATION
        assert c.state == ProtocolState.OPEN
        assert c.response is None
        assert c.timeout_minutes == 30

    def test_roundtrip(self):
        c = ConsultationProtocol(
            requester_id="a", expert_id="b", question="q",
        )
        data = c.model_dump()
        c2 = ConsultationProtocol(**data)
        assert c2.protocol_id == c.protocol_id


class TestReviewSchema:
    def test_defaults(self):
        r = ReviewProtocol(
            author_id="writer", reviewer_id="reviewer",
            artifact_path="report.md",
        )
        assert r.protocol_type == ProtocolType.REVIEW
        assert r.max_rounds == 3
        assert r.rounds == []

    def test_with_criteria(self):
        r = ReviewProtocol(
            author_id="w", reviewer_id="r", artifact_path="x.md",
            criteria=["accuracy", "clarity"],
        )
        assert len(r.criteria) == 2


class TestEscalationSchema:
    def test_defaults(self):
        e = EscalationProtocol(
            escalator_id="agent-a", issue="stuck on conflicting data",
        )
        assert e.target_id == "human"
        assert e.priority == "high"
        assert e.timeout_minutes == 60


class TestReviewRound:
    def test_round(self):
        r = ReviewRound(round_number=1, verdict="revise",
                         issues=[{"severity": "high", "description": "wrong data"}])
        assert r.verdict == "revise"
        assert len(r.issues) == 1


# ---------------------------------------------------------------------------
# ProtocolManager tests
# ---------------------------------------------------------------------------


@pytest.fixture
def pm(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return ProtocolManager(el, seq, "wf-test")


class TestConsultation:
    def test_start_and_resolve(self, pm):
        pid = pm.start_consultation("a", "b", "which source?")
        assert pid
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.OPEN

        pm.resolve_consultation(pid, "Use IMF")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.ANSWERED
        assert proto.response == "Use IMF"
        assert proto.resolved_at is not None

    def test_events_logged(self, pm):
        pid = pm.start_consultation("a", "b", "q")
        pm.resolve_consultation(pid, "a")
        events = pm._event_log.query(workflow_id="wf-test")
        types = [e.event_type for e in events]
        assert EventType.PROTOCOL_STARTED in types
        assert EventType.PROTOCOL_RESOLVED in types


class TestReview:
    def test_approve(self, pm):
        pid = pm.start_review("author", "reviewer", "report.md")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.IN_REVIEW

        pm.submit_review_round(pid, "approve")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.APPROVED
        assert len(proto.rounds) == 1

    def test_revise_and_approve(self, pm):
        pid = pm.start_review("a", "r", "x.md")
        pm.submit_review_round(pid, "revise", issues=[{"desc": "fix data"}])
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.REVISION_REQUESTED

        pm.submit_review_round(pid, "approve")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.APPROVED
        assert len(proto.rounds) == 2

    def test_reject(self, pm):
        pid = pm.start_review("a", "r", "x.md")
        pm.submit_review_round(pid, "reject", feedback="fundamentally flawed")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.REJECTED

    def test_max_rounds_auto_rejects(self, pm):
        pid = pm.start_review("a", "r", "x.md", max_rounds=2)
        pm.submit_review_round(pid, "revise")
        pm.submit_review_round(pid, "revise")  # Round 2 = max
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.REJECTED


class TestEscalation:
    def test_start_and_resolve(self, pm):
        pid = pm.start_escalation("agent-a", "can't decide", context={"options": 2})
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.OPEN

        pm.resolve_escalation(pid, "Use option A")
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.RESOLVED
        assert proto.resolution == "Use option A"


class TestTimeouts:
    def test_detect_timeout(self, pm):
        # Start a consultation with a short timeout
        pid = pm.start_consultation("a", "b", "q", timeout_minutes=1)

        # Manually set created_at to the distant past so it's timed out
        pm._protocols[pid].created_at = "2020-01-01T00:00:00+00:00"

        timed_out = pm.check_timeouts()
        assert pid in timed_out
        proto = pm.get_protocol(pid)
        assert proto.state == ProtocolState.TIMEOUT

    def test_no_false_timeouts(self, pm):
        pid = pm.start_consultation("a", "b", "q", timeout_minutes=9999)
        timed_out = pm.check_timeouts()
        assert pid not in timed_out

    def test_resolved_not_timed_out(self, pm):
        pid = pm.start_consultation("a", "b", "q", timeout_minutes=1)
        pm._protocols[pid].created_at = "2020-01-01T00:00:00+00:00"
        pm.resolve_consultation(pid, "answer")
        timed_out = pm.check_timeouts()
        assert pid not in timed_out

    def test_timeout_event_logged(self, pm):
        pid = pm.start_consultation("a", "b", "q", timeout_minutes=1)
        pm._protocols[pid].created_at = "2020-01-01T00:00:00+00:00"
        pm.check_timeouts()
        events = pm._event_log.query(workflow_id="wf-test")
        assert any(e.event_type == EventType.PROTOCOL_TIMEOUT for e in events)


class TestQueries:
    def test_get_open_protocols(self, pm):
        pm.start_consultation("a", "b", "q1")
        pid2 = pm.start_consultation("a", "c", "q2")
        pm.resolve_consultation(pid2, "done")

        open_protos = pm.get_open_protocols()
        assert len(open_protos) == 1

    def test_filter_by_participant(self, pm):
        pm.start_consultation("a", "b", "q1")
        pm.start_consultation("a", "c", "q2")
        pm.start_escalation("d", "issue")

        open_a = pm.get_open_protocols("a")
        assert len(open_a) == 2

        open_d = pm.get_open_protocols("d")
        assert len(open_d) == 1

    def test_get_all(self, pm):
        pm.start_consultation("a", "b", "q")
        pm.start_review("a", "r", "x.md")
        all_protos = pm.get_all_protocols()
        assert len(all_protos) == 2

    def test_get_unknown_raises(self, pm):
        with pytest.raises(ValueError, match="Unknown protocol"):
            pm.get_protocol("nonexistent")

    def test_wrong_type_raises(self, pm):
        pid = pm.start_consultation("a", "b", "q")
        with pytest.raises(TypeError):
            pm.submit_review_round(pid, "approve")
