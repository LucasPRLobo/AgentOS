"""Tests for context summaries, progressive delivery, lifecycle, assistant, completion, cost."""

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec, BudgetUsage
from agentos.workspace.assistant import AssistantSpawner
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.completion import CompletionDetector
from agentos.workspace.context_summary import ContextSummaryManager
from agentos.workspace.cost_tracker import CostTracker
from agentos.workspace.lifecycle import AgentLifecycleManager, AgentState
from agentos.workspace.persistence import load_workspace, save_workspace, workspace_exists
from agentos.workspace.schemas import (
    BacklogTask,
    BacklogTaskStatus,
    WorkspaceConfig,
    WorkspaceState,
)


@pytest.fixture
def event_log(tmp_path):
    return SQLiteEventLog(str(tmp_path / "test.db"))


@pytest.fixture
def seq():
    return SeqCounter()


# ======================================================================
# Context Summaries
# ======================================================================

class TestContextSummaryManager:
    def test_create_and_update(self, tmp_path):
        mgr = ContextSummaryManager(tmp_path)
        assert mgr.get_agent_summary("agent-a") is None

        s = mgr.update_agent_summary("agent-a", {
            "summary": "Found GDP data",
            "findings": [{"finding": "IMF reports 2.3% growth"}],
            "open_questions": ["Verify with World Bank?"],
            "files_produced": ["report.md"],
        }, task_title="Research ECB")

        assert s.agent_id == "agent-a"
        assert "Found GDP data" in s.changes_made
        assert "IMF reports 2.3% growth" in s.decisions
        assert "Verify with World Bank?" in s.next_steps
        assert "report.md" in s.entity_references
        assert "Research ECB" in s.tasks_completed
        assert s.summary_version == 1

    def test_incremental_merge(self, tmp_path):
        mgr = ContextSummaryManager(tmp_path)
        mgr.update_agent_summary("a", {"summary": "Step 1"})
        mgr.update_agent_summary("a", {"summary": "Step 2"})
        s = mgr.get_agent_summary("a")
        assert len(s.changes_made) == 2
        assert s.summary_version == 2

    def test_max_items_cap(self, tmp_path):
        mgr = ContextSummaryManager(tmp_path)
        for i in range(15):
            mgr.update_agent_summary("a", {"summary": f"Item {i}"})
        s = mgr.get_agent_summary("a")
        assert len(s.changes_made) <= 10

    def test_workspace_summary(self, tmp_path):
        mgr = ContextSummaryManager(tmp_path)
        ws = mgr.update_workspace_summary(
            tasks_completed=3, tasks_remaining=2,
            new_decisions=["Use IMF data"],
            status="Phase 2",
        )
        assert ws.tasks_completed == 3
        assert "Use IMF data" in ws.key_decisions

    def test_persistence(self, tmp_path):
        mgr = ContextSummaryManager(tmp_path)
        mgr.update_agent_summary("a", {"summary": "persisted"})
        mgr.update_workspace_summary(status="saved")

        mgr2 = ContextSummaryManager(tmp_path)
        mgr2.load_from_disk()
        assert mgr2.get_agent_summary("a").changes_made == ["persisted"]
        assert mgr2.get_workspace_summary().current_status == "saved"


# ======================================================================
# Lifecycle
# ======================================================================

class TestAgentLifecycle:
    def test_activate_deactivate(self, event_log, seq):
        lm = AgentLifecycleManager(event_log, seq, "wf-test")
        assert lm.get_state("a") == AgentState.DORMANT

        lm.activate("a", "task-1")
        assert lm.get_state("a") == AgentState.ACTIVE
        assert "a" in lm.get_active_agents()

        lm.deactivate("a")
        assert lm.get_state("a") == AgentState.DORMANT
        assert "a" in lm.get_dormant_agents()

    def test_suspend_resume(self, event_log, seq):
        lm = AgentLifecycleManager(event_log, seq, "wf-test")
        lm.activate("a", "t1")
        lm.suspend("a", "waiting for input")
        assert lm.get_state("a") == AgentState.SUSPENDED

        lm.resume_agent("a")
        assert lm.get_state("a") == AgentState.ACTIVE

    def test_duration_tracking(self, event_log, seq):
        lm = AgentLifecycleManager(event_log, seq, "wf-test")
        lm.activate("a", "t1")
        dur = lm.get_activation_duration("a")
        assert dur >= 0

    def test_35_min_check(self, event_log, seq):
        lm = AgentLifecycleManager(event_log, seq, "wf-test")
        # Agent not active — should not warn
        assert lm.check_duration("a") is False

        lm.activate("a", "t1")
        # Just activated — should not exceed
        assert lm.check_duration("a") is False


