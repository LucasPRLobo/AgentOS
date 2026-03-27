"""Tests for agentos.comms.message_bus — direct messaging infrastructure."""

import threading

import pytest

from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import DirectMessage, MessagePriority, SpeechAct
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


@pytest.fixture
def bus(tmp_path):
    event_log = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return MessageBus(event_log, seq, "wf-test")


def _msg(sender="agent-a", recipient="agent-b", content="hello", **kw):
    return DirectMessage(
        sender_id=sender,
        recipient_id=recipient,
        content=content,
        workflow_id="wf-test",
        **kw,
    )


class TestSend:
    def test_send_returns_message_id(self, bus):
        mid = bus.send(_msg())
        assert mid
        assert isinstance(mid, str)

    def test_send_logs_event(self, bus):
        bus.send(_msg(content="test event"))
        events = bus._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.DIRECT_MESSAGE_SENT,
        )
        assert len(events) == 1
        assert events[0].payload["content_preview"] == "test event"

    def test_send_multiple(self, bus):
        bus.send(_msg(content="one"))
        bus.send(_msg(content="two"))
        assert bus.get_pending_count("agent-b") == 2


class TestReceive:
    def test_receive_returns_pending(self, bus):
        bus.send(_msg(content="first"))
        bus.send(_msg(content="second"))
        msgs = bus.receive("agent-b")
        assert len(msgs) == 2
        assert msgs[0].content == "first"
        assert msgs[1].content == "second"

    def test_receive_marks_delivered(self, bus):
        bus.send(_msg())
        msgs = bus.receive("agent-b")
        assert msgs[0].delivered is True
        assert msgs[0].delivered_at is not None

    def test_receive_no_double_delivery(self, bus):
        bus.send(_msg())
        bus.receive("agent-b")
        msgs2 = bus.receive("agent-b")
        assert len(msgs2) == 0

    def test_receive_without_marking(self, bus):
        bus.send(_msg())
        msgs = bus.receive("agent-b", mark_delivered=False)
        assert len(msgs) == 1
        assert msgs[0].delivered is False
        # Should still be receivable
        msgs2 = bus.receive("agent-b")
        assert len(msgs2) == 1

    def test_receive_priority_filter(self, bus):
        bus.send(_msg(content="low", priority=MessagePriority.LOW))
        bus.send(_msg(content="high", priority=MessagePriority.HIGH))
        msgs = bus.receive("agent-b", priority_min=MessagePriority.HIGH)
        assert len(msgs) == 1
        assert msgs[0].content == "high"

    def test_receive_logs_delivery_events(self, bus):
        bus.send(_msg())
        bus.receive("agent-b")
        events = bus._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.DIRECT_MESSAGE_DELIVERED,
        )
        assert len(events) == 1

    def test_pending_count(self, bus):
        assert bus.get_pending_count("agent-b") == 0
        bus.send(_msg())
        assert bus.get_pending_count("agent-b") == 1
        bus.receive("agent-b")
        assert bus.get_pending_count("agent-b") == 0


