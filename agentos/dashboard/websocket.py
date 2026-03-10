"""WebSocket event streaming for the dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agentos.dashboard.serializers import event_to_dict, snapshot_to_dict
from agentos.kernel.event_log import EventLog
from agentos.kernel.replayer import WorkflowReplayer
from agentos.schemas.events import EventType

logger = logging.getLogger(__name__)

# Polling interval for new events (seconds).
POLL_INTERVAL = 0.5


async def event_stream(websocket: Any, event_log: EventLog) -> None:
    """Handle a WebSocket connection for live event streaming.

    Protocol:
        Client -> Server: {"type": "subscribe", "workflow_id": "...", "since_seq": 0}
        Server -> Client: {"type": "snapshot", "data": {...}}  (once, on subscribe)
        Server -> Client: {"type": "event", ...event fields...} (pushed as they appear)
    """
    try:
        # Wait for subscription message
        raw = await websocket.receive_text()
        msg = json.loads(raw)

        if msg.get("type") != "subscribe":
            await websocket.send_json({"type": "error", "message": "Expected subscribe message"})
            return

        workflow_id = msg.get("workflow_id", "")
        since_seq = msg.get("since_seq", 0)

        if not workflow_id:
            await websocket.send_json({"type": "error", "message": "workflow_id required"})
            return

        # Send initial snapshot
        replayer = WorkflowReplayer(event_log)
        snapshot = replayer.replay(workflow_id)
        await websocket.send_json({
            "type": "snapshot",
            "data": snapshot_to_dict(snapshot),
        })

        # Track the last sequence we've sent
        last_seq = snapshot.events[-1].seq if snapshot.events else since_seq

        # Poll for new events
        while True:
            await asyncio.sleep(POLL_INTERVAL)

            new_events = event_log.query(
                workflow_id=workflow_id,
                since_seq=last_seq + 1,
            )

            for event in new_events:
                await websocket.send_json({
                    "type": "event",
                    **event_to_dict(event),
                })
                last_seq = event.seq

    except Exception:
        # WebSocket disconnected or other error — just return
        logger.debug("WebSocket connection closed", exc_info=True)
