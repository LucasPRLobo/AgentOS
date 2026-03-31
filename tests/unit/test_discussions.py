"""Tests for discussion threads and the collaborative flow."""

import pytest

from agentos.comms.discussions import (
    DiscussionManager,
    DiscussionStatus,
    DiscussionThread,
    DiscussionType,
)
from agentos.comms.board_manager import BoardManager
from agentos.comms.message_bus import MessageBus
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


@pytest.fixture
def dm(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    bus = MessageBus(el, seq, "wf-test")
    board = BoardManager(el, seq, "wf-test")
    return DiscussionManager(el, seq, "wf-test", bus, board)


class TestOpen:
    def test_open_returns_thread_id(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Project kickoff", "What are your priorities?")
        assert tid
        assert isinstance(tid, str)

    def test_open_creates_thread(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Question?")
        thread = dm.get_thread(tid)
        assert thread.discussion_type == DiscussionType.KICKOFF
        assert thread.status == DiscussionStatus.OPEN
        assert thread.title == "Test"
        assert len(thread.messages) == 1
        assert thread.messages[0]["content"] == "Question?"

    def test_open_with_options(self, dm):
        tid = dm.open(
            DiscussionType.TASK_SPEC, "Task approach",
            "How should we approach this?",
            options=["Option A: deep dive", "Option B: quick scan"],
        )
        thread = dm.get_thread(tid)
        assert thread.options == ["Option A: deep dive", "Option B: quick scan"]

    def test_open_with_related_task(self, dm):
        tid = dm.open(
            DiscussionType.REVIEW, "Review research",
            "Here's what the researcher found...",
            related_task_id="task-123",
        )
        thread = dm.get_thread(tid)
        assert thread.related_task_id == "task-123"

    def test_open_posts_to_board(self, dm):
        dm.open(DiscussionType.KICKOFF, "Test", "Question?")
        board_state = dm._board.get_state()
        # Should have posted to board
        all_posts = board_state.open_questions + board_state.recent_posts
        assert any("Question?" in p.content for p in all_posts)

    def test_open_sends_message_to_human(self, dm):
        dm.open(DiscussionType.KICKOFF, "Test", "What do you think?")
        msgs = dm._bus.receive("human")
        assert len(msgs) == 1
        assert "What do you think?" in msgs[0].content

    def test_open_logs_event(self, dm):
        dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        events = dm._event_log.query(workflow_id="wf-test", event_type=EventType.DISCUSSION_OPENED)
        assert len(events) == 1


class TestMessages:
    def test_add_message(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.add_message(tid, "human", "Focus on architecture", sender_type="human")
        thread = dm.get_thread(tid)
        assert len(thread.messages) == 2
        assert thread.messages[1]["content"] == "Focus on architecture"

    def test_human_response_activates(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        assert dm.get_thread(tid).status == DiscussionStatus.OPEN
        dm.add_message(tid, "human", "My answer", sender_type="human")
        assert dm.get_thread(tid).status == DiscussionStatus.ACTIVE

    def test_cannot_message_resolved(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.resolve(tid, "Agreed on X")
        with pytest.raises(ValueError, match="already resolved"):
            dm.add_message(tid, "human", "Too late")

    def test_message_logs_event(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.add_message(tid, "human", "Answer")
        events = dm._event_log.query(workflow_id="wf-test", event_type=EventType.DISCUSSION_MESSAGE)
        assert len(events) == 1


class TestResolve:
    def test_resolve_records_decision(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.add_message(tid, "human", "Let's do A")
        dm.resolve(tid, "Go with approach A", rationale="Human preferred it")
        thread = dm.get_thread(tid)
        assert thread.status == DiscussionStatus.RESOLVED
        assert thread.decision == "Go with approach A"
        assert thread.decision_rationale == "Human preferred it"
        assert thread.resolved_at is not None

    def test_resolve_posts_decision_to_board(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.resolve(tid, "Decided X")
        board = dm._board.get_state()
        assert any("Decided X" in p.content for p in board.decisions)

    def test_resolve_logs_event(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.resolve(tid, "Done")
        events = dm._event_log.query(workflow_id="wf-test", event_type=EventType.DISCUSSION_RESOLVED)
        assert len(events) == 1


class TestDefer:
    def test_defer(self, dm):
        tid = dm.open(DiscussionType.CHECK_IN, "Check", "How's it going?")
        dm.defer(tid, "Will revisit later")
        assert dm.get_thread(tid).status == DiscussionStatus.DEFERRED


class TestQueries:
    def test_get_open(self, dm):
        dm.open(DiscussionType.KICKOFF, "Open1", "Q1?")
        tid2 = dm.open(DiscussionType.REVIEW, "Open2", "Q2?")
        dm.resolve(tid2, "Done")
        open_threads = dm.get_open()
        assert len(open_threads) == 1
        assert open_threads[0].title == "Open1"

    def test_get_for_task(self, dm):
        dm.open(DiscussionType.TASK_SPEC, "Spec", "Q?", related_task_id="t1")
        dm.open(DiscussionType.REVIEW, "Review", "Q?", related_task_id="t1")
        dm.open(DiscussionType.KICKOFF, "Kickoff", "Q?")
        assert len(dm.get_for_task("t1")) == 2
        assert len(dm.get_for_task("t2")) == 0

    def test_has_open_discussions(self, dm):
        assert dm.has_open_discussions() is False
        dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        assert dm.has_open_discussions() is True

    def test_get_resolved_decisions(self, dm):
        tid = dm.open(DiscussionType.KICKOFF, "Test", "Q?")
        dm.resolve(tid, "Use approach A")
        decisions = dm.get_resolved_decisions()
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "Use approach A"

    def test_get_all(self, dm):
        dm.open(DiscussionType.KICKOFF, "A", "Q?")
        dm.open(DiscussionType.REVIEW, "B", "Q?")
        assert len(dm.get_all()) == 2

    def test_unknown_thread_raises(self, dm):
        with pytest.raises(ValueError, match="Unknown discussion"):
            dm.get_thread("nonexistent")


class TestCollaborativeFlow:
    """Test a full kickoff → spec → review discussion flow."""

    def test_full_flow(self, dm):
        # 1. Kickoff discussion
        kickoff_id = dm.open(DiscussionType.KICKOFF, "Project kickoff",
                              "What are your priorities for this project?",
                              options=["Speed", "Quality", "Cost"])
        dm.add_message(kickoff_id, "human", "Focus on quality. Audience is technical.", sender_type="human")
        dm.add_message(kickoff_id, "coordinator", "Got it. I'll prioritize thorough research.",
                       sender_type="agent", speech_act="confirm")
        dm.resolve(kickoff_id, "Quality-first approach, technical audience")

        # 2. Task spec discussion
        spec_id = dm.open(DiscussionType.TASK_SPEC, "Research approach",
                           "I'm thinking the researcher should focus on architecture details.",
                           related_task_id="task-1",
                           options=["Deep architecture dive", "Broad ecosystem survey"])
        dm.add_message(spec_id, "human", "Deep dive on architecture. Also compare pricing.", sender_type="human")
        dm.resolve(spec_id, "Deep architecture dive + pricing comparison")

        # 3. Review discussion
        review_id = dm.open(DiscussionType.REVIEW, "Research review",
                             "Research is done. Key finding: A2A and MCP are complementary.",
                             related_task_id="task-1")
        dm.add_message(review_id, "human", "Looks good. Accept and move on.", sender_type="human")
        dm.resolve(review_id, "Accepted — move to writing phase")

        # Verify the full trail
        assert not dm.has_open_discussions()
        decisions = dm.get_resolved_decisions()
        assert len(decisions) == 3
        assert "Quality-first" in decisions[0]["decision"]
        assert "architecture dive" in decisions[1]["decision"]
        assert "Accepted" in decisions[2]["decision"]
