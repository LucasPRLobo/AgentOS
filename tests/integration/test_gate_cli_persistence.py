"""Integration tests — gate CLI persistence and cross-process resolution.

Tests: approve/reject via CLI with persisted DB, seq continuation,
feedback visibility, resolve-twice protection.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from agentos.cli.main import cli
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_with_gate(tmp_path):
    """Create a persisted DB with a workflow that has a pending gate."""
    db_path = str(tmp_path / "test.db")
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()
    workflow_id = "test-wf-gate"

    # Emit workflow started
    from agentos.schemas.events import Event
    event_log.append(Event(
        event_type=EventType.WORKFLOW_STARTED,
        workflow_id=workflow_id,
        seq=seq.next(),
        payload={"workflow_name": "gate-test", "task_count": 2},
    ))

    # Create a pending gate
    gate_mgr = GateManager(event_log, seq, workflow_id)
    gate_id = gate_mgr.create_gate("review_step", GateType.APPROVAL, "Please review the output.")

    return db_path, gate_id, workflow_id


@pytest.fixture
def db_with_two_gates(tmp_path):
    """Create a persisted DB with two pending gates in the same workflow."""
    db_path = str(tmp_path / "test2.db")
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()
    workflow_id = "test-wf-multi"

    from agentos.schemas.events import Event
    event_log.append(Event(
        event_type=EventType.WORKFLOW_STARTED,
        workflow_id=workflow_id,
        seq=seq.next(),
        payload={"workflow_name": "multi-gate", "task_count": 3},
    ))

    gate_mgr = GateManager(event_log, seq, workflow_id)
    gate_id_1 = gate_mgr.create_gate("step_1", GateType.APPROVAL, "First gate")
    gate_id_2 = gate_mgr.create_gate("step_2", GateType.APPROVAL, "Second gate")

    return db_path, gate_id_1, gate_id_2, workflow_id


# ---------------------------------------------------------------------------
# Tests: Gate approve via CLI with persisted DB
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestGateApproveViaCLI:
    """Approve a gate from a separate CLI invocation on a persisted DB."""

    def test_approve_persisted_gate(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        result = runner.invoke(cli, [
            "gate", "approve", gate_id, "--db", db_path,
            "--reviewer", "human-tester",
        ])

        assert result.exit_code == 0
        assert "APPROVED" in result.output

        # Verify the gate is resolved in the DB
        event_log = SQLiteEventLog(db_path)
        resolved = event_log.query(
            workflow_id=wf_id, event_type=EventType.GATE_RESOLVED,
        )
        assert len(resolved) == 1
        assert resolved[0].payload["gate_id"] == gate_id
        assert resolved[0].payload["resolution"] == "approved"
        assert resolved[0].payload["reviewer"] == "human-tester"

    def test_approve_with_feedback(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        result = runner.invoke(cli, [
            "gate", "approve", gate_id, "--db", db_path,
            "--feedback", "Looks good, proceed.",
        ])

        assert result.exit_code == 0
        assert "Looks good" in result.output

        event_log = SQLiteEventLog(db_path)
        resolved = event_log.query(
            workflow_id=wf_id, event_type=EventType.GATE_RESOLVED,
        )
        assert resolved[0].payload["feedback"] == "Looks good, proceed."


# ---------------------------------------------------------------------------
# Tests: Gate reject via CLI
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestGateRejectViaCLI:

    def test_reject_persisted_gate(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        result = runner.invoke(cli, [
            "gate", "reject", gate_id, "--db", db_path,
            "--feedback", "Needs more detail in section 3.",
        ])

        assert result.exit_code == 0
        assert "REJECTED" in result.output

        event_log = SQLiteEventLog(db_path)
        resolved = event_log.query(
            workflow_id=wf_id, event_type=EventType.GATE_RESOLVED,
        )
        assert resolved[0].payload["resolution"] == "rejected"
        assert resolved[0].payload["feedback"] == "Needs more detail in section 3."


# ---------------------------------------------------------------------------
# Tests: Seq continuation from persisted DB
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSeqContinuation:
    """Gate resolve correctly continues sequence from persisted DB."""

    def test_seq_continues_from_max(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        # Check max seq before approval
        event_log = SQLiteEventLog(db_path)
        events_before = event_log.replay(wf_id)
        max_seq_before = max(e.seq for e in events_before)

        # Approve via CLI (separate process simulation)
        result = runner.invoke(cli, [
            "gate", "approve", gate_id, "--db", db_path,
        ])
        assert result.exit_code == 0

        # New event should have seq > max_seq_before
        event_log2 = SQLiteEventLog(db_path)
        events_after = event_log2.replay(wf_id)
        new_events = [e for e in events_after if e.seq > max_seq_before]
        assert len(new_events) == 1
        assert new_events[0].event_type == EventType.GATE_RESOLVED
        assert new_events[0].seq > max_seq_before


# ---------------------------------------------------------------------------
# Tests: Resolve twice fails
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestResolveTwice:

    def test_approve_already_approved_fails(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        # First approval
        result1 = runner.invoke(cli, ["gate", "approve", gate_id, "--db", db_path])
        assert result1.exit_code == 0

        # Second approval should fail
        result2 = runner.invoke(cli, ["gate", "approve", gate_id, "--db", db_path])
        assert result2.exit_code == 1
        assert "already resolved" in result2.output.lower()


# ---------------------------------------------------------------------------
# Tests: Gate list with feedback visibility
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestGateListVisibility:

    def test_list_shows_feedback_and_reviewer(self, runner, db_with_gate):
        db_path, gate_id, wf_id = db_with_gate

        # Approve with feedback
        runner.invoke(cli, [
            "gate", "approve", gate_id, "--db", db_path,
            "--reviewer", "alice", "--feedback", "Ship it!",
        ])

        # List all gates (including resolved)
        result = runner.invoke(cli, ["gate", "list", "--db", db_path, "--all"])
        assert result.exit_code == 0
        assert "APPROVED" in result.output
        assert "Ship it!" in result.output
        assert "alice" in result.output

    def test_list_pending_shows_only_unresolved(self, runner, db_with_two_gates):
        db_path, gate_id_1, gate_id_2, wf_id = db_with_two_gates

        # Approve first gate
        runner.invoke(cli, ["gate", "approve", gate_id_1, "--db", db_path])

        # List pending (should only show gate_id_2)
        result = runner.invoke(cli, ["gate", "list", "--db", db_path])
        assert result.exit_code == 0
        assert gate_id_2 in result.output
        assert gate_id_1 not in result.output
