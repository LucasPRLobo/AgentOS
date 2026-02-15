"""Integration tests for session API endpoints."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import DomainRegistry

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.server import create_app


class _MockProvider(BaseLMProvider):
    """Mock provider that immediately finishes."""

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
    app = create_app(lm_provider=_MockProvider(), domain_registry=registry)
    return TestClient(app)


@pytest.fixture()
def workspace_root(tmp_path: object) -> str:
    return str(tmp_path)


@pytest.mark.integration
class TestCreateSession:
    def test_create_returns_201(self, client: TestClient, workspace_root: str) -> None:
        resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert data["state"] == "CREATED"
        assert data["domain_pack"] == "labos"

    def test_create_invalid_pack_422(self, client: TestClient, workspace_root: str) -> None:
        resp = client.post("/api/sessions", json={
            "domain_pack": "nonexistent",
            "workflow": "test",
            "agents": [],
            "workspace_root": workspace_root,
        })
        assert resp.status_code == 422

    def test_create_invalid_role_422(self, client: TestClient, workspace_root: str) -> None:
        resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "nonexistent_role", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        assert resp.status_code == 422


@pytest.mark.integration
class TestListSessions:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, client: TestClient, workspace_root: str) -> None:
        client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


@pytest.mark.integration
class TestSessionLifecycle:
    def test_start_session(self, client: TestClient, workspace_root: str) -> None:
        create_resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        sid = create_resp.json()["session_id"]
        start_resp = client.post(f"/api/sessions/{sid}/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "started"

    def test_get_session_events(self, client: TestClient, workspace_root: str) -> None:
        create_resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        sid = create_resp.json()["session_id"]
        client.post(f"/api/sessions/{sid}/start")
        time.sleep(2.0)

        events_resp = client.get(f"/api/sessions/{sid}/events")
        assert events_resp.status_code == 200
        events = events_resp.json()
        assert len(events) > 0
        assert events[0]["event_type"] == "SessionStarted"

    def test_stop_session(self, client: TestClient, workspace_root: str) -> None:
        create_resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        sid = create_resp.json()["session_id"]
        client.post(f"/api/sessions/{sid}/start")
        stop_resp = client.post(f"/api/sessions/{sid}/stop")
        assert stop_resp.status_code == 200

    def test_unknown_session_404(self, client: TestClient) -> None:
        resp = client.get("/api/sessions/nonexistent-id")
        assert resp.status_code == 404

    def test_events_with_after_seq(self, client: TestClient, workspace_root: str) -> None:
        create_resp = client.post("/api/sessions", json={
            "domain_pack": "labos",
            "workflow": "multi_agent_research",
            "agents": [{"role": "planner", "model": "mock"}],
            "workspace_root": workspace_root,
        })
        sid = create_resp.json()["session_id"]
        client.post(f"/api/sessions/{sid}/start")
        time.sleep(2.0)

        all_events = client.get(f"/api/sessions/{sid}/events").json()
        if len(all_events) > 1:
            filtered = client.get(f"/api/sessions/{sid}/events?after_seq=1").json()
            assert len(filtered) < len(all_events)
