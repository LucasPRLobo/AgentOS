"""Tests for agentos.comms.board_hooks — board auto-updates from events."""

import pytest

from agentos.comms.board_hooks import BoardEventHooks
from agentos.comms.board_manager import BoardManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType


@pytest.fixture
def board(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return BoardManager(el, seq, "wf-test")


@pytest.fixture
def hooks(board):
    return BoardEventHooks(
        board, total_budget_usd=10.0, total_budget_tokens=100_000,
    )


def _event(event_type, payload=None):
    return Event(
        event_type=event_type,
        workflow_id="wf-test",
        seq=0,
        payload=payload or {},
    )


class TestTaskStateChanged:
    def test_running_updates_status(self, hooks, board):
        hooks.on_event(_event(EventType.TASK_STATE_CHANGED, {
            "task_id": "t1", "agent_id": "research", "new_state": "RUNNING",
        }))
        state = board.get_state()
        assert len(state.team_status) == 1
        assert state.team_status[0].state == "running"
        assert state.team_status[0].current_task == "t1"

    def test_succeeded_posts_summary(self, hooks, board):
        hooks.on_event(_event(EventType.TASK_STATE_CHANGED, {
            "task_id": "t1", "agent_id": "research",
            "new_state": "SUCCEEDED", "summary": "Found 3 sources",
        }))
        state = board.get_state()
        assert state.team_status[0].state == "succeeded"
        assert any("Found 3 sources" in p.content for p in state.recent_posts)

    def test_failed_posts_alert(self, hooks, board):
        hooks.on_event(_event(EventType.TASK_STATE_CHANGED, {
            "task_id": "t1", "agent_id": "research",
            "new_state": "FAILED", "error": "API timeout",
        }))
        state = board.get_state()
        assert len(state.alerts) == 1
        assert "API timeout" in state.alerts[0].content


class TestBudget:
    def test_60_percent_alert(self, hooks, board):
        hooks.on_event(_event(EventType.BUDGET_CONSUMED, {"cost_usd": 6.5, "tokens": 0}))
        state = board.get_state()
        assert any("60%" in a.content for a in state.alerts)

    def test_80_percent_alert(self, hooks, board):
        hooks.on_event(_event(EventType.BUDGET_CONSUMED, {"cost_usd": 8.5, "tokens": 0}))
        state = board.get_state()
        alerts = [a.content for a in state.alerts]
        assert any("60%" in a for a in alerts)
        assert any("80%" in a for a in alerts)

    def test_no_duplicate_alerts(self, hooks, board):
        hooks.on_event(_event(EventType.BUDGET_CONSUMED, {"cost_usd": 6.5, "tokens": 0}))
        hooks.on_event(_event(EventType.BUDGET_CONSUMED, {"cost_usd": 0.5, "tokens": 0}))
        state = board.get_state()
        sixty_alerts = [a for a in state.alerts if "60%" in a.content]
        assert len(sixty_alerts) == 1

    def test_token_threshold(self, hooks, board):
        hooks.on_event(_event(EventType.BUDGET_CONSUMED, {"cost_usd": 0, "tokens": 65_000}))
        state = board.get_state()
        assert any("Token budget at 60%" in a.content for a in state.alerts)

    def test_budget_exceeded_pins_alert(self, hooks, board):
        hooks.on_event(_event(EventType.BUDGET_EXCEEDED, {
            "agent_id": "research", "dimension": "cost_usd",
        }))
        state = board.get_state()
        # Should be pinned to announcements
        assert any("BUDGET EXCEEDED" in a.content for a in state.announcements)


class TestGates:
    def test_gate_waiting_posts_question(self, hooks, board):
        hooks.on_event(_event(EventType.GATE_WAITING, {
            "gate_id": "g1", "gate_type": "approval", "task_id": "t1",
        }))
        state = board.get_state()
        assert len(state.open_questions) == 1
        assert "g1" in state.open_questions[0].content

    def test_gate_resolved_posts(self, hooks, board):
        hooks.on_event(_event(EventType.GATE_RESOLVED, {
            "gate_id": "g1", "action": "approved",
        }))
        state = board.get_state()
        assert any("approved" in p.content for p in state.recent_posts)


class TestAgentSpawned:
    def test_adds_to_roster(self, hooks, board):
        hooks.on_event(_event(EventType.AGENT_SPAWNED, {
            "agent_id": "new-agent", "role": "Validator",
        }))
        state = board.get_state()
        assert any(s.agent_id == "new-agent" for s in state.team_status)
        assert any("new-agent" in p.content for p in state.recent_posts)


class TestError:
    def test_error_posts_alert(self, hooks, board):
        hooks.on_event(_event(EventType.ERROR_OCCURRED, {
            "agent_id": "research", "error": "Connection reset",
        }))
        state = board.get_state()
        assert len(state.alerts) == 1
        assert "Connection reset" in state.alerts[0].content


class TestProcessEvents:
    def test_processes_batch(self, hooks, board):
        events = [
            _event(EventType.TASK_STATE_CHANGED, {
                "task_id": "t1", "agent_id": "a", "new_state": "RUNNING",
            }),
            _event(EventType.BUDGET_CONSUMED, {"cost_usd": 7.0, "tokens": 0}),
        ]
        count = hooks.process_events(events)
        assert count >= 2  # At least status update + budget alert

    def test_ignores_unhandled_events(self, hooks, board):
        v_before = board.get_state().version
        hooks.on_event(_event(EventType.FILE_CREATED, {"path": "test.txt"}))
        assert board.get_state().version == v_before
