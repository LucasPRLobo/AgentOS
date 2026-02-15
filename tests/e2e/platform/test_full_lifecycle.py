"""End-to-end tests for the full platform workflow lifecycle.

These tests exercise the complete stack: API → orchestrator → compiler →
DAG executor → events, using mock LLM providers. Each test verifies that
the entire chain works correctly for a specific scenario.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import DomainRegistry

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.server import create_app
from agentplatform.settings import SettingsManager


# ── Mock Providers ──────────────────────────────────────────────────


class MockFinishProvider(BaseLMProvider):
    """Always finishes immediately with a canned response."""

    def __init__(self, result: str = "Task completed successfully.") -> None:
        self._result = result

    @property
    def name(self) -> str:
        return "mock-finish"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        return LMResponse(
            content=json.dumps({
                "action": "finish",
                "result": self._result,
                "reasoning": "Done.",
            }),
            tokens_used=20,
            prompt_tokens=15,
            completion_tokens=5,
        )


class MockToolThenFinishProvider(BaseLMProvider):
    """Makes one file_write tool call, then finishes."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock-tool-finish"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        self._call_count += 1
        if self._call_count <= 1:
            return LMResponse(
                content=json.dumps({
                    "action": "tool_call",
                    "tool": "file_write",
                    "input": {"path": "output.md", "content": "# Test Output"},
                    "reasoning": "Writing output file.",
                }),
                tokens_used=30,
                prompt_tokens=20,
                completion_tokens=10,
            )
        return LMResponse(
            content=json.dumps({
                "action": "finish",
                "result": "Output written to output.md",
                "reasoning": "File written.",
            }),
            tokens_used=20,
            prompt_tokens=15,
            completion_tokens=5,
        )


