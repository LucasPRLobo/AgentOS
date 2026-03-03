"""Tests for agentos.kernel.gate_manager — gate lifecycle via events."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateError, GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType


@pytest.fixture
def gate_manager(event_log, seq):
    return GateManager(event_log, seq, workflow_id="test-wf")


class TestCreateGate:
    """Creating a gate emits GATE_WAITING and returns a gate_id."""

    def test_create_returns_gate_id(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL, "Review?")
        assert gate_id.startswith("gate-")

    def test_create_emits_gate_waiting_event(self, gate_manager, event_log):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL, "Review?")
        events = event_log.query(event_type=EventType.GATE_WAITING)
        assert len(events) == 1
        assert events[0].payload["gate_id"] == gate_id
        assert events[0].payload["task_id"] == "task_1"
        assert events[0].payload["gate_type"] == "approval"
        assert events[0].payload["prompt"] == "Review?"

    def test_create_input_gate(self, gate_manager, event_log):
        gate_id = gate_manager.create_gate("task_2", GateType.INPUT, "Provide API key:")
        events = event_log.query(event_type=EventType.GATE_WAITING)
        assert events[0].payload["gate_type"] == "input"

    def test_create_multiple_gates(self, gate_manager):
        id1 = gate_manager.create_gate("task_1", GateType.APPROVAL)
        id2 = gate_manager.create_gate("task_2", GateType.APPROVAL)
        assert id1 != id2


class TestResolveGate:
    """Resolving a gate emits GATE_RESOLVED and updates state."""

    def test_approve_gate(self, gate_manager, event_log):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL, "Review?")
        state = gate_manager.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="alice")
        assert state.pending is False
        assert state.resolution == GateResolution.APPROVED
        assert state.reviewer == "alice"

        events = event_log.query(event_type=EventType.GATE_RESOLVED)
        assert len(events) == 1
        assert events[0].payload["gate_id"] == gate_id
        assert events[0].payload["resolution"] == "approved"

    def test_reject_gate_with_feedback(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL, "Review?")
        state = gate_manager.resolve_gate(
            gate_id, GateResolution.REJECTED,
            reviewer="bob", feedback="Needs more detail.",
        )
        assert state.pending is False
        assert state.resolution == GateResolution.REJECTED
        assert state.feedback == "Needs more detail."

    def test_edit_gate(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.INPUT, "Provide key:")
        state = gate_manager.resolve_gate(
            gate_id, GateResolution.EDITED,
            reviewer="carol", feedback="Updated input provided.",
        )
        assert state.resolution == GateResolution.EDITED

    def test_resolve_nonexistent_raises(self, gate_manager):
        with pytest.raises(GateError, match="not found"):
            gate_manager.resolve_gate("gate-bogus", GateResolution.APPROVED)

    def test_resolve_already_resolved_raises(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL)
        gate_manager.resolve_gate(gate_id, GateResolution.APPROVED)
        with pytest.raises(GateError, match="already resolved"):
            gate_manager.resolve_gate(gate_id, GateResolution.APPROVED)


class TestGetGate:
    """get_gate derives current state from events."""

    def test_pending_gate(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL, "Review?")
        state = gate_manager.get_gate(gate_id)
        assert state is not None
        assert state.pending is True
        assert state.resolution is None
        assert state.task_id == "task_1"
        assert state.prompt == "Review?"

    def test_resolved_gate(self, gate_manager):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL)
        gate_manager.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="alice")
        state = gate_manager.get_gate(gate_id)
        assert state is not None
        assert state.pending is False
        assert state.resolution == GateResolution.APPROVED
        assert state.reviewer == "alice"

    def test_nonexistent_gate_returns_none(self, gate_manager):
        assert gate_manager.get_gate("gate-nope") is None


class TestListPending:
    """list_pending returns only unresolved gates."""

    def test_empty_when_no_gates(self, gate_manager):
        assert gate_manager.list_pending() == []

    def test_returns_pending_only(self, gate_manager):
        id1 = gate_manager.create_gate("task_1", GateType.APPROVAL, "First?")
        id2 = gate_manager.create_gate("task_2", GateType.APPROVAL, "Second?")
        gate_manager.resolve_gate(id1, GateResolution.APPROVED)

        pending = gate_manager.list_pending()
        assert len(pending) == 1
        assert pending[0].gate_id == id2
        assert pending[0].pending is True

    def test_empty_after_all_resolved(self, gate_manager):
        id1 = gate_manager.create_gate("task_1", GateType.APPROVAL)
        gate_manager.resolve_gate(id1, GateResolution.APPROVED)
        assert gate_manager.list_pending() == []


class TestListAll:
    """list_all returns all gates with current state."""

    def test_includes_pending_and_resolved(self, gate_manager):
        id1 = gate_manager.create_gate("task_1", GateType.APPROVAL)
        id2 = gate_manager.create_gate("task_2", GateType.APPROVAL)
        gate_manager.resolve_gate(id1, GateResolution.APPROVED)

        all_gates = gate_manager.list_all()
        assert len(all_gates) == 2

        by_id = {g.gate_id: g for g in all_gates}
        assert by_id[id1].pending is False
        assert by_id[id2].pending is True


class TestEventSequencing:
    """Gate events use the shared SeqCounter correctly."""

    def test_events_have_incrementing_seq(self, gate_manager, event_log):
        gate_id = gate_manager.create_gate("task_1", GateType.APPROVAL)
        gate_manager.resolve_gate(gate_id, GateResolution.APPROVED)

        events = event_log.replay("test-wf")
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # All unique
