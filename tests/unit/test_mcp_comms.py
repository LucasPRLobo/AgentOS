"""Tests for agentos.comms.mcp_server — MCP tool functions."""

import json

import pytest

from agentos.comms.comms_state import read_comms_state, write_comms_state, write_outbox_message
from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import BoardPost, DirectMessage, SpeechAct
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter

# We test the MCP tool functions directly by calling them with a mocked workspace,
# rather than spinning up the MCP server over stdio.
import agentos.comms.mcp_server as mcp_mod


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
    bm.post(BoardPost(
        author_id="human", content="Project: research AI protocols",
        pinned=True, section="announcement",
    ))
    return bm


@pytest.fixture
def setup_workspace(workspace, board):
    """Write comms state to workspace and point the MCP module at it."""
    msgs = [DirectMessage(
        sender_id="human", recipient_id="research-agent",
        content="Focus on A2A", workflow_id="wf-test",
        speech_act=SpeechAct.DIRECTIVE,
    )]
    write_comms_state(workspace, board, msgs, "research-agent", "wf-test")

    # Point the MCP server module at our workspace
    mcp_mod._workspace = workspace
    yield workspace
    mcp_mod._workspace = None


class TestReadBoard:
    def test_returns_board_text(self, setup_workspace):
        result = mcp_mod.read_board()
        assert "WORKSPACE BOARD" in result

    def test_empty_workspace(self, workspace):
        mcp_mod._workspace = workspace
        result = mcp_mod.read_board()
        assert "WORKSPACE BOARD" in result
        mcp_mod._workspace = None


class TestPostToBoard:
    def test_post_creates_outbox_file(self, setup_workspace):
        result = mcp_mod.post_to_board("Important finding", section="post")
        assert "Posted to board" in result

        outbox = setup_workspace / ".agentos" / "outbox"
        files = list(outbox.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["to"] == "board"
        assert data["content"] == "Important finding"
        assert data["section"] == "post"

    def test_question_section(self, setup_workspace):
        mcp_mod.post_to_board("Which source?", section="question", speech_act="request")
        outbox = setup_workspace / ".agentos" / "outbox"
        data = json.loads(list(outbox.glob("*.json"))[0].read_text())
        assert data["section"] == "question"
        assert data["speech_act"] == "request"

    def test_invalid_section(self, setup_workspace):
        result = mcp_mod.post_to_board("x", section="invalid")
        assert "Invalid section" in result

    def test_invalid_speech_act(self, setup_workspace):
        result = mcp_mod.post_to_board("x", speech_act="invalid")
        assert "Invalid speech_act" in result


class TestCheckMessages:
    def test_returns_messages(self, setup_workspace):
        result = mcp_mod.check_messages()
        assert "1 message(s)" in result
        assert "Focus on A2A" in result
        assert "DIRECTIVE" in result.lower() or "directive" in result.lower()

    def test_no_messages(self, workspace):
        mcp_mod._workspace = workspace
        # Write state with empty inbox
        (workspace / ".agentos").mkdir()
        (workspace / ".agentos" / "comms_state.json").write_text(
            json.dumps({"agent_id": "a", "workflow_id": "w", "inbox": [],
                         "board_compact": "", "board_full": {}})
        )
        result = mcp_mod.check_messages()
        assert "No new messages" in result
        mcp_mod._workspace = None


class TestSendMessage:
    def test_send_creates_outbox(self, setup_workspace):
        result = mcp_mod.send_message(
            to="analysis-agent", content="Check my finding",
            speech_act="request", priority="high",
        )
        assert "Message sent" in result

        outbox = setup_workspace / ".agentos" / "outbox"
        files = list(outbox.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["to"] == "analysis-agent"
        assert data["speech_act"] == "request"
        assert data["priority"] == "high"

    def test_send_uses_per_agent_outbox_when_agent_id_set(self, setup_workspace, monkeypatch):
        """When AGENTOS_AGENT_ID is set, send_message writes to the per-agent
        outbox directory so the supervisor's read_all_agent_outboxes picks it up.
        This is the fix for the bug where agent DM replies were invisible to the TUI.
        """
        monkeypatch.setenv("AGENTOS_AGENT_ID", "researcher")
        result = mcp_mod.send_message(to="human", content="Here is my reply")
        assert "Message sent" in result

        # Message must be in the per-agent outbox
        from agentos.comms.comms_state import read_agent_outbox
        msgs = read_agent_outbox(setup_workspace, "researcher")
        assert len(msgs) == 1
        assert msgs[0]["to"] == "human"
        assert msgs[0]["content"] == "Here is my reply"

        # Legacy global outbox must be empty
        global_outbox = setup_workspace / ".agentos" / "outbox"
        assert not global_outbox.exists() or list(global_outbox.glob("*.json")) == []

    def test_invalid_speech_act(self, setup_workspace):
        result = mcp_mod.send_message(to="x", content="y", speech_act="bad")
        assert "Invalid" in result

    def test_invalid_priority(self, setup_workspace):
        result = mcp_mod.send_message(to="x", content="y", priority="urgent")
        assert "Invalid" in result


class TestRequestConsultation:
    def test_creates_outbox_with_protocol(self, setup_workspace):
        result = mcp_mod.request_consultation(
            expert="analysis-agent", question="Which GDP source?",
        )
        assert "Consultation request sent" in result

        outbox = setup_workspace / ".agentos" / "outbox"
        data = json.loads(list(outbox.glob("*.json"))[0].read_text())
        assert data["protocol"] == "consultation"
        assert data["to"] == "analysis-agent"


class TestRequestReview:
    def test_creates_outbox_with_protocol(self, setup_workspace):
        result = mcp_mod.request_review(
            reviewer="human", artifact_path="report.md",
            criteria="accuracy, clarity",
        )
        assert "Review request sent" in result

        outbox = setup_workspace / ".agentos" / "outbox"
        data = json.loads(list(outbox.glob("*.json"))[0].read_text())
        assert data["protocol"] == "review"
        assert data["protocol_data"]["artifact_path"] == "report.md"


class TestEscalate:
    def test_creates_two_outbox_files(self, setup_workspace):
        result = mcp_mod.escalate(
            issue="Can't resolve conflicting data",
            context="IMF says 2.3%, World Bank says 2.7%",
        )
        assert "escalated" in result.lower()

        outbox = setup_workspace / ".agentos" / "outbox"
        files = sorted(outbox.glob("*.json"))
        # Should create both a message to human AND a board alert
        assert len(files) == 2
        targets = {json.loads(f.read_text())["to"] for f in files}
        assert "human" in targets
        assert "board" in targets
