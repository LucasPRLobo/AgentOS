"""Tests for agentos.comms.schemas — message and board data models."""

from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    BoardState,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)


class TestSpeechAct:
    def test_all_values(self):
        assert SpeechAct.INFORM == "inform"
        assert SpeechAct.REQUEST == "request"
        assert SpeechAct.PROPOSE == "propose"
        assert SpeechAct.ACCEPT == "accept"
        assert SpeechAct.REJECT == "reject"
        assert SpeechAct.CONFIRM == "confirm"
        assert SpeechAct.ALERT == "alert"
        assert SpeechAct.DIRECTIVE == "directive"
        assert SpeechAct.STATUS == "status"

    def test_string_coercion(self):
        assert SpeechAct("inform") == SpeechAct.INFORM


class TestMessagePriority:
    def test_ordering(self):
        values = list(MessagePriority)
        assert values == [
            MessagePriority.LOW,
            MessagePriority.NORMAL,
            MessagePriority.HIGH,
            MessagePriority.CRITICAL,
        ]


class TestDirectMessage:
    def test_defaults(self):
        msg = DirectMessage(
            sender_id="agent-a",
            recipient_id="agent-b",
            content="hello",
            workflow_id="wf-1",
        )
        assert msg.message_id  # auto-generated UUID
        assert msg.speech_act == SpeechAct.INFORM
        assert msg.priority == MessagePriority.NORMAL
        assert msg.delivered is False
        assert msg.acknowledged is False
        assert msg.thread_id is None
        assert msg.reply_to is None

    def test_all_fields(self):
        msg = DirectMessage(
            sender_type="human",
            sender_id="user-1",
            recipient_type="agent",
            recipient_id="research-agent",
            content="Focus on Germany",
            speech_act=SpeechAct.DIRECTIVE,
            priority=MessagePriority.HIGH,
            workflow_id="wf-1",
            structured_data={"scope": "Germany"},
            attachments=["/workspace/notes.md"],
            thread_id="thread-1",
            reply_to="msg-prev",
            reply_by="2026-03-26T18:00:00+00:00",
        )
        assert msg.sender_type == "human"
        assert msg.speech_act == SpeechAct.DIRECTIVE
        assert msg.attachments == ["/workspace/notes.md"]

    def test_serialization_roundtrip(self):
        msg = DirectMessage(
            sender_id="a",
            recipient_id="b",
            content="test",
            workflow_id="wf-1",
        )
        data = msg.model_dump()
        msg2 = DirectMessage(**data)
        assert msg2.message_id == msg.message_id
        assert msg2.content == "test"


class TestBoardPost:
    def test_defaults(self):
        post = BoardPost(
            author_id="agent-a",
            content="Found something interesting",
        )
        assert post.post_id  # auto-generated
        assert post.section == BoardSection.POST
        assert post.speech_act == SpeechAct.INFORM
        assert post.pinned is False
        assert post.resolved is False

    def test_question_post(self):
        post = BoardPost(
            section=BoardSection.QUESTION,
            author_type="agent",
            author_id="research-agent",
            content="Which GDP source should we use?",
            speech_act=SpeechAct.REQUEST,
        )
        assert post.section == BoardSection.QUESTION

    def test_promoted_post(self):
        post = BoardPost(
            author_id="agent-a",
            content="promoted finding",
            source_message_id="msg-123",
            source_thread_id="thread-456",
        )
        assert post.source_message_id == "msg-123"


class TestAgentStatus:
    def test_defaults(self):
        status = AgentStatus(agent_id="agent-a")
        assert status.state == "pending"
        assert status.agent_name == ""

    def test_running(self):
        status = AgentStatus(
            agent_id="research",
            agent_name="Research Agent",
            role="Macro researcher",
            state="running",
            current_task="task-1",
            progress_summary="70% complete",
        )
        assert status.state == "running"
        assert status.progress_summary == "70% complete"


class TestBoardState:
    def test_empty_board(self):
        state = BoardState(workflow_id="wf-1")
        assert state.version == 0
        assert state.announcements == []
        assert state.team_status == []
        assert state.recent_posts == []

    def test_serialization(self):
        state = BoardState(
            workflow_id="wf-1",
            version=5,
            announcements=[
                BoardPost(author_id="human", content="Focus on Germany")
            ],
        )
        data = state.model_dump()
        state2 = BoardState(**data)
        assert state2.version == 5
        assert len(state2.announcements) == 1


class TestBoardSection:
    def test_all_sections(self):
        assert BoardSection.ANNOUNCEMENT == "announcement"
        assert BoardSection.STATUS == "status"
        assert BoardSection.POST == "post"
        assert BoardSection.DECISION == "decision"
        assert BoardSection.QUESTION == "question"
        assert BoardSection.ALERT == "alert"