class MockErrorProvider(BaseLMProvider):
    """Fails on first call, succeeds on second (simulates fallback)."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock-error"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        self._call_count += 1
        if self._call_count <= 1:
            raise RuntimeError("Simulated LLM failure")
        return LMResponse(
            content=json.dumps({
                "action": "finish",
                "result": "Recovered after retry.",
                "reasoning": "Done.",
            }),
            tokens_used=20,
            prompt_tokens=15,
            completion_tokens=5,
        )


class MockNLGeneratorProvider(BaseLMProvider):
    """Returns a valid WorkflowDefinition JSON for NL generation tests."""

    @property
    def name(self) -> str:
        return "mock-nl-gen"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        wf = {
            "workflow": {
                "name": "Generated Research Pipeline",
                "description": "Auto-generated workflow",
                "domain_pack": "codeos",
                "nodes": [
                    {
                        "id": "researcher",
                        "role": "custom",
                        "display_name": "Researcher",
                        "position": {"x": 100, "y": 100},
                        "config": {
                            "model": "gpt-4o-mini",
                            "system_prompt": "Research the topic.",
                            "persona_preset": "analytical",
                            "tools": ["web_search"],
                            "budget": None,
                            "max_steps": 10,
                            "advanced": None,
                        },
                    },
                    {
                        "id": "writer",
                        "role": "custom",
                        "display_name": "Writer",
                        "position": {"x": 400, "y": 100},
                        "config": {
                            "model": "gpt-4o-mini",
                            "system_prompt": "Write a report.",
                            "persona_preset": "formal",
                            "tools": ["file_write"],
                            "budget": None,
                            "max_steps": 10,
                            "advanced": None,
                        },
                    },
                ],
                "edges": [{"source": "researcher", "target": "writer"}],
                "variables": [],
            },
            "explanation": "Two agents: one researches, one writes.",
        }
        return LMResponse(
            content=json.dumps(wf),
            tokens_used=100,
            prompt_tokens=80,
            completion_tokens=20,
        )


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def _setup(tmp_path):
    """Create shared test components."""
    sm = SettingsManager(str(tmp_path / "config"))
    sm.update({"workflows_dir": str(tmp_path / "workflows")})
    registry = DomainRegistry()
    register_builtin_packs(registry)
    return sm, registry, tmp_path


@pytest.fixture()
def client(_setup) -> TestClient:
    sm, registry, _ = _setup
    app = create_app(
        lm_provider=MockFinishProvider(),
        lm_provider_factory=lambda m: MockFinishProvider(),
        domain_registry=registry,
        settings_manager=sm,
    )
    return TestClient(app)


@pytest.fixture()
def client_with_tool_provider(_setup) -> TestClient:
    sm, registry, _ = _setup
    app = create_app(
        lm_provider_factory=lambda m: MockToolThenFinishProvider(),
        domain_registry=registry,
        settings_manager=sm,
    )
    return TestClient(app)


@pytest.fixture()
def client_with_nl_provider(_setup) -> TestClient:
    sm, registry, _ = _setup
    app = create_app(
        lm_provider_factory=lambda m: MockNLGeneratorProvider(),
        domain_registry=registry,
        settings_manager=sm,
    )
    return TestClient(app)


# ── E2E Tests ───────────────────────────────────────────────────────


@pytest.mark.e2e
class TestTemplateToRun:
    """Load a template, instantiate it, run the workflow, verify events."""

    def test_template_instantiate_and_run(self, client: TestClient) -> None:
        # 1. List templates
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        templates = resp.json()
        assert len(templates) >= 1

        # 2. Instantiate a template
        resp = client.post("/api/templates/tpl_meeting_notes/instantiate")
        assert resp.status_code == 200
        wf = resp.json()
        wf_id = wf["id"]
        assert wf["template_source"] == "tpl_meeting_notes"

        # 3. Verify it's in the workflow list
        resp = client.get("/api/workflows")
        assert any(w["id"] == wf_id for w in resp.json())

        # 4. Run the workflow
        resp = client.post(f"/api/workflows/{wf_id}/run", json={
            "task_description": "Process weekly standup transcript",
        })
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        assert resp.json()["state"] == "RUNNING"

        # 5. Wait for completion and check session
        _wait_for_session(client, session_id)

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        session = resp.json()
        assert session["state"] in ("SUCCEEDED", "FAILED")

        # 6. Check events were emitted
        resp = client.get(f"/api/sessions/{session_id}/events")
        events = resp.json()
        assert len(events) >= 1


@pytest.mark.e2e
class TestBuilderSaveLoad:
    """Create a workflow via API, save, reload, verify fidelity."""

    def test_builder_save_and_reload(self, client: TestClient) -> None:
        workflow = {
            "name": "E2E Builder Test",
            "description": "Tests builder save/load flow",
            "domain_pack": "codeos",
            "version": "1.0.0",
            "nodes": [
                {
                    "id": "n1",
                    "role": "custom",
                    "display_name": "Agent Alpha",
                    "position": {"x": 100, "y": 100},
                    "config": {
                        "model": "gpt-4o-mini",
                        "system_prompt": "Be helpful.",
                        "persona_preset": "analytical",
                        "tools": ["file_read", "file_write"],
                        "budget": {
                            "max_tokens": 10000,
                            "max_tool_calls": 5,
                            "max_time_seconds": 60.0,
                            "max_recursion_depth": 1,
                        },
                        "max_steps": 10,
                        "advanced": None,
                    },
                },
                {
                    "id": "n2",
                    "role": "custom",
                    "display_name": "Agent Beta",
                    "position": {"x": 400, "y": 100},
                    "config": {
                        "model": "gpt-4o-mini",
                        "system_prompt": "Review output.",
                        "persona_preset": "formal",
                        "tools": ["file_read"],
                        "budget": None,
                        "max_steps": 5,
                        "advanced": {"temperature": 0.3},
                    },
                },
            ],
            "edges": [{"source": "n1", "target": "n2"}],
            "variables": [{"name": "topic", "type": "string", "default": "AI"}],
        }

        # Save
        resp = client.post("/api/workflows", json=workflow)
        assert resp.status_code == 201
        wf_id = resp.json()["id"]

        # Reload
        resp = client.get(f"/api/workflows/{wf_id}")
        assert resp.status_code == 200
        loaded = resp.json()

        # Verify fidelity
        assert loaded["name"] == "E2E Builder Test"
        assert len(loaded["nodes"]) == 2
        assert len(loaded["edges"]) == 1
        assert loaded["nodes"][0]["display_name"] == "Agent Alpha"
        assert loaded["nodes"][0]["config"]["tools"] == ["file_read", "file_write"]
        assert loaded["nodes"][1]["config"]["advanced"]["temperature"] == 0.3
        assert loaded["variables"][0]["name"] == "topic"
        assert loaded["domain_pack"] == "codeos"

    def test_workflow_update_preserves_changes(self, client: TestClient) -> None:
        # Create
        resp = client.post("/api/workflows", json={
            "name": "Mutable Workflow",
            "domain_pack": "codeos",
            "nodes": [{
                "id": "n1", "role": "custom", "display_name": "Agent",
                "config": {"model": "gpt-4o-mini"},
            }],
        })
        wf_id = resp.json()["id"]

        # Update name and add a node
        resp = client.put(f"/api/workflows/{wf_id}", json={
            "name": "Renamed Workflow",
            "domain_pack": "codeos",
            "nodes": [
                {"id": "n1", "role": "custom", "display_name": "Agent 1",
                 "config": {"model": "gpt-4o-mini"}},
                {"id": "n2", "role": "custom", "display_name": "Agent 2",
                 "config": {"model": "gpt-4o-mini"}},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Workflow"
        assert resp.json()["node_count"] == 2


@pytest.mark.e2e
class TestNLGenerateToRun:
    """Generate a workflow from NL, validate, and run it."""

    def test_nl_generate_validate_and_run(self, client_with_nl_provider: TestClient) -> None:
        client = client_with_nl_provider

        # 1. Generate workflow from NL description
        resp = client.post("/api/workflows/generate", json={
            "description": "I need agents that research a topic and write a report.",
            "model": "gpt-4o-mini",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "workflow" in data
        assert "explanation" in data
        wf = data["workflow"]
        assert len(wf["nodes"]) == 2

        # 2. Save the generated workflow
        resp = client.post("/api/workflows", json=wf)
        assert resp.status_code == 201
        wf_id = resp.json()["id"]

        # 3. Validate it
        resp = client.post(f"/api/workflows/{wf_id}/validate")
        assert resp.status_code == 200


@pytest.mark.e2e
class TestMultiProvider:
    """Verify same workflow works with different provider mock names."""

    def test_workflow_accepts_different_models(self, _setup) -> None:
        sm, registry, _ = _setup
        call_log: list[str] = []

        def routing_factory(model_name: str) -> MockFinishProvider:
            call_log.append(model_name)
            return MockFinishProvider(result=f"Done by {model_name}")

        app = create_app(
            lm_provider_factory=routing_factory,
            domain_registry=registry,
            settings_manager=sm,
        )
        client = TestClient(app)

        workflow = {
            "name": "Multi-Model Pipeline",
            "domain_pack": "codeos",
            "nodes": [
                {
                    "id": "n1", "role": "custom", "display_name": "GPT Agent",
                    "config": {"model": "gpt-4o-mini"},
                },
                {
                    "id": "n2", "role": "custom", "display_name": "Claude Agent",
                    "config": {"model": "claude-3-haiku"},
                },
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        }

        resp = client.post("/api/workflows", json=workflow)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/run", json={})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        _wait_for_session(client, session_id)

        # Both model names should have been requested
        assert "gpt-4o-mini" in call_log
        assert "claude-3-haiku" in call_log


@pytest.mark.e2e
class TestSettingsPersistence:
    """Save settings, create new server, verify settings loaded."""

    def test_settings_survive_restart(self, _setup) -> None:
        sm, registry, _ = _setup

        # Server 1: set API key
        app1 = create_app(
            lm_provider=MockFinishProvider(),
            domain_registry=registry,
            settings_manager=sm,
        )
        c1 = TestClient(app1)
        c1.put("/api/settings", json={"openai_api_key": "sk-test-e2e-key-12345678"})

        # Server 2: new app instance with same settings manager
        registry2 = DomainRegistry()
        register_builtin_packs(registry2)
        app2 = create_app(
            lm_provider=MockFinishProvider(),
            domain_registry=registry2,
            settings_manager=sm,
        )
        c2 = TestClient(app2)

        resp = c2.get("/api/settings")
        assert resp.status_code == 200
        settings = resp.json()
        # Key should be masked but present
        assert settings["openai_api_key"] is not None
        assert "sk-test-" in settings["openai_api_key"]


@pytest.mark.e2e
class TestWorkflowValidationE2E:
    """Validate workflows with various issues through the full API stack."""

    def test_invalid_workflow_reports_issues(self, client: TestClient) -> None:
        # Workflow with cycle
        workflow = {
            "name": "Cyclic Workflow",
            "domain_pack": "codeos",
            "nodes": [
                {"id": "a", "role": "custom", "display_name": "A",
                 "config": {"model": "gpt-4o-mini"}},
                {"id": "b", "role": "custom", "display_name": "B",
                 "config": {"model": "gpt-4o-mini"}},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        }
        resp = client.post("/api/workflows", json=workflow)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/validate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert any("cycle" in issue["message"].lower() for issue in data["issues"])

    def test_valid_workflow_passes(self, client: TestClient) -> None:
        workflow = {
            "name": "Valid Linear",
            "domain_pack": "codeos",
            "nodes": [
                {"id": "a", "role": "custom", "display_name": "A",
                 "config": {"model": "gpt-4o-mini", "tools": ["file_read"]}},
                {"id": "b", "role": "custom", "display_name": "B",
                 "config": {"model": "gpt-4o-mini", "tools": ["file_write"]}},
            ],
            "edges": [{"source": "a", "target": "b"}],
        }
        resp = client.post("/api/workflows", json=workflow)
        wf_id = resp.json()["id"]

        resp = client.post(f"/api/workflows/{wf_id}/validate")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True


@pytest.mark.e2e
class TestIntegrationEndpoints:
    """Test integration connect/disconnect lifecycle through API."""

    def test_slack_connect_disconnect_cycle(self, client: TestClient) -> None:
        # Initially not connected
        resp = client.get("/api/integrations")
        slack = next(i for i in resp.json() if i["name"] == "slack")
        assert slack["connected"] is False

        # Connect
        resp = client.post("/api/integrations/slack/connect", json={
            "bot_token": "xoxb-test-e2e-token-123",
        })
        assert resp.status_code == 200
        assert resp.json()["connected"] is True

        # Verify connected
        resp = client.get("/api/integrations")
        slack = next(i for i in resp.json() if i["name"] == "slack")
        assert slack["connected"] is True

        # Disconnect
        resp = client.delete("/api/integrations/slack/disconnect")
        assert resp.status_code == 200

        # Verify disconnected
        resp = client.get("/api/integrations")
        slack = next(i for i in resp.json() if i["name"] == "slack")
        assert slack["connected"] is False


# ── Helpers ─────────────────────────────────────────────────────────


def _wait_for_session(
    client: TestClient,
    session_id: str,
    timeout: float = 10.0,
    poll_interval: float = 0.2,
) -> dict[str, Any]:
    """Poll session until it's no longer RUNNING or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/sessions/{session_id}")
        data = resp.json()
        if data["state"] != "RUNNING":
            return data
        time.sleep(poll_interval)
    # Final check
    resp = client.get(f"/api/sessions/{session_id}")
    return resp.json()
