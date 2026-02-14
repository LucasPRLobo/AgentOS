"""WebSocket event streamer — pushes new events to connected clients."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from agentplatform.orchestrator import SessionOrchestrator, SessionState


class EventStreamer:
    """Streams events from an EventLog to WebSocket clients.

    Polls the event log at a configurable interval and pushes any new
    events (after the client's last-seen sequence number) as JSON.
    """

    def __init__(self, *, poll_interval: float = 0.1) -> None:
        self._poll_interval = poll_interval

    async def stream(
        self,
        websocket: WebSocket,
        orchestrator: "SessionOrchestrator",
        session_id: str,
    ) -> None:
        """Push new events as JSON to the WebSocket client.

        Runs until the session is in a terminal state and no new events
        are available, or until the client disconnects.
        """
        last_seq = -1
        terminal_states = {"SUCCEEDED", "FAILED", "STOPPED"}
        idle_count = 0
        max_idle = 50  # Stop after ~5 seconds of no new events in terminal state

        while True:
            try:
                events = orchestrator.get_session_events(
                    session_id, after_seq=last_seq + 1
                )
            except KeyError:
                break

            if events:
                idle_count = 0
                for event in events:
                    payload = {
                        "run_id": event.run_id,
                        "seq": event.seq,
                        "timestamp": event.timestamp.isoformat(),
                        "event_type": event.event_type.value,
                        "payload": event.payload,
                    }
                    await websocket.send_text(json.dumps(payload))
                    if event.seq > last_seq:
                        last_seq = event.seq
            else:
                idle_count += 1

            # Check if session is done
            try:
                state = orchestrator.get_session_state(session_id)
                if state.value in terminal_states and idle_count >= max_idle:
                    break
            except KeyError:
                break

            await asyncio.sleep(self._poll_interval)
