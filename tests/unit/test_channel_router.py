"""Tests for the ChannelRouter message channel system."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.channel_router import ChannelRouter
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.channel import ChannelConfig, ChannelMessage, ChannelMode
from agentos.schemas.events import EventType


@pytest.fixture
def channel_configs() -> dict[str, ChannelConfig]:
    return {
        "findings": ChannelConfig(name="findings", mode=ChannelMode.BROADCAST, max_buffer=10),
        "tasks": ChannelConfig(name="tasks", mode=ChannelMode.QUEUE, max_buffer=5),
    }


@pytest.fixture
def router(channel_configs, event_log, seq) -> ChannelRouter:
    return ChannelRouter(
        channels=channel_configs,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )


def _make_msg(channel: str, content: dict | None = None) -> ChannelMessage:
    return ChannelMessage(
        channel=channel,
        sender_task_id="t1",
        sender_agent_id="a1",
        content=content or {"data": "test"},
    )


class TestChannelCreation:
    def test_router_initializes_with_config(self, router, channel_configs):
        assert router._channels == channel_configs

    def test_register_subscriber(self, router):
        router.register_subscriber("findings", "t2")
        assert "t2" in router.get_subscribers("findings")

    def test_register_subscriber_unknown_channel(self, router):
        with pytest.raises(ValueError, match="Unknown channel"):
            router.register_subscriber("nonexistent", "t1")

    def test_register_subscriber_idempotent(self, router):
        router.register_subscriber("findings", "t2")
        router.register_subscriber("findings", "t2")
        assert router.get_subscribers("findings").count("t2") == 1


class TestPublishSubscribe:
    def test_publish_broadcast(self, router):
        msg = _make_msg("findings", {"key": "value"})
        router.publish(msg)
        assert router.buffer_size("findings") == 1

    def test_receive_broadcast_all_get_messages(self, router):
        router.register_subscriber("findings", "t2")
        router.register_subscriber("findings", "t3")
        router.publish(_make_msg("findings", {"item": 1}))
        router.publish(_make_msg("findings", {"item": 2}))

        msgs_t2 = router.receive("findings", "t2")
        msgs_t3 = router.receive("findings", "t3")
        assert len(msgs_t2) == 2
        assert len(msgs_t3) == 2

    def test_receive_queue_round_robin(self, router):
        router.register_subscriber("tasks", "t2")
        router.register_subscriber("tasks", "t3")
        router.publish(_make_msg("tasks", {"item": 1}))
        router.publish(_make_msg("tasks", {"item": 2}))

        msgs_t2 = router.receive("tasks", "t2")
        assert len(msgs_t2) == 1
        assert msgs_t2[0].content == {"item": 1}

        msgs_t3 = router.receive("tasks", "t3")
        assert len(msgs_t3) == 1
        assert msgs_t3[0].content == {"item": 2}

    def test_receive_empty_channel(self, router):
        msgs = router.receive("findings", "t1")
        assert msgs == []

    def test_receive_queue_empty_after_consumed(self, router):
        router.publish(_make_msg("tasks", {"item": 1}))
        router.receive("tasks", "t1")
        msgs = router.receive("tasks", "t1")
        assert msgs == []


class TestBufferOverflow:
    def test_buffer_full_raises(self, router):
        for i in range(5):
            router.publish(_make_msg("tasks", {"i": i}))
        with pytest.raises(BufferError, match="buffer full"):
            router.publish(_make_msg("tasks", {"i": 5}))

    def test_buffer_within_limit(self, router):
        for i in range(10):
            router.publish(_make_msg("findings", {"i": i}))
        assert router.buffer_size("findings") == 10


class TestUnknownChannel:
    def test_publish_unknown_channel(self, router):
        with pytest.raises(ValueError, match="Unknown channel"):
            router.publish(_make_msg("nonexistent"))

    def test_receive_unknown_channel(self, router):
        with pytest.raises(ValueError, match="Unknown channel"):
            router.receive("nonexistent", "t1")


class TestEventLogging:
    def test_message_sent_event(self, router, event_log):
        router.publish(_make_msg("findings", {"key": "val"}))
        events = event_log.query(event_type=EventType.MESSAGE_SENT)
        assert len(events) == 1
        assert events[0].payload["channel"] == "findings"
        assert events[0].payload["sender_task_id"] == "t1"
        assert events[0].payload["content"] == {"key": "val"}
        assert events[0].schema_version == "0.2"

    def test_message_received_event(self, router, event_log):
        router.publish(_make_msg("findings"))
        router.receive("findings", "t2")
        events = event_log.query(event_type=EventType.MESSAGE_RECEIVED)
        assert len(events) == 1
        assert events[0].payload["receiver_task_id"] == "t2"
        assert events[0].payload["sender_task_id"] == "t1"
        assert events[0].schema_version == "0.2"

    def test_channel_closed_event(self, router, event_log):
        router.close_channel("findings")
        events = event_log.query(event_type=EventType.CHANNEL_CLOSED)
        assert len(events) == 1
        assert events[0].payload["channel"] == "findings"


class TestConcurrentPublish:
    def test_concurrent_publish_no_lost_messages(self, router):
        errors = []

        def publish_batch(start: int) -> None:
            try:
                for i in range(3):
                    router.publish(_make_msg("findings", {"i": start + i}))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publish_batch, args=(i * 3,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert router.buffer_size("findings") == 9


class TestCloseChannel:
    def test_close_clears_buffer(self, router):
        router.publish(_make_msg("findings"))
        router.close_channel("findings")
        assert router.buffer_size("findings") == 0

    def test_close_clears_subscribers(self, router):
        router.register_subscriber("findings", "t2")
        router.close_channel("findings")
        assert router.get_subscribers("findings") == []