class TestReply:
    def test_reply_creates_thread(self, bus):
        mid = bus.send(_msg(sender="agent-a", recipient="agent-b", content="question"))
        reply_id = bus.reply(
            reply_to_id=mid,
            sender_type="agent",
            sender_id="agent-b",
            content="answer",
        )
        # Both messages should be in the same thread
        original = bus._messages[mid]
        reply = bus._messages[reply_id]
        assert original.thread_id is not None
        assert reply.thread_id == original.thread_id
        assert reply.reply_to == mid

    def test_reply_uses_existing_thread(self, bus):
        mid1 = bus.send(_msg(sender="a", recipient="b", content="q1"))
        bus.reply(reply_to_id=mid1, sender_type="agent", sender_id="b", content="a1")
        thread_id = bus._messages[mid1].thread_id

        # Reply to original again
        mid3 = bus.reply(reply_to_id=mid1, sender_type="agent", sender_id="b", content="a2")
        assert bus._messages[mid3].thread_id == thread_id

    def test_reply_routes_to_original_sender(self, bus):
        mid = bus.send(_msg(sender="agent-a", recipient="agent-b"))
        bus.reply(reply_to_id=mid, sender_type="agent", sender_id="agent-b", content="reply")
        # The reply should be in agent-a's inbox
        msgs = bus.receive("agent-a")
        assert len(msgs) == 1
        assert msgs[0].content == "reply"

    def test_reply_to_unknown_raises(self, bus):
        with pytest.raises(ValueError, match="Unknown message"):
            bus.reply(reply_to_id="nonexistent", sender_type="agent", sender_id="b", content="x")

    def test_thread_created_event(self, bus):
        mid = bus.send(_msg())
        bus.reply(reply_to_id=mid, sender_type="agent", sender_id="agent-b", content="r")
        events = bus._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.THREAD_CREATED,
        )
        assert len(events) == 1


class TestGetThread:
    def test_get_thread(self, bus):
        mid1 = bus.send(_msg(sender="a", recipient="b", content="q"))
        bus.reply(reply_to_id=mid1, sender_type="agent", sender_id="b", content="a")
        thread_id = bus._messages[mid1].thread_id
        thread = bus.get_thread(thread_id)
        assert len(thread) == 2
        assert thread[0].content == "q"
        assert thread[1].content == "a"

    def test_get_nonexistent_thread(self, bus):
        thread = bus.get_thread("nonexistent")
        assert thread == []


class TestAcknowledge:
    def test_acknowledge(self, bus):
        mid = bus.send(_msg())
        bus.receive("agent-b")
        bus.acknowledge(mid)
        msg = bus._messages[mid]
        assert msg.acknowledged is True
        assert msg.acknowledged_at is not None

    def test_acknowledge_unknown_raises(self, bus):
        with pytest.raises(ValueError, match="Unknown message"):
            bus.acknowledge("nonexistent")

    def test_acknowledge_event(self, bus):
        mid = bus.send(_msg())
        bus.acknowledge(mid)
        events = bus._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.DIRECT_MESSAGE_ACKNOWLEDGED,
        )
        assert len(events) == 1


class TestPromoteToBoard:
    def test_promote(self, bus):
        mid = bus.send(_msg(content="important finding"))

        # Mock board manager
        class MockBoard:
            def __init__(self):
                self.posted = None
            def post(self, p):
                self.posted = p
                return "post-123"

        mock = MockBoard()
        post_id = bus.promote_to_board(mid, mock, section="decision")
        assert post_id == "post-123"
        assert mock.posted.content == "important finding"
        assert mock.posted.source_message_id == mid

    def test_promote_event(self, bus):
        mid = bus.send(_msg())

        class MockBoard:
            def post(self, p):
                return "p1"

        bus.promote_to_board(mid, MockBoard())
        events = bus._event_log.query(
            workflow_id="wf-test",
            event_type=EventType.MESSAGE_PROMOTED_TO_BOARD,
        )
        assert len(events) == 1


class TestAudit:
    def test_get_all_messages(self, bus):
        bus.send(_msg(content="one"))
        bus.send(_msg(content="two"))
        all_msgs = bus.get_all_messages()
        assert len(all_msgs) == 2

    def test_get_messages_for_participant(self, bus):
        bus.send(_msg(sender="a", recipient="b", content="from a"))
        bus.send(_msg(sender="b", recipient="a", content="from b"))
        bus.send(_msg(sender="c", recipient="d", content="unrelated"))
        msgs = bus.get_messages_for_participant("a")
        assert len(msgs) == 2


class TestThreadSafety:
    def test_concurrent_sends(self, bus):
        errors = []

        def send_batch(n):
            try:
                for i in range(n):
                    bus.send(_msg(content=f"msg-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=send_batch, args=(20,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert bus.get_pending_count("agent-b") == 100
