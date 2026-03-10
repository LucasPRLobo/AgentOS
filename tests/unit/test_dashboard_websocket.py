"""Tests for agentos.dashboard WebSocket event streaming."""

from __future__ import annotations

import json

import pytest

from agentos.dashboard.app import create_app
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


def _seed_workflow(db_path: str, workflow_id: str = "ws-test-01") -> SQLiteEventLog:
    """Seed a database with events for WebSocket testing."""
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()

    events = [
        Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"workflow_name": "ws-test", "task_count": 1},
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task1", "from_state": "pending", "to_state": "running"},
        ),
        Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"task_id": "task1", "from_state": "running", "to_state": "succeeded"},
        ),
        Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            seq=seq.next(),
            payload={"status": "succeeded"},
        ),
    ]

    for event in events:
        event_log.append(event)

    return event_log


@pytest.fixture
def ws_app(tmp_path):
    db_path = str(tmp_path / "ws.db")
    _seed_workflow(db_path)
    app = create_app(db_path)
    return TestClient(app)


class TestWebSocketConnection:
    def test_subscribe_receives_snapshot(self, ws_app):
        with ws_app.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "workflow_id": "ws-test-01", "since_seq": 0})
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["data"]["workflow_id"] == "ws-test-01"
            assert msg["data"]["status"] == "succeeded"

    def test_subscribe_without_workflow_id(self, ws_app):
        with ws_app.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "workflow_id": ""})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_non_subscribe_message(self, ws_app):
        with ws_app.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_snapshot_has_events(self, ws_app):
        with ws_app.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "workflow_id": "ws-test-01", "since_seq": 0})
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert len(msg["data"]["events"]) == 4

    def test_snapshot_has_tasks(self, ws_app):
        with ws_app.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "workflow_id": "ws-test-01", "since_seq": 0})
            msg = ws.receive_json()
            assert "task1" in msg["data"]["tasks"]
