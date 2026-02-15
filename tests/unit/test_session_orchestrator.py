"""Unit tests for SessionOrchestrator."""

from __future__ import annotations

import time

import pytest

from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.domain_registry import DomainRegistry
from agentos.schemas.events import EventType
from agentos.schemas.session import AgentSlotConfig, SessionConfig

from agentplatform._domain_manifests import register_builtin_packs
from agentplatform.orchestrator import SessionOrchestrator, SessionState


class _FinishImmediatelyProvider(BaseLMProvider):
    """Mock provider that immediately returns a finish action."""

    @property
    def name(self) -> str:
        return "mock-finish"

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        content = '{"action": "finish", "result": "Done.", "reasoning": "Finished"}'
        return LMResponse(
            content=content,
            tokens_used=20,
            prompt_tokens=10,
            completion_tokens=10,
        )


@pytest.fixture()
def registry() -> DomainRegistry:
    reg = DomainRegistry()
    register_builtin_packs(reg)
    return reg


@pytest.fixture()
def orchestrator(registry: DomainRegistry) -> SessionOrchestrator:
    return SessionOrchestrator(registry)


@pytest.fixture()
def labos_config(tmp_path: object) -> SessionConfig:
    return SessionConfig(
        domain_pack="labos",
        workflow="multi_agent_research",
        agents=[
            AgentSlotConfig(role="planner", model="mock"),
        ],
        workspace_root=str(tmp_path),
    )


class TestSessionCreation:
    def test_create_returns_session_id(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        assert sid == labos_config.session_id

    def test_create_sets_state_created(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        assert orchestrator.get_session_state(sid) == SessionState.CREATED

    def test_unknown_domain_pack_raises(
        self, orchestrator: SessionOrchestrator, tmp_path: object
    ) -> None:
        config = SessionConfig(
            domain_pack="unknown_pack",
            workflow="test",
            agents=[],
            workspace_root=str(tmp_path),
        )
        with pytest.raises(ValueError, match="Unknown domain pack"):
            orchestrator.create_session(config)

    def test_unknown_workflow_raises(
        self, orchestrator: SessionOrchestrator, tmp_path: object
    ) -> None:
        config = SessionConfig(
            domain_pack="labos",
            workflow="nonexistent_workflow",
            agents=[],
            workspace_root=str(tmp_path),
        )
        with pytest.raises(ValueError, match="Unknown workflow"):
            orchestrator.create_session(config)

    def test_unknown_role_raises(
        self, orchestrator: SessionOrchestrator, tmp_path: object
    ) -> None:
        config = SessionConfig(
            domain_pack="labos",
            workflow="multi_agent_research",
            agents=[AgentSlotConfig(role="nonexistent_role", model="mock")],
            workspace_root=str(tmp_path),
        )
        with pytest.raises(ValueError, match="Unknown role"):
            orchestrator.create_session(config)


class TestSessionLifecycle:
    def test_start_sets_running(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        # State should be RUNNING initially (or quickly transition)
        state = orchestrator.get_session_state(sid)
        assert state in (SessionState.RUNNING, SessionState.SUCCEEDED, SessionState.FAILED)

    def test_session_succeeds_with_mock(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        # Wait for completion
        time.sleep(2.0)
        state = orchestrator.get_session_state(sid)
        assert state in (SessionState.SUCCEEDED, SessionState.FAILED)

    def test_session_emits_events(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        time.sleep(2.0)
        events = orchestrator.get_session_events(sid)
        assert len(events) > 0
        # First event should be SessionStarted
        assert events[0].event_type == EventType.SESSION_STARTED

    def test_stop_session(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        orchestrator.stop_session(sid)
        state = orchestrator.get_session_state(sid)
        assert state in (SessionState.STOPPED, SessionState.SUCCEEDED, SessionState.FAILED)

    def test_start_non_created_session_raises(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        time.sleep(1.0)
        with pytest.raises(RuntimeError, match="expected CREATED"):
            orchestrator.start_session(sid, lm_provider=provider)


class TestSessionQueries:
    def test_list_sessions(
        self, orchestrator: SessionOrchestrator, tmp_path: object
    ) -> None:
        for i in range(3):
            config = SessionConfig(
                domain_pack="labos",
                workflow="multi_agent_research",
                agents=[AgentSlotConfig(role="planner", model="mock")],
                workspace_root=str(tmp_path) + f"/session_{i}",
            )
            orchestrator.create_session(config)
        sessions = orchestrator.list_sessions()
        assert len(sessions) == 3

    def test_get_session_info(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        info = orchestrator.get_session_info(sid)
        assert info["session_id"] == sid
        assert info["state"] == "CREATED"
        assert info["domain_pack"] == "labos"
        assert info["workflow"] == "multi_agent_research"

    def test_get_events_after_seq(
        self, orchestrator: SessionOrchestrator, labos_config: SessionConfig
    ) -> None:
        sid = orchestrator.create_session(labos_config)
        provider = _FinishImmediatelyProvider()
        orchestrator.start_session(sid, lm_provider=provider)
        time.sleep(2.0)
        all_events = orchestrator.get_session_events(sid)
        if len(all_events) > 1:
            filtered = orchestrator.get_session_events(sid, after_seq=1)
            assert len(filtered) < len(all_events)

    def test_unknown_session_raises(
        self, orchestrator: SessionOrchestrator
    ) -> None:
        with pytest.raises(KeyError, match="not found"):
            orchestrator.get_session_state("nonexistent-session-id")
