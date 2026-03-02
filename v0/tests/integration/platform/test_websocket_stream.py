"""Integration tests for WebSocket event streaming."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import DomainRegistry

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.event_stream import EventStreamer
from agentplatform.server import create_app


class _MockProvider(BaseLMProvider):
    @property
    def name(self) -> str:
        return "mock"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        content = '{"action": "finish", "result": "done", "reasoning": "test"}'
        return LMResponse(
            content=content, tokens_used=10,
            prompt_tokens=5, completion_tokens=5,
        )


@pytest.fixture()
def client(tmp_path: object) -> TestClient:
    registry = DomainRegistry()
    register_builtin_packs(registry)
    # Use a fast-exiting streamer for tests (0.5s idle timeout)
    app = create_app(lm_provider=_MockProvider(), domain_registry=registry)
    app.state.streamer = EventStreamer(poll_interval=0.05)
    return TestClient(app)


def _create_and_start(client: TestClient, workspace_root: str) -> str:
    """Helper: create and start a session, return session_id."""
    resp = client.post("/api/sessions", json={
        "domain_pack": "labos",
        "workflow": "multi_agent_research",
        "agents": [{"role": "planner", "model": "mock"}],
        "workspace_root": workspace_root,
    })
    sid = resp.json()["session_id"]
    client.post(f"/api/sessions/{sid}/start")
    return sid


@pytest.mark.integration
class TestWebSocketStream:
    def test_connect_and_receive_event(self, client: TestClient, tmp_path: object) -> None:
        sid = _create_and_start(client, str(tmp_path))
        time.sleep(1.0)

        with client.websocket_connect(f"/ws/sessions/{sid}/events") as ws:
            data = ws.receive_text()
            event = json.loads(data)
            assert "event_type" in event
            assert "seq" in event
            assert "run_id" in event

    def test_events_have_correct_structure(self, client: TestClient, tmp_path: object) -> None:
        sid = _create_and_start(client, str(tmp_path))
        time.sleep(2.0)

        # Use REST endpoint to know how many events to expect
        rest_events = client.get(f"/api/sessions/{sid}/events").json()
        expected_count = len(rest_events)
        assert expected_count > 0

        # Collect all events via WebSocket (we know exactly how many)
        ws_events: list[dict] = []
        with client.websocket_connect(f"/ws/sessions/{sid}/events") as ws:
            for _ in range(expected_count):
                data = ws.receive_text()
                ws_events.append(json.loads(data))

        # All WS events should match REST events count
        assert len(ws_events) == expected_count

        # First event should be SessionStarted
        assert ws_events[0]["event_type"] == "SessionStarted"

    def test_unknown_session_closes(self, client: TestClient) -> None:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/sessions/nonexistent/events") as ws:
                ws.receive_text()
