"""Tests for AgentLifecycleManager — spawn, stop, restart, policy enforcement."""

from __future__ import annotations

import time

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.lifecycle import (
    AgentLifecycleManager,
    AgentState,
    CuratedBriefing,
    LifecycleError,
    LifecyclePolicy,
    RestartReason,
    TerminationReason,
)
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


@pytest.fixture
def manager(event_log, seq):
    return AgentLifecycleManager(event_log, seq, "test-wf")


# ---------------------------------------------------------------------------
# Tests: Spawn
# ---------------------------------------------------------------------------

class TestSpawn:

    def test_spawn_creates_running_agent(self, manager):
        record = manager.spawn("ag1", agent_name="researcher")
        assert record.agent_id == "ag1"
        assert record.agent_name == "researcher"
        assert record.state == AgentState.RUNNING
        assert record.start_time is not None

    def test_spawn_emits_event(self, manager, event_log):
        manager.spawn("ag1", agent_name="researcher", adapter_tier=2)
        events = event_log.query(event_type=EventType.AGENT_SPAWNED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["agent_name"] == "researcher"
        assert events[0].payload["adapter_tier"] == 2

    def test_spawn_default_name(self, manager):
        record = manager.spawn("ag1")
        assert record.agent_name == "ag1"

    def test_spawn_duplicate_running_raises(self, manager):
        manager.spawn("ag1")
        with pytest.raises(LifecycleError, match="already running"):
            manager.spawn("ag1")

    def test_spawn_after_stop_ok(self, manager):
        manager.spawn("ag1")
        manager.stop("ag1")
        record = manager.spawn("ag1")
        assert record.state == AgentState.RUNNING


# ---------------------------------------------------------------------------
# Tests: Stop
# ---------------------------------------------------------------------------

class TestStop:

    def test_stop_sets_stopped_state(self, manager):
        manager.spawn("ag1")
        record = manager.stop("ag1")
        assert record.state == AgentState.STOPPED

    def test_stop_emits_event(self, manager, event_log):
        manager.spawn("ag1")
        manager.stop("ag1", reason=TerminationReason.COMPLETED)

        events = event_log.query(event_type=EventType.AGENT_TERMINATED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["reason"] == "completed"

    def test_stop_includes_metrics(self, manager, event_log):
        manager.spawn("ag1")
        manager.record_turn("ag1", tokens=500)
        manager.record_turn("ag1", tokens=300)
        manager.stop("ag1")

        events = event_log.query(event_type=EventType.AGENT_TERMINATED)
        metrics = events[0].payload["metrics"]
        assert metrics["tokens"] == 800
        assert metrics["turns"] == 2

    def test_stop_nonexistent_raises(self, manager):
        with pytest.raises(LifecycleError, match="not found"):
            manager.stop("ghost")

    def test_stop_already_stopped_raises(self, manager):
        manager.spawn("ag1")
        manager.stop("ag1")
        with pytest.raises(LifecycleError, match="not running"):
            manager.stop("ag1")

    def test_stop_custom_metrics(self, manager, event_log):
        manager.spawn("ag1")
        manager.stop("ag1", metrics={"tokens": 9999, "custom": "data"})

        events = event_log.query(event_type=EventType.AGENT_TERMINATED)
        assert events[0].payload["metrics"]["custom"] == "data"


# ---------------------------------------------------------------------------
# Tests: Record turn
# ---------------------------------------------------------------------------

class TestRecordTurn:

    def test_accumulates_tokens(self, manager):
        manager.spawn("ag1")
        manager.record_turn("ag1", tokens=100)
        manager.record_turn("ag1", tokens=200)
        record = manager.get_record("ag1")
        assert record.tokens_consumed == 300
        assert record.turns_completed == 2

    def test_records_summary(self, manager):
        manager.spawn("ag1")
        manager.record_turn("ag1", summary="First pass done")
        record = manager.get_record("ag1")
        assert record.last_summary == "First pass done"

    def test_accumulates_findings(self, manager):
        manager.spawn("ag1")
        manager.record_turn("ag1", findings=["found A"])
        manager.record_turn("ag1", findings=["found B", "found C"])
        record = manager.get_record("ag1")
        assert record.cumulative_findings == ["found A", "found B", "found C"]

    def test_turn_on_nonrunning_raises(self, manager):
        with pytest.raises(LifecycleError):
            manager.record_turn("ghost", tokens=100)


# ---------------------------------------------------------------------------
# Tests: Record error
# ---------------------------------------------------------------------------

class TestRecordError:

    def test_records_error(self, manager):
        manager.spawn("ag1")
        manager.record_error("ag1", "API timeout")
        record = manager.get_record("ag1")
        assert record.error_history == ["API timeout"]

    def test_error_on_unknown_agent_is_noop(self, manager):
        manager.record_error("ghost", "no crash")


# ---------------------------------------------------------------------------
# Tests: Policy enforcement via record_turn
# ---------------------------------------------------------------------------

class TestPolicyEnforcement:

    def test_token_threshold_triggers(self, manager):
        policy = LifecyclePolicy(max_tokens=500)
        manager.spawn("ag1", policy=policy)
        result = manager.record_turn("ag1", tokens=300)
        assert result is None
        result = manager.record_turn("ag1", tokens=200)
        assert result == RestartReason.TOKEN_THRESHOLD

    def test_turn_count_triggers(self, manager):
        policy = LifecyclePolicy(max_turns=3)
        manager.spawn("ag1", policy=policy)
        assert manager.record_turn("ag1") is None
        assert manager.record_turn("ag1") is None
        assert manager.record_turn("ag1") == RestartReason.TURN_COUNT

    def test_time_limit_triggers(self, manager, event_log, seq):
        policy = LifecyclePolicy(max_time_seconds=0.0)  # Immediate
        mgr = AgentLifecycleManager(event_log, seq, "test-wf", default_policy=policy)
        mgr.spawn("ag1")
        # Even with 0.0 limit, time.monotonic() will have advanced
        time.sleep(0.01)
        result = mgr.record_turn("ag1")
        assert result == RestartReason.TIME_LIMIT

    def test_no_policy_no_trigger(self, manager):
        manager.spawn("ag1")
        for _ in range(100):
            result = manager.record_turn("ag1", tokens=1000)
            assert result is None


# ---------------------------------------------------------------------------
# Tests: Restart
# ---------------------------------------------------------------------------

class TestRestart:

    def test_restart_returns_new_record_and_briefing(self, manager):
        manager.spawn("ag1", agent_name="researcher")
        manager.record_turn("ag1", tokens=100, summary="Did analysis",
                            findings=["Finding A"])

        new_record, briefing = manager.restart("ag1", RestartReason.MANUAL)

        assert new_record.state == AgentState.RUNNING
        assert new_record.restart_count == 1
        assert new_record.tokens_consumed == 0  # Fresh instance
        assert new_record.cumulative_findings == ["Finding A"]  # Carried forward

        assert isinstance(briefing, CuratedBriefing)
        assert briefing.restart_number == 1
        assert briefing.reason == RestartReason.MANUAL
        assert briefing.prior_summary == "Did analysis"
        assert "Finding A" in briefing.key_findings

    def test_restart_emits_terminated_and_spawned(self, manager, event_log):
        manager.spawn("ag1")
        manager.restart("ag1", RestartReason.TOKEN_THRESHOLD)

        terminated = event_log.query(event_type=EventType.AGENT_TERMINATED)
        spawned = event_log.query(event_type=EventType.AGENT_SPAWNED)
        # 1 initial spawn + 1 restart spawn = 2 spawned events
        assert len(spawned) == 2
        # 1 stop from restart = 1 terminated event
        assert len(terminated) == 1

    def test_restart_increments_count(self, manager):
        policy = LifecyclePolicy(max_restarts=5)
        manager.spawn("ag1", policy=policy)
        manager.restart("ag1")
        manager.restart("ag1")
        record = manager.get_record("ag1")
        assert record.restart_count == 2

    def test_max_restarts_exceeded_fails(self, manager):
        policy = LifecyclePolicy(max_restarts=1)
        manager.spawn("ag1", policy=policy)
        manager.restart("ag1")  # restart_count becomes 1
        with pytest.raises(LifecycleError, match="exceeded max restarts"):
            manager.restart("ag1")

    def test_max_restarts_exceeded_sets_failed_state(self, manager):
        policy = LifecyclePolicy(max_restarts=0)
        manager.spawn("ag1", policy=policy)
        with pytest.raises(LifecycleError):
            manager.restart("ag1")
        record = manager.get_record("ag1")
        assert record.state == AgentState.FAILED

    def test_restart_with_instructions(self, manager):
        manager.spawn("ag1")
        manager.record_turn("ag1", summary="Phase 1 done")
        _, briefing = manager.restart(
            "ag1",
            reason=RestartReason.TOKEN_THRESHOLD,
            instructions="Focus on phase 2 analysis",
        )
        assert briefing.instructions == "Focus on phase 2 analysis"

    def test_restart_nonrunning_raises(self, manager):
        with pytest.raises(LifecycleError, match="not found"):
            manager.restart("ghost")


# ---------------------------------------------------------------------------
# Tests: Curated briefing
# ---------------------------------------------------------------------------

class TestCuratedBriefing:

    def test_briefing_trims_findings(self, manager):
        policy = LifecyclePolicy(briefing_max_tokens=300)
        manager.spawn("ag1", policy=policy)
        # Add many findings
        for i in range(100):
            manager.record_turn("ag1", findings=[f"Finding {i}"])

        _, briefing = manager.restart("ag1")
        # Should be trimmed to fit within budget
        assert len(briefing.key_findings) < 100
        # Most recent findings should be kept
        assert briefing.key_findings[-1] == "Finding 99"

    def test_briefing_carries_summary(self, manager):
        manager.spawn("ag1")
        manager.record_turn("ag1", summary="Early work")
        manager.record_turn("ag1", summary="Latest summary")
        _, briefing = manager.restart("ag1")
        assert briefing.prior_summary == "Latest summary"


# ---------------------------------------------------------------------------
# Tests: Query methods
# ---------------------------------------------------------------------------

class TestQueryMethods:

    def test_get_record(self, manager):
        manager.spawn("ag1")
        record = manager.get_record("ag1")
        assert record is not None
        assert record.agent_id == "ag1"

    def test_get_record_nonexistent(self, manager):
        assert manager.get_record("ghost") is None

    def test_list_agents(self, manager):
        manager.spawn("ag1")
        manager.spawn("ag2")
        agents = manager.list_agents()
        assert len(agents) == 2

    def test_running_agents(self, manager):
        manager.spawn("ag1")
        manager.spawn("ag2")
        manager.stop("ag1")
        running = manager.running_agents()
        assert len(running) == 1
        assert running[0].agent_id == "ag2"
