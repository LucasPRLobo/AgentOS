"""Tests for agentos.comms.board_manager — shared board state."""

import pytest

from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    BoardState,
    SpeechAct,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


@pytest.fixture
def bm(tmp_path):
    event_log = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return BoardManager(event_log, seq, "wf-test")


def _post(content="test post", section="post", author_id="agent-a", **kw):
    return BoardPost(
        section=BoardSection(section),
        author_id=author_id,
        content=content,
        **kw,
    )


class TestPost:
    def test_post_to_recent(self, bm):
        bm.post(_post(content="hello"))
        state = bm.get_state()
        assert len(state.recent_posts) == 1
        assert state.recent_posts[0].content == "hello"

    def test_post_to_question(self, bm):
        bm.post(_post(content="which data?", section="question"))
        state = bm.get_state()
        assert len(state.open_questions) == 1

    def test_post_to_decision(self, bm):
        bm.post(_post(content="use IMF", section="decision"))
        state = bm.get_state()
        assert len(state.decisions) == 1

    def test_post_to_alert(self, bm):
        bm.post(_post(content="budget low", section="alert"))
        state = bm.get_state()
        assert len(state.alerts) == 1

    def test_post_to_announcement(self, bm):
        bm.post(_post(content="important", section="announcement"))
        state = bm.get_state()
        assert len(state.announcements) == 1

    def test_version_increments(self, bm):
        assert bm.get_state().version == 0
        bm.post(_post())
        assert bm.get_state().version == 1
        bm.post(_post())
        assert bm.get_state().version == 2

    def test_recent_posts_capped(self, bm):
        for i in range(25):
            bm.post(_post(content=f"post-{i}"))
        state = bm.get_state()
        assert len(state.recent_posts) == 20
        # Newest first
        assert state.recent_posts[0].content == "post-24"

    def test_post_logs_event(self, bm):
        bm.post(_post(content="logged"))
        events = bm._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.BOARD_POST_CREATED,
        )
        assert len(events) == 1
        assert events[0].payload["content_preview"] == "logged"

    def test_post_returns_id(self, bm):
        pid = bm.post(_post())
        assert pid
        assert isinstance(pid, str)


class TestPinUnpin:
    def test_pin_moves_to_announcements(self, bm):
        pid = bm.post(_post(content="pinnable"))
        bm.pin(pid)
        state = bm.get_state()
        assert len(state.announcements) == 1
        assert state.announcements[0].content == "pinnable"
        assert len(state.recent_posts) == 0

    def test_unpin_moves_to_recent(self, bm):
        pid = bm.post(_post(content="was pinned"))
        bm.pin(pid)
        bm.unpin(pid)
        state = bm.get_state()
        assert len(state.announcements) == 0
        assert len(state.recent_posts) == 1

    def test_pin_unknown_raises(self, bm):
        with pytest.raises(ValueError, match="Unknown post"):
            bm.pin("nonexistent")

    def test_pin_logs_event(self, bm):
        pid = bm.post(_post())
        bm.pin(pid)
        events = bm._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.BOARD_POST_PINNED,
        )
        assert len(events) == 1

    def test_pin_idempotent(self, bm):
        pid = bm.post(_post())
        bm.pin(pid)
        bm.pin(pid)  # no error
        state = bm.get_state()
        assert len(state.announcements) == 1


class TestResolve:
    def test_resolve_question(self, bm):
        pid = bm.post(_post(section="question", content="which source?"))
        bm.resolve(pid, resolved_by="agent-b")
        state = bm.get_state()
        assert state.open_questions[0].resolved is True
        assert state.open_questions[0].resolved_by == "agent-b"

    def test_resolve_logs_event(self, bm):
        pid = bm.post(_post(section="question"))
        bm.resolve(pid, resolved_by="human")
        events = bm._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.BOARD_POST_RESOLVED,
        )
        assert len(events) == 1

    def test_resolve_unknown_raises(self, bm):
        with pytest.raises(ValueError, match="Unknown post"):
            bm.resolve("nonexistent", resolved_by="x")


