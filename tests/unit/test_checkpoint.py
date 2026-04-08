"""Tests for workspace checkpoint — save/load/apply cycle."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentos.workspace.checkpoint import (
    CHECKPOINT_FILENAME,
    CHECKPOINT_VERSION,
    apply_checkpoint,
    checkpoint_summary,
    delete_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supervisor(tmp_path: Path, task_status: str = "in_progress") -> MagicMock:
    """Build a minimal mock supervisor with enough state to checkpoint."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)

    # Mock backlog task
    task = MagicMock()
    task.task_id = "task-abc"
    task.title = "Write tests"
    task.status = task_status
    task.assigned_to = "coder"

    # Mock backlog manager
    backlog = MagicMock()
    backlog.get_all_tasks.return_value = [task]

    # Mock runtime
    rt = MagicMock()
    rt._workspace_dir = workspace_dir
    rt._workflow_id = "wf-test-123"
    rt.state.workspace_id = "ws-uuid-1"
    rt.state.status = "active"
    rt.backlog = backlog

    # Mock PersistentAgent
    agent = MagicMock()
    agent.state = "idle"
    agent.session_started = True
    agent.current_task_id = None

    # Mock supervisor
    sup = MagicMock()
    sup._rt = rt
    sup._agents = {"coder": agent}
    sup._tick_count = 7

    return sup


# ---------------------------------------------------------------------------
# save_checkpoint
# ---------------------------------------------------------------------------

