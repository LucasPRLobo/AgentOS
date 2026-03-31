"""Tests for the workspace runtime."""

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType
from agentos.workspace.runtime import WorkspaceRuntime
from agentos.workspace.schemas import (
    BacklogTask,
    BacklogTaskStatus,
    TeamMode,
    WorkspaceConfig,
    WorkspaceParticipant,
    WorkspaceStatus,
)


@pytest.fixture
def runtime(tmp_path):
    cfg = WorkspaceConfig(
        name="Test Workspace",
        goal="Build something great",
        team=[
            WorkspaceParticipant(name="agent-a", specialization="Research"),
            WorkspaceParticipant(name="lucas", type="human", roles=["lead"]),
        ],
        acceptance_criteria=["Output produced", "Human approved"],
    )
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    rt = WorkspaceRuntime(cfg, el, seq, "wf-test")
    return rt


class TestLifecycle:
    def test_start(self, runtime):
        runtime.start()
        state = runtime.state
        assert state.status == WorkspaceStatus.ACTIVE

        board = runtime.get_board_state()
        # Should have pinned announcement
        assert any("Build something great" in a.content for a in board.announcements)
        # Should have team on roster
        assert len(board.team_status) == 2

    def test_pause_resume(self, runtime):
        runtime.start()
        runtime.pause()
        assert runtime.state.status == WorkspaceStatus.PAUSED

        runtime.resume()
        assert runtime.state.status == WorkspaceStatus.ACTIVE

    def test_complete(self, runtime):
        runtime.start()
        runtime.complete()
        assert runtime.state.status == WorkspaceStatus.COMPLETED


class TestTaskManagement:
    def test_add_task(self, runtime):
        runtime.start()
        tid = runtime.add_task(BacklogTask(title="Research ECB"))
        tasks = runtime.backlog.get_all_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Research ECB"

    def test_claim_and_complete(self, runtime):
        runtime.start()
        tid = runtime.add_task(BacklogTask(title="Test"))
        runtime.claim_task(tid, "agent-a")

        # Board should show agent as running
        board = runtime.get_board_state()
        agent_status = [s for s in board.team_status if s.agent_id == "agent-a"]
        assert agent_status[0].state == "running"

        runtime.backlog.start_task(tid)
        runtime.complete_task(tid, {"summary": "Done researching"})

        task = runtime.backlog.get_task(tid)
        assert task.status == BacklogTaskStatus.DONE

    def test_backlog_summary(self, runtime):
        runtime.start()
        runtime.add_task(BacklogTask(title="t1"))
        runtime.add_task(BacklogTask(title="t2"))
        tid = runtime.add_task(BacklogTask(title="t3"))
        runtime.claim_task(tid, "agent-a")
        runtime.backlog.start_task(tid)
        runtime.complete_task(tid)

        summary = runtime.get_backlog_summary()
        assert summary["total"] == 3
        assert summary["open"] == 2
        assert summary["done"] == 1


class TestTeamManagement:
    def test_add_participant(self, runtime):
        runtime.start()
        runtime.add_participant(WorkspaceParticipant(
            name="quant-dev", specialization="Quantitative analysis"
        ))
        assert len(runtime.config.team) == 3

    def test_remove_participant(self, runtime):
        runtime.start()
        runtime.remove_participant("agent-a")
        assert len(runtime.config.team) == 1

    def test_lock_team(self, runtime):
        runtime.start()
        runtime.lock_team()
        assert runtime.config.team_mode == TeamMode.LOCKED

    def test_unlock_team(self, runtime):
        runtime.start()
        runtime.lock_team()
        runtime.unlock_team("suggest")
        assert runtime.config.team_mode == TeamMode.SUGGEST


class TestEvents:
    def test_workspace_events(self, runtime):
        runtime.start()
        runtime.add_task(BacklogTask(title="t"))
        runtime.pause()
        runtime.resume()
        runtime.complete()

        events = runtime._event_log.query(workflow_id="wf-test")
        types = {e.event_type for e in events}
        assert EventType.WORKSPACE_CREATED in types
        assert EventType.WORKSPACE_PAUSED in types
        assert EventType.WORKSPACE_COMPLETED in types
        assert EventType.BACKLOG_TASK_CREATED in types
