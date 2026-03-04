"""Integration tests for channel-aware workflow execution."""

from __future__ import annotations

import pytest

from agentos.kernel.channel_router import ChannelRouter
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.channel import ChannelConfig, ChannelMode
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


class TestChannelWorkflowIntegration:
    """Test channels working within a workflow context."""

    def test_channel_yaml_parsing(self):
        """Workflow YAML with channels section parses correctly."""
        wf = WorkflowDefinition(
            name="channel_test",
            channels={
                "findings": ChannelConfig(name="findings", mode=ChannelMode.BROADCAST),
                "tasks": ChannelConfig(name="tasks", mode=ChannelMode.QUEUE, max_buffer=50),
            },
            tasks={
                "research": TaskConfig(
                    name="research",
                    agent="researcher",
                    description="Research and publish findings",
                    publishes_to=["findings"],
                ),
                "analyze": TaskConfig(
                    name="analyze",
                    agent="analyst",
                    description="Analyze findings",
                    subscribes_to=["findings"],
                    depends_on=["research"],
                ),
            },
        )
        assert "findings" in wf.channels
        assert wf.channels["findings"].mode == ChannelMode.BROADCAST
        assert wf.tasks["research"].publishes_to == ["findings"]
        assert wf.tasks["analyze"].subscribes_to == ["findings"]

    def test_channel_backward_compat(self):
        """V1.5 workflows without channels still work."""
        wf = WorkflowDefinition(
            name="legacy_workflow",
            tasks={
                "task_a": TaskConfig(name="task_a", description="Simple task"),
            },
        )
        assert wf.channels == {}
        assert wf.tasks["task_a"].publishes_to == []
        assert wf.tasks["task_a"].subscribes_to == []

    def test_channel_router_with_workflow(self):
        """ChannelRouter integrates with workflow channel config."""
        wf = WorkflowDefinition(
            name="test",
            channels={
                "data": ChannelConfig(name="data", mode=ChannelMode.BROADCAST),
            },
        )
        event_log = SQLiteEventLog(":memory:")
        seq = SeqCounter()

        router = ChannelRouter(
            channels=wf.channels,
            event_log=event_log,
            seq=seq,
            workflow_id="wf-1",
        )
        router.register_subscriber("data", "consumer_task")

        from agentos.schemas.channel import ChannelMessage

        router.publish(
            ChannelMessage(
                channel="data",
                sender_task_id="producer_task",
                sender_agent_id="agent_a",
                content={"result": "42"},
            )
        )

        msgs = router.receive("data", "consumer_task")
        assert len(msgs) == 1
        assert msgs[0].content == {"result": "42"}

        sent_events = event_log.query(event_type=EventType.MESSAGE_SENT)
        recv_events = event_log.query(event_type=EventType.MESSAGE_RECEIVED)
        assert len(sent_events) == 1
        assert len(recv_events) == 1

    def test_multiple_channels_workflow(self):
        """Workflow with multiple channels routes correctly."""
        event_log = SQLiteEventLog(":memory:")
        seq = SeqCounter()

        channels = {
            "research": ChannelConfig(name="research", mode=ChannelMode.BROADCAST),
            "code": ChannelConfig(name="code", mode=ChannelMode.QUEUE),
        }
        router = ChannelRouter(channels=channels, event_log=event_log, seq=seq, workflow_id="wf-1")
        router.register_subscriber("research", "analyst")
        router.register_subscriber("code", "reviewer")

        from agentos.schemas.channel import ChannelMessage

        router.publish(ChannelMessage(
            channel="research", sender_task_id="researcher", sender_agent_id="a1",
            content={"finding": "interest rates rising"},
        ))
        router.publish(ChannelMessage(
            channel="code", sender_task_id="developer", sender_agent_id="a2",
            content={"file": "main.py", "changes": 42},
        ))

        research_msgs = router.receive("research", "analyst")
        code_msgs = router.receive("code", "reviewer")
        assert len(research_msgs) == 1
        assert research_msgs[0].content["finding"] == "interest rates rising"
        assert len(code_msgs) == 1
        assert code_msgs[0].content["file"] == "main.py"

    def test_workflow_definition_serialization_with_channels(self):
        """WorkflowDefinition with channels round-trips through JSON."""
        wf = WorkflowDefinition(
            name="round_trip_test",
            channels={
                "events": ChannelConfig(name="events", mode=ChannelMode.BROADCAST, max_buffer=50),
            },
            tasks={
                "producer": TaskConfig(name="producer", publishes_to=["events"]),
                "consumer": TaskConfig(name="consumer", subscribes_to=["events"]),
            },
        )
        data = wf.model_dump(mode="json")
        restored = WorkflowDefinition.model_validate(data)
        assert restored.channels["events"].mode == ChannelMode.BROADCAST
        assert restored.channels["events"].max_buffer == 50
        assert restored.tasks["producer"].publishes_to == ["events"]
        assert restored.tasks["consumer"].subscribes_to == ["events"]