class TestArchive:
    def test_archive_removes_from_board(self, bm):
        pid = bm.post(_post(content="archivable"))
        bm.archive(pid)
        state = bm.get_state()
        assert len(state.recent_posts) == 0

    def test_archive_logs_event(self, bm):
        pid = bm.post(_post())
        bm.archive(pid)
        events = bm._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.BOARD_POST_ARCHIVED,
        )
        assert len(events) == 1

    def test_archive_unknown_raises(self, bm):
        with pytest.raises(ValueError, match="Unknown post"):
            bm.archive("nonexistent")


class TestAgentStatus:
    def test_add_agent(self, bm):
        bm.update_agent_status(AgentStatus(
            agent_id="research",
            agent_name="Research Agent",
            role="Researcher",
            state="running",
        ))
        state = bm.get_state()
        assert len(state.team_status) == 1
        assert state.team_status[0].state == "running"

    def test_update_existing_agent(self, bm):
        bm.update_agent_status(AgentStatus(agent_id="r", state="running"))
        bm.update_agent_status(AgentStatus(agent_id="r", state="succeeded"))
        state = bm.get_state()
        assert len(state.team_status) == 1
        assert state.team_status[0].state == "succeeded"


class TestSystemAlert:
    def test_add_alert(self, bm):
        pid = bm.add_system_alert("Budget at 80%")
        assert pid
        state = bm.get_state()
        assert len(state.alerts) == 1
        assert state.alerts[0].content == "Budget at 80%"
        assert state.alerts[0].author_type == "system"

    def test_alert_with_expiry(self, bm):
        bm.add_system_alert("temp alert", expires_minutes=5)
        state = bm.get_state()
        assert state.alerts[0].expires_at is not None


class TestRenderCompact:
    def test_renders_board(self, bm):
        bm.post(_post(content="a finding", section="announcement", pinned=True))
        bm.add_system_alert("watch out")
        bm.update_agent_status(AgentStatus(
            agent_id="r", agent_name="Research", state="running",
            progress_summary="50%",
        ))
        text = bm.render_compact()
        assert "[WORKSPACE BOARD" in text
        assert "PINNED:" in text
        assert "ALERT:" in text
        assert "Research" in text
        assert "[END BOARD]" in text

    def test_respects_token_budget(self, bm):
        for i in range(30):
            bm.post(_post(content=f"post number {i} with some extra text to fill tokens"))
        text = bm.render_compact(max_tokens=100)
        # Should be roughly within budget (100 tokens * 4 chars = 400 chars)
        assert len(text) < 600

    def test_empty_board(self, bm):
        text = bm.render_compact()
        assert "[WORKSPACE BOARD" in text
        assert "[END BOARD]" in text


class TestCleanup:
    def test_cleanup_expired(self, bm):
        # Add an alert that's already expired
        post = BoardPost(
            section=BoardSection.ALERT,
            author_type="system",
            author_id="system",
            content="old alert",
            expires_at="2020-01-01T00:00:00+00:00",
        )
        bm.post(post)
        count = bm.cleanup_expired()
        assert count == 1
        state = bm.get_state()
        assert len(state.alerts) == 0

    def test_cleanup_resolved(self, bm):
        pid = bm.post(_post(section="question", content="resolved q"))
        bm.resolve(pid, resolved_by="x")
        # With 0 minute threshold, should archive immediately
        count = bm.cleanup_resolved(older_than_minutes=0)
        assert count == 1


class TestRenderFull:
    def test_render_full_returns_dict(self, bm):
        bm.post(_post(content="test"))
        data = bm.render_full()
        assert isinstance(data, dict)
        assert data["workflow_id"] == "wf-test"
        assert len(data["recent_posts"]) == 1
