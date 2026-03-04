"""Tests for the PostHocVerifier — runtime policy verification for Tier 2/3."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.security.post_hoc_verifier import PostHocVerifier


@pytest.fixture
def verifier(event_log, seq) -> PostHocVerifier:
    return PostHocVerifier(event_log=event_log, seq=seq, workflow_id="test-wf")


class TestNoViolations:
    def test_no_changes_passes(self, verifier, tmp_path):
        policy = CapabilityPolicy(agent_id="a1")
        snapshot = {str(tmp_path / "file.py"): 1000.0}
        result = verifier.verify("a1", policy, tmp_path, snapshot, snapshot)
        assert result.passed
        assert result.files_touched == []

    def test_allowed_path_accepted(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = CapabilityPolicy(
            agent_id="a1",
            grants=[CapabilityGrant(type="path:*")],
        )
        file_path = str(workspace.resolve() / "output.txt")
        pre = {}
        post = {file_path: 1000.0}
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert result.passed
        assert file_path in result.files_allowed


class TestUnauthorizedPath:
    def test_unauthorized_path_detected(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = CapabilityPolicy(agent_id="a1", deny_by_default=True)
        file_path = str(workspace.resolve() / "secret.txt")
        pre = {}
        post = {file_path: 1000.0}
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert not result.passed
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == "path"
        assert result.violations[0].severity == "error"
        assert file_path in result.files_unauthorized

    def test_multiple_violations(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = CapabilityPolicy(agent_id="a1", deny_by_default=True)
        pre = {}
        post = {
            str(workspace.resolve() / "a.txt"): 1000.0,
            str(workspace.resolve() / "b.txt"): 1000.0,
            str(workspace.resolve() / "c.txt"): 1000.0,
        }
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert len(result.violations) == 3
        assert len(result.files_unauthorized) == 3


class TestWorkspaceEscape:
    def test_file_outside_workspace_critical(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside_file = str((tmp_path / "outside.txt").resolve())
        policy = CapabilityPolicy(agent_id="a1")
        pre = {}
        post = {outside_file: 1000.0}
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert not result.passed
        assert result.violations[0].violation_type == "workspace_escape"
        assert result.violations[0].severity == "critical"


class TestViolationEvents:
    def test_violation_events_emitted(self, verifier, event_log, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = CapabilityPolicy(agent_id="a1", deny_by_default=True)
        file_path = str(workspace.resolve() / "file.txt")
        pre = {}
        post = {file_path: 1000.0}
        verifier.verify("a1", policy, workspace, pre, post)
        events = event_log.query(event_type=EventType.POLICY_VIOLATION_DETECTED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "a1"
        assert events[0].payload["violation_type"] == "path"
        assert events[0].schema_version == "0.2"

    def test_no_events_on_clean_run(self, verifier, event_log, tmp_path):
        policy = CapabilityPolicy(agent_id="a1")
        snapshot = {}
        verifier.verify("a1", policy, tmp_path, snapshot, snapshot)
        events = event_log.query(event_type=EventType.POLICY_VIOLATION_DETECTED)
        assert len(events) == 0


class TestSeverityClassification:
    def test_path_violation_is_error(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        policy = CapabilityPolicy(agent_id="a1", deny_by_default=True)
        pre = {}
        post = {str(workspace.resolve() / "file.txt"): 1000.0}
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert result.violations[0].severity == "error"

    def test_escape_violation_is_critical(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = str((tmp_path / "escape.txt").resolve())
        policy = CapabilityPolicy(agent_id="a1")
        result = verifier.verify("a1", policy, workspace, {}, {outside: 1000.0})
        assert result.violations[0].severity == "critical"


class TestSnapshotDirectory:
    def test_snapshot_captures_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        snapshot = PostHocVerifier.snapshot_directory(tmp_path)
        assert len(snapshot) == 2
        assert all(isinstance(v, float) for v in snapshot.values())

    def test_snapshot_empty_dir(self, tmp_path):
        snapshot = PostHocVerifier.snapshot_directory(tmp_path)
        assert snapshot == {}

    def test_snapshot_nonexistent_dir(self, tmp_path):
        snapshot = PostHocVerifier.snapshot_directory(tmp_path / "nonexistent")
        assert snapshot == {}


class TestModifiedFileDetection:
    def test_modified_file_detected(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        file_path = str(workspace.resolve() / "existing.txt")
        policy = CapabilityPolicy(agent_id="a1", deny_by_default=True)
        pre = {file_path: 1000.0}
        post = {file_path: 2000.0}  # Different mtime = modified
        result = verifier.verify("a1", policy, workspace, pre, post)
        assert file_path in result.files_touched

    def test_unchanged_file_ignored(self, verifier, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        file_path = str(workspace.resolve() / "unchanged.txt")
        policy = CapabilityPolicy(agent_id="a1")
        snapshot = {file_path: 1000.0}
        result = verifier.verify("a1", policy, workspace, snapshot, snapshot)
        assert file_path not in result.files_touched
