"""Broker-mediated message channels for inter-agent communication."""

from __future__ import annotations

import threading
from collections import defaultdict

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.channel import ChannelConfig, ChannelMessage, ChannelMode
from agentos.schemas.events import Event, EventType


class ChannelRouter:
    """Routes messages between tasks via named channels.

    All messages are logged as events for auditability.
    Channels are scoped to a single workflow execution.
    """

    def __init__(
        self,
        channels: dict[str, ChannelConfig],
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._channels = channels
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._buffers: dict[str, list[ChannelMessage]] = defaultdict(list)
        self._subscribers: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.Lock()

    def register_subscriber(self, channel: str, task_id: str) -> None:
        """Register a task as a subscriber to a channel."""
        if channel not in self._channels:
            raise ValueError(f"Unknown channel: {channel}")
        with self._lock:
            if task_id not in self._subscribers[channel]:
                self._subscribers[channel].append(task_id)

    def publish(self, message: ChannelMessage) -> None:
        """Publish a message to a channel. Emits MESSAGE_SENT event."""
        config = self._channels.get(message.channel)
        if config is None:
            raise ValueError(f"Unknown channel: {message.channel}")

        with self._lock:
            if len(self._buffers[message.channel]) >= config.max_buffer:
                raise BufferError(f"Channel '{message.channel}' buffer full")
            self._buffers[message.channel].append(message)

        self._event_log.append(
            Event(
                event_type=EventType.MESSAGE_SENT,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={
                    "channel": message.channel,
                    "sender_task_id": message.sender_task_id,
                    "sender_agent_id": message.sender_agent_id,
                    "content": message.content,
                },
            )
        )

    def receive(self, channel: str, task_id: str) -> list[ChannelMessage]:
        """Receive pending messages for a task on a channel."""
        config = self._channels.get(channel)
        if config is None:
            raise ValueError(f"Unknown channel: {channel}")

        with self._lock:
            if config.mode == ChannelMode.BROADCAST:
                messages = list(self._buffers[channel])
            else:
                # QUEUE mode — take the first message only
                messages = []
                if self._buffers[channel]:
                    messages.append(self._buffers[channel].pop(0))

        for msg in messages:
            self._event_log.append(
                Event(
                    event_type=EventType.MESSAGE_RECEIVED,
                    workflow_id=self._workflow_id,
                    seq=self._seq.next(),
                    schema_version="0.2",
                    payload={
                        "channel": channel,
                        "receiver_task_id": task_id,
                        "sender_task_id": msg.sender_task_id,
                        "content": msg.content,
                    },
                )
            )
        return messages

    def get_subscribers(self, channel: str) -> list[str]:
        """Return the list of subscriber task IDs for a channel."""
        with self._lock:
            return list(self._subscribers.get(channel, []))

    def buffer_size(self, channel: str) -> int:
        """Return current buffer size for a channel."""
        with self._lock:
            return len(self._buffers.get(channel, []))

    def close_channel(self, channel: str) -> None:
        """Close a channel and emit event."""
        with self._lock:
            self._buffers.pop(channel, None)
            self._subscribers.pop(channel, None)

        self._event_log.append(
            Event(
                event_type=EventType("channel.closed"),
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={"channel": channel},
            )
        )
