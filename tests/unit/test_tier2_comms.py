"""Tests for Tier 2 workspace-based communication helpers."""

import json

import pytest

from agentos.adapters.tier2_shared import (
    cleanup_comms_files,
    read_outbox,
    write_board_state,
    write_comms_prompt_addition,
    write_inbox,
)
from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import (
    BoardPost,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "workspace"


@pytest.fixture
def board(tmp_path):
    event_log = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    bm = BoardManager(event_log, seq, "wf-test")
    bm.post(BoardPost(author_id="agent-a", content="test finding"))
    return bm


def _msg(content="hello", sender="agent-a", speech_act="inform"):
    return DirectMessage(
        sender_id=sender,
        recipient_id="agent-b",
        content=content,
        speech_act=SpeechAct(speech_act),
        workflow_id="wf-test",
    )


class TestWriteBoardState:
    def test_writes_board_file(self, workspace, board):
        workspace.mkdir()
        write_board_state(workspace, board)
        path = workspace / ".agentos" / "board.md"
        assert path.exists()
        text = path.read_text()
        assert "WORKSPACE BOARD" in text
        assert "test finding" in text

    def test_creates_agentos_dir(self, workspace, board):
        workspace.mkdir()
        write_board_state(workspace, board)
        assert (workspace / ".agentos").is_dir()


class TestWriteInbox:
    def test_writes_message_files(self, workspace):
        workspace.mkdir()
        msgs = [_msg(content="first"), _msg(content="second")]
        write_inbox(workspace, msgs)
        inbox = workspace / ".agentos" / "inbox"
        files = list(inbox.glob("msg-*.md"))
        assert len(files) == 2

    def test_message_content(self, workspace):
        workspace.mkdir()
        msgs = [_msg(content="check this data", speech_act="request")]
        write_inbox(workspace, msgs)
        inbox = workspace / ".agentos" / "inbox"
        files = list(inbox.glob("msg-*.md"))
        text = files[0].read_text()
        assert "check this data" in text
        assert "Response expected" in text

    def test_clears_stale_files(self, workspace):
        workspace.mkdir()
        write_inbox(workspace, [_msg(content="old")])
        # Write again — old files should be cleared
        write_inbox(workspace, [_msg(content="new")])
        inbox = workspace / ".agentos" / "inbox"
        files = list(inbox.glob("msg-*.md"))
        assert len(files) == 1
        assert "new" in files[0].read_text()


class TestReadOutbox:
    def test_reads_json_files(self, workspace):
        workspace.mkdir()
        outbox = workspace / ".agentos" / "outbox"
        outbox.mkdir(parents=True)
        data = {"to": "human", "content": "need help", "speech_act": "request"}
        (outbox / "reply-001.json").write_text(json.dumps(data))
        results = read_outbox(workspace)
        assert len(results) == 1
        assert results[0]["to"] == "human"
        assert results[0]["content"] == "need help"

    def test_deletes_after_reading(self, workspace):
        workspace.mkdir()
        outbox = workspace / ".agentos" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "msg.json").write_text(json.dumps({"to": "x", "content": "y"}))
        read_outbox(workspace)
        assert not list(outbox.glob("*.json"))

    def test_skips_invalid_json(self, workspace):
        workspace.mkdir()
        outbox = workspace / ".agentos" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "bad.json").write_text("not json")
        (outbox / "good.json").write_text(json.dumps({"to": "a", "content": "b"}))
        results = read_outbox(workspace)
        assert len(results) == 1

    def test_skips_missing_fields(self, workspace):
        workspace.mkdir()
        outbox = workspace / ".agentos" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "bad.json").write_text(json.dumps({"no_to": "x"}))
        results = read_outbox(workspace)
        assert len(results) == 0

    def test_empty_outbox(self, workspace):
        workspace.mkdir()
        results = read_outbox(workspace)
        assert results == []


class TestCleanup:
    def test_cleanup_removes_files(self, workspace):
        workspace.mkdir()
        write_inbox(workspace, [_msg()])
        outbox = workspace / ".agentos" / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "msg.json").write_text("{}")
        cleanup_comms_files(workspace)
        assert not list((workspace / ".agentos" / "inbox").iterdir())
        assert not list(outbox.iterdir())

    def test_cleanup_nonexistent_dir(self, workspace):
        workspace.mkdir()
        cleanup_comms_files(workspace)  # should not raise


class TestPromptAddition:
    def test_returns_prompt_text(self):
        text = write_comms_prompt_addition()
        assert "Team Communication" in text
        assert ".agentos/board.md" in text
        assert ".agentos/inbox/" in text
        assert ".agentos/outbox/" in text