# ======================================================================
# Assistant Spawner
# ======================================================================

class TestAssistantSpawner:
    def test_should_spawn(self, event_log, seq):
        sp = AssistantSpawner(event_log, seq, "wf-test")
        assert sp.should_spawn(3000) is False  # Below threshold
        assert sp.should_spawn(6000) is True   # Above threshold

    @pytest.mark.asyncio
    async def test_spawn_with_mock(self, event_log, seq):
        sp = AssistantSpawner(event_log, seq, "wf-test")
        result = await sp.spawn(
            worker_id="agent-a",
            task_description="Summarize data",
        )
        assert result["status"] == "succeeded"

        events = event_log.query(workflow_id="wf-test")
        types = [e.event_type for e in events]
        from agentos.schemas.events import EventType
        assert EventType.ASSISTANT_SPAWNED in types
        assert EventType.ASSISTANT_COMPLETED in types


# ======================================================================
# Completion Detector
# ======================================================================

class TestCompletionDetector:
    def test_no_tasks(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        cfg = WorkspaceConfig(name="t", goal="g")
        cd = CompletionDetector(cfg, bl)
        result = cd.check()
        assert result.complete is False
        assert result.reason == "no_tasks"

    def test_tasks_remaining(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        bl.create_task(BacklogTask(title="t1"))
        bl.create_task(BacklogTask(title="t2"))
        cfg = WorkspaceConfig(name="t", goal="g")
        cd = CompletionDetector(cfg, bl)
        result = cd.check()
        assert result.complete is False
        assert result.reason == "tasks_remaining"

    def test_all_done_no_criteria(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        tid = bl.create_task(BacklogTask(title="only task"))
        bl.claim_task(tid, "a"); bl.start_task(tid); bl.complete_task(tid)
        cfg = WorkspaceConfig(name="t", goal="g")
        cd = CompletionDetector(cfg, bl)
        result = cd.check()
        assert result.complete is True
        assert result.reason == "all_tasks_done"

    def test_all_done_with_criteria(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        tid = bl.create_task(BacklogTask(title="t"))
        bl.claim_task(tid, "a"); bl.start_task(tid); bl.complete_task(tid)
        cfg = WorkspaceConfig(name="t", goal="g", acceptance_criteria=["Report produced"])
        cd = CompletionDetector(cfg, bl)
        result = cd.check()
        assert result.complete is True
        assert result.reason == "goal_satisfied"

    def test_budget_exhausted(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        bl.create_task(BacklogTask(title="t"))
        cfg = WorkspaceConfig(name="t", goal="g", budget=BudgetSpec(max_cost_usd=10.0))
        cd = CompletionDetector(cfg, bl, budget_usage=BudgetUsage(cost_usd=11.0))
        result = cd.check()
        assert result.complete is True
        assert result.reason == "budget_exhausted"

    def test_scope_creep(self, event_log, seq):
        bl = BacklogManager(event_log, seq, "wf-test")
        for i in range(3):
            bl.create_task(BacklogTask(title=f"initial-{i}"))
        cfg = WorkspaceConfig(name="t", goal="g")
        cd = CompletionDetector(cfg, bl)
        cd.set_initial_task_count(3)
        # Add many more tasks
        for i in range(10):
            bl.create_task(BacklogTask(title=f"extra-{i}"))
        result = cd.check()
        assert result.reason == "scope_creep"


# ======================================================================
# Cost Tracker
# ======================================================================

class TestCostTracker:
    def test_record_and_totals(self):
        ct = CostTracker(BudgetSpec(max_cost_usd=50.0))
        ct.record("agent-a", "task-1", BudgetDelta(tokens=1000, cost_usd=0.10))
        ct.record("agent-a", "task-1", BudgetDelta(tokens=500, cost_usd=0.05))
        ct.record("agent-b", "task-2", BudgetDelta(tokens=2000, cost_usd=0.20))

        total = ct.get_total()
        assert total.tokens_used == 3500
        assert total.cost_usd == pytest.approx(0.35)

    def test_per_agent(self):
        ct = CostTracker(BudgetSpec())
        ct.record("a", "t1", BudgetDelta(cost_usd=0.10))
        ct.record("b", "t2", BudgetDelta(cost_usd=0.20))
        assert ct.get_per_agent("a").cost_usd == pytest.approx(0.10)

    def test_per_task(self):
        ct = CostTracker(BudgetSpec())
        ct.record("a", "t1", BudgetDelta(cost_usd=0.10))
        ct.record("a", "t1", BudgetDelta(cost_usd=0.05))
        assert ct.get_per_task("t1").cost_usd == pytest.approx(0.15)

    def test_budget_allocation(self):
        ct = CostTracker(BudgetSpec(max_cost_usd=50.0))
        ct.allocate_for_task("t1", BudgetSpec(max_cost_usd=5.0))
        ct.record("a", "t1", BudgetDelta(cost_usd=2.0))
        remaining = ct.get_remaining_for_task("t1")
        assert remaining.max_cost_usd == pytest.approx(3.0)

    def test_reserve(self):
        ct = CostTracker(BudgetSpec(max_cost_usd=100.0))
        ct.allocate_for_task("t1", BudgetSpec(max_cost_usd=30.0))
        ct.allocate_for_task("t2", BudgetSpec(max_cost_usd=20.0))
        assert ct.get_reserve() == pytest.approx(50.0)

    def test_budget_consumed_pct(self):
        ct = CostTracker(BudgetSpec(max_cost_usd=100.0))
        ct.record("a", "t1", BudgetDelta(cost_usd=25.0))
        assert ct.get_budget_consumed_pct() == pytest.approx(0.25)

    def test_cost_of_pass(self):
        ct = CostTracker(BudgetSpec())
        ct.record("a", "t1", BudgetDelta(cost_usd=1.0))
        ct.record_task_attempt("t1", success=True)
        ct.record("a", "t1", BudgetDelta(cost_usd=1.0))
        ct.record_task_attempt("t1", success=False)
        # 2 attempts, 1 success, $2 total → $1/attempt, 50% success → $2 cost-of-pass
        cop = ct.cost_of_pass("t1")
        assert cop == pytest.approx(2.0)

    def test_model_tier_suggestion(self):
        assert CostTracker.suggest_model_tier("simple data extraction") == "haiku"
        assert CostTracker.suggest_model_tier("complex strategy synthesis") == "opus"
        assert CostTracker.suggest_model_tier("analyze market data") == "sonnet"


# ======================================================================
# Persistence
# ======================================================================

class TestPersistence:
    def test_save_and_load(self, tmp_path):
        cfg = WorkspaceConfig(name="test", goal="goal")
        state = WorkspaceState(config=cfg)
        tasks = [BacklogTask(title="t1"), BacklogTask(title="t2")]

        save_workspace(tmp_path, cfg, state, tasks)
        assert workspace_exists(tmp_path)

        loaded = load_workspace(tmp_path)
        assert loaded is not None
        assert loaded["config"].name == "test"
        assert len(loaded["tasks"]) == 2

    def test_missing_workspace(self, tmp_path):
        assert workspace_exists(tmp_path) is False
        assert load_workspace(tmp_path) is None

    def test_roundtrip_preserves_data(self, tmp_path):
        cfg = WorkspaceConfig(
            name="Investment", goal="Manage portfolio",
            acceptance_criteria=["Report produced"],
        )
        state = WorkspaceState(config=cfg)
        task = BacklogTask(title="Research", priority="high", assigned_to="agent-a",
                            status=BacklogTaskStatus.CLAIMED)
        save_workspace(tmp_path, cfg, state, [task])

        loaded = load_workspace(tmp_path)
        assert loaded["config"].acceptance_criteria == ["Report produced"]
        assert loaded["tasks"][0].priority == "high"
        assert loaded["tasks"][0].assigned_to == "agent-a"
