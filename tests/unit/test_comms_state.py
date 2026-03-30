"""Tests for agentos.comms.comms_state — MCP server state file I/O."""

import json

import pytest

from agentos.comms.board_manager import BoardManager
from agentos.comms.comms_state import (
    read_comms_state,
    refresh_comms_state,
    write_comms_state,
    write_outbox_message,
)
from agentos.comms.schemas import BoardPost, DirectMessage, SpeechAct
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def board(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    bm = BoardManager(el, seq, "wf-test")
    bm.post(BoardPost(author_id="a", content="hello board"))
    return bm


class TestWriteCommsState:
    def test_writes_state_file(self, workspace, board):
        msgs = [DirectMessage(
            sender_id="human", recipient_id="agent-a",
            content="focus on X", workflow_id="wf-test",
            speech_act=SpeechAct.DIRECTIVE,
        )]
        path = write_comms_state(workspace, board, msgs, "agent-a", "wf-test")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["agent_id"] == "agent-a"
        assert data["workflow_id"] == "wf-test"
        assert "WORKSPACE BOARD" in data["board_compact"]
        assert len(data["inbox"]) == 1
        assert data["inbox"][0]["content"] == "focus on X"

    def test_empty_inbox(self, workspace, board):
        path = write_comms_state(workspace, board, [], "agent-a", "wf-test")
        data = json.loads(path.read_text())
        assert data["inbox"] == []


class TestReadCommsState:
    def test_reads_existing(self, workspace, board):
        write_comms_state(workspace, board, [], "agent-a", "wf-test")
        state = read_comms_state(workspace)
        assert state["agent_id"] == "agent-a"

    def test_missing_file_returns_defaults(self, workspace):
        state = read_comms_state(workspace)
        assert state["agent_id"] == "unknown"
        assert state["inbox"] == []

    def test_corrupt_file_returns_defaults(self, workspace):
        (workspace / ".agentos").mkdir()
        (workspace / ".agentos" / "comms_state.json").write_text("not json")
        state = read_comms_state(workspace)
        assert state["agent_id"] == "unknown"


class TestWriteOutboxMessage:
    def test_writes_json_file(self, workspace):
        msg = {"to": "human", "content": "help"}
        path = write_outbox_message(workspace, msg)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["to"] == "human"

    def test_sequential_naming(self, workspace):
        write_outbox_message(workspace, {"to": "a", "content": "1"})
        write_outbox_message(workspace, {"to": "b", "content": "2"})
        outbox = workspace / ".agentos" / "outbox"
        files = sorted(outbox.glob("*.json"))
        assert len(files) == 2


class TestRefreshCommsState:
    def test_updates_board(self, workspace, board):
        write_comms_state(workspace, board, [], "agent-a", "wf-test")
        refresh_comms_state(workspace, board_compact="NEW BOARD STATE")
        state = read_comms_state(workspace)
        assert state["board_compact"] == "NEW BOARD STATE"

    def test_appends_inbox(self, workspace, board):
        write_comms_state(workspace, board, [], "agent-a", "wf-test")
        refresh_comms_state(workspace, new_inbox_messages=[
            {"sender_id": "b", "content": "new msg"}
        ])
        state = read_comms_state(workspace)
        assert len(state["inbox"]) == 1