class TestSaveCheckpoint:
    def test_creates_checkpoint_file(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir

        path = save_checkpoint(sup, workspace_dir)

        assert path.exists()
        assert path.name == CHECKPOINT_FILENAME

    def test_checkpoint_content(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir

        save_checkpoint(sup, workspace_dir)

        data = json.loads((workspace_dir / ".agentos" / CHECKPOINT_FILENAME).read_text())
        assert data["version"] == CHECKPOINT_VERSION
        assert data["workflow_id"] == "wf-test-123"
        assert data["workspace_status"] == "active"
        assert data["tick_count"] == 7
        assert "saved_at" in data
        assert "coder" in data["agent_states"]
        assert data["agent_states"]["coder"]["session_started"] is True

    def test_task_assignments_captured(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir

        save_checkpoint(sup, workspace_dir)

        data = json.loads((workspace_dir / ".agentos" / CHECKPOINT_FILENAME).read_text())
        assert "task-abc" in data["task_assignments"]
        assert data["task_assignments"]["task-abc"] == "coder"

    def test_in_progress_tasks_captured(self, tmp_path):
        sup = _make_supervisor(tmp_path, task_status="in_progress")
        workspace_dir = sup._rt._workspace_dir

        save_checkpoint(sup, workspace_dir)

        data = json.loads((workspace_dir / ".agentos" / CHECKPOINT_FILENAME).read_text())
        assert "task-abc" in data["in_progress_task_ids"]

    def test_claimed_tasks_captured(self, tmp_path):
        sup = _make_supervisor(tmp_path, task_status="claimed")
        workspace_dir = sup._rt._workspace_dir

        save_checkpoint(sup, workspace_dir)

        data = json.loads((workspace_dir / ".agentos" / CHECKPOINT_FILENAME).read_text())
        assert "task-abc" in data["in_progress_task_ids"]

    def test_done_tasks_not_in_in_progress(self, tmp_path):
        sup = _make_supervisor(tmp_path, task_status="done")
        workspace_dir = sup._rt._workspace_dir

        save_checkpoint(sup, workspace_dir)

        data = json.loads((workspace_dir / ".agentos" / CHECKPOINT_FILENAME).read_text())
        assert "task-abc" not in data["in_progress_task_ids"]

    def test_creates_agentos_dir_if_missing(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir
        # Ensure the .agentos dir doesn't pre-exist
        agentos_dir = workspace_dir / ".agentos"
        if agentos_dir.exists():
            import shutil
            shutil.rmtree(agentos_dir)

        save_checkpoint(sup, workspace_dir)

        assert (agentos_dir / CHECKPOINT_FILENAME).exists()


# ---------------------------------------------------------------------------
# load_checkpoint
# ---------------------------------------------------------------------------

class TestLoadCheckpoint:
    def test_returns_none_when_no_file(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        assert load_checkpoint(workspace_dir) is None

    def test_loads_valid_checkpoint(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir
        save_checkpoint(sup, workspace_dir)

        data = load_checkpoint(workspace_dir)

        assert data is not None
        assert data["version"] == CHECKPOINT_VERSION

    def test_returns_none_for_corrupt_json(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agentos_dir = workspace_dir / ".agentos"
        agentos_dir.mkdir()
        (agentos_dir / CHECKPOINT_FILENAME).write_text("{ bad json {{")

        assert load_checkpoint(workspace_dir) is None

    def test_returns_none_for_wrong_version(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agentos_dir = workspace_dir / ".agentos"
        agentos_dir.mkdir()
        data = {
            "version": 999,
            "saved_at": "2026-01-01",
            "agent_states": {},
            "task_assignments": {},
            "in_progress_task_ids": [],
        }
        (agentos_dir / CHECKPOINT_FILENAME).write_text(json.dumps(data))

        assert load_checkpoint(workspace_dir) is None

    def test_returns_none_for_missing_required_keys(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        agentos_dir = workspace_dir / ".agentos"
        agentos_dir.mkdir()
        # Missing agent_states
        data = {"version": CHECKPOINT_VERSION, "saved_at": "2026-01-01"}
        (agentos_dir / CHECKPOINT_FILENAME).write_text(json.dumps(data))

        assert load_checkpoint(workspace_dir) is None


# ---------------------------------------------------------------------------
# apply_checkpoint
# ---------------------------------------------------------------------------

class TestApplyCheckpoint:
    def _make_checkpoint_data(self, extra_in_progress: bool = False) -> dict:
        data = {
            "version": CHECKPOINT_VERSION,
            "saved_at": "2026-01-01T00:00:00+00:00",
            "workspace_id": "ws-1",
            "workflow_id": "wf-1",
            "workspace_status": "active",
            "agent_states": {
                "coder": {
                    "state": "working",
                    "session_started": True,
                    "current_task_id": "task-abc",
                }
            },
            "task_assignments": {"task-abc": "coder"},
            "in_progress_task_ids": ["task-abc"],
            "tick_count": 42,
        }
        return data

    def test_agents_set_to_idle(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        cp = self._make_checkpoint_data()

        apply_checkpoint(sup, cp)

        # Agents should always start idle after restart (processes don't survive)
        assert sup._agents["coder"].state == "idle"
        assert sup._agents["coder"].current_task_id is None

    def test_session_started_preserved(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        sup._agents["coder"].session_started = False
        cp = self._make_checkpoint_data()

        apply_checkpoint(sup, cp)

        # session_started from checkpoint is restored so --continue works
        assert sup._agents["coder"].session_started is True

    def test_tick_count_restored(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        sup._tick_count = 0
        cp = self._make_checkpoint_data()

        apply_checkpoint(sup, cp)

        assert sup._tick_count == 42

    def test_in_progress_tasks_reset_to_open(self, tmp_path):
        sup = _make_supervisor(tmp_path)

        # Set up a real-ish task on backlog
        task = MagicMock()
        task.task_id = "task-abc"
        task.status = "in_progress"
        task.assigned_to = "coder"
        task.claimed_at = "2026-01-01"
        sup._rt.backlog.get_task.return_value = task

        cp = self._make_checkpoint_data()
        apply_checkpoint(sup, cp)

        # Task should be reset to open
        assert task.status == "open"
        assert task.assigned_to is None
        assert task.claimed_at is None

    def test_unknown_agents_in_checkpoint_are_skipped(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        # Checkpoint references an agent not in the current team
        cp = self._make_checkpoint_data()
        cp["agent_states"]["ghost-agent"] = {
            "state": "working", "session_started": True, "current_task_id": None,
        }

        # Should not raise
        apply_checkpoint(sup, cp)

        assert "ghost-agent" not in sup._agents

    def test_missing_task_in_backlog_is_skipped(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        sup._rt.backlog.get_task.side_effect = ValueError("Unknown task")

        cp = self._make_checkpoint_data()

        # Should not raise even when task isn't in backlog
        apply_checkpoint(sup, cp)


# ---------------------------------------------------------------------------
# delete_checkpoint
# ---------------------------------------------------------------------------

class TestDeleteCheckpoint:
    def test_deletes_existing_checkpoint(self, tmp_path):
        sup = _make_supervisor(tmp_path)
        workspace_dir = sup._rt._workspace_dir
        save_checkpoint(sup, workspace_dir)

        checkpoint_file = workspace_dir / ".agentos" / CHECKPOINT_FILENAME
        assert checkpoint_file.exists()

        delete_checkpoint(workspace_dir)

        assert not checkpoint_file.exists()

    def test_noop_when_no_checkpoint(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        # Should not raise
        delete_checkpoint(workspace_dir)


# ---------------------------------------------------------------------------
# checkpoint_summary
# ---------------------------------------------------------------------------

class TestCheckpointSummary:
    def test_returns_none_when_no_checkpoint(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        assert checkpoint_summary(workspace_dir) is None

    def test_returns_summary_dict(self, tmp_path):
        sup = _make_supervisor(tmp_path, task_status="in_progress")
        workspace_dir = sup._rt._workspace_dir
        save_checkpoint(sup, workspace_dir)

        summary = checkpoint_summary(workspace_dir)

        assert summary is not None
        assert "saved_at" in summary
        assert summary["agent_count"] == 1
        assert summary["task_count"] == 1
        assert summary["in_progress_count"] == 1
        assert summary["workspace_status"] == "active"
        assert summary["tick_count"] == 7


# ---------------------------------------------------------------------------
# Round-trip: save → load → apply
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_full_round_trip(self, tmp_path):
        """Save a checkpoint, load it back, and apply it to a fresh supervisor."""
        # Original supervisor saves checkpoint
        original = _make_supervisor(tmp_path, task_status="in_progress")
        original._agents["coder"].session_started = True
        original._tick_count = 99
        workspace_dir = original._rt._workspace_dir

        save_checkpoint(original, workspace_dir)

        # Verify it can be loaded
        data = load_checkpoint(workspace_dir)
        assert data is not None
        assert data["tick_count"] == 99

        # Apply to a new supervisor (simulating a restart).
        # The workspace directory already exists from the original save above.
        resumed = _make_supervisor(tmp_path, task_status="in_progress")
        resumed._rt._workspace_dir = workspace_dir  # reuse the same dir
        resumed._agents["coder"].session_started = False  # Reset to simulate fresh process
        resumed._tick_count = 0

        # Wire up the task reset correctly
        task = MagicMock()
        task.task_id = "task-abc"
        task.status = "in_progress"
        task.assigned_to = "coder"
        task.claimed_at = "some-time"
        resumed._rt.backlog.get_task.return_value = task

        apply_checkpoint(resumed, data)

        # session_started restored (so --continue works)
        assert resumed._agents["coder"].session_started is True
        # Agent is idle (process died on restart)
        assert resumed._agents["coder"].state == "idle"
        # Task reset to open for re-claiming
        assert task.status == "open"
        # Tick count restored
        assert resumed._tick_count == 99
