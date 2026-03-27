"""Tests for agentos.comms.ambient_context — board + message injection."""

import pytest

from agentos.comms.ambient_context import AmbientContextInjector
from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import (
    BoardPost,
    BoardSection,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter


@pytest.fixture
def board(tmp_path):
    event_log = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return BoardManager(event_log, seq, "wf-test")


@pytest.fixture
def injector(board):
    return AmbientContextInjector(board)


def _msg(content="hello", sender="agent-a", priority="normal", speech_act="inform"):
    return DirectMessage(
        sender_id=sender,
        recipient_id="agent-b",
        content=content,
        speech_act=SpeechAct(speech_act),
        priority=MessagePriority(priority),
        workflow_id="wf-test",
    )


class TestRenderForAgent:
    def test_returns_board_text(self, injector, board):
        board.post(BoardPost(
            author_id="agent-a",
            content="finding",
        ))
        text = injector.render_for_agent("agent-b")
        assert text is not None
        assert "[WORKSPACE BOARD" in text

    def test_returns_none_when_unchanged(self, injector, board):
        board.post(BoardPost(author_id="a", content="x"))
        state = board.get_state()
        result = injector.render_for_agent("b", last_seen_version=state.version)
        assert result is None

    def test_returns_text_when_version_advanced(self, injector, board):
        board.post(BoardPost(author_id="a", content="first"))
        v1 = board.get_state().version
        board.post(BoardPost(author_id="a", content="second"))
        result = injector.render_for_agent("b", last_seen_version=v1)
        assert result is not None


class TestFormatMessageInjection:
    def test_empty_list(self):
        assert AmbientContextInjector.format_message_injection([]) == ""

    def test_single_inform(self):
        text = AmbientContextInjector.format_message_injection([_msg(content="data ready")])
        assert "TEAM COMMUNICATION" in text
        assert "data ready" in text
        assert "END TEAM COMMUNICATION" in text

    def test_high_priority_highlighted(self):
        text = AmbientContextInjector.format_message_injection([
            _msg(content="urgent", priority="high"),
        ])
        assert "PRIORITY: HIGH" in text

    def test_directive_highlighted(self):
        text = AmbientContextInjector.format_message_injection([
            _msg(content="do this", speech_act="directive"),
        ])
        assert "DIRECTIVE" in text

    def test_request_prompts_response(self):
        text = AmbientContextInjector.format_message_injection([
            _msg(content="which source?", speech_act="request"),
        ])
        assert "Response expected" in text

    def test_multiple_messages(self):
        msgs = [
            _msg(content="msg one", sender="agent-a"),
            _msg(content="msg two", sender="agent-b"),
        ]
        text = AmbientContextInjector.format_message_injection(msgs)
        assert "msg one" in text
        assert "msg two" in text


class TestBuildInjection:
    def test_board_only(self, injector, board):
        board.post(BoardPost(author_id="a", content="finding"))
        result = injector.build_injection("agent-b")
        assert result is not None
        assert "WORKSPACE BOARD" in result

    def test_messages_only(self, injector):
        msgs = [_msg(content="hello")]
        result = injector.build_injection(
            "agent-b",
            pending_messages=msgs,
            last_seen_board_version=0,  # board version is 0, unchanged
        )
        assert result is not None
        assert "TEAM COMMUNICATION" in result

    def test_both_board_and_messages(self, injector, board):
        board.post(BoardPost(author_id="a", content="finding"))
        msgs = [_msg(content="check this")]
        result = injector.build_injection("agent-b", pending_messages=msgs)
        assert "WORKSPACE BOARD" in result
        assert "TEAM COMMUNICATION" in result

    def test_nothing_to_inject(self, injector):
        result = injector.build_injection(
            "agent-b",
            last_seen_board_version=0,
        )
        assert result is None
