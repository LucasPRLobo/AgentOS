"""Tests for collaborative workspace components: context curator, artifacts, verifier."""

import pytest
from pathlib import Path

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.artifacts import ProjectArtifacts
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.context_curator import ContextCurator, TaskContext
from agentos.workspace.schemas import BacklogTask, BacklogTaskStatus, WorkspaceConfig, WorkspaceParticipant
from agentos.workspace.verifier import TaskVerifier, VerificationResult


# ======================================================================
# Context Curator
# ======================================================================

@pytest.fixture
def config():
    return WorkspaceConfig(
        name="Test",
        goal="Research AI protocols and write a report",
        team=[
            WorkspaceParticipant(name="researcher", specialization="Protocol research"),
            WorkspaceParticipant(name="writer", specialization="Technical writing"),
        ],
        acceptance_criteria=["Research report produced", "Human reviewed"],
    )


@pytest.fixture
def backlog(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return BacklogManager(el, seq, "wf-test")


class TestContextCurator:
    def test_curate_basic(self, config, backlog):
        curator = ContextCurator(config, backlog)
        task = BacklogTask(title="Research A2A", spec="Research Google's A2A protocol")
        backlog.create_task(task)
        ctx = curator.curate(task)
        assert ctx.task_spec == "Research Google's A2A protocol"
        assert "AI protocols" in ctx.project_brief

    def test_curate_includes_predecessor_findings(self, config, backlog):
        # Create predecessor with output
        t1 = BacklogTask(title="Research A2A", output={"summary": "A2A is for agent-to-agent discovery"})
        t1.status = BacklogTaskStatus.DONE
        backlog.create_task(t1)

        # Create dependent task
        t2 = BacklogTask(title="Write report", depends_on=[t1.task_id], spec="Write comparison")
        backlog.create_task(t2)

        curator = ContextCurator(config, backlog)
        ctx = curator.curate(t2)
        assert any("agent-to-agent" in f for f in ctx.relevant_findings)

    def test_curate_excludes_unrelated_tasks(self, config, backlog):
        # Unrelated task (not a dependency)
        t_unrelated = BacklogTask(title="Unrelated task", output={"summary": "Something else entirely"})
        t_unrelated.status = BacklogTaskStatus.DONE
        backlog.create_task(t_unrelated)

        # Our task with no dependencies
        task = BacklogTask(title="Write report", spec="Write comparison")
        backlog.create_task(task)

        curator = ContextCurator(config, backlog)
        ctx = curator.curate(task)
        assert not any("Something else" in f for f in ctx.relevant_findings)

    def test_curate_project_brief_compact(self, config, backlog):
        curator = ContextCurator(config, backlog)
        task = BacklogTask(title="Test")
        backlog.create_task(task)
        ctx = curator.curate(task)
        assert len(ctx.project_brief) < 500

    def test_render_prompt_section(self, config, backlog):
        curator = ContextCurator(config, backlog)
        task = BacklogTask(title="Research", spec="Find protocol details", spec_approach="Read docs")
        backlog.create_task(task)
        ctx = curator.curate(task)
        rendered = curator.render_prompt_section(ctx)
        assert "Task Specification" in rendered
        assert "Find protocol details" in rendered
        assert "Read docs" in rendered


# ======================================================================
# Project Artifacts
# ======================================================================

class TestProjectArtifacts:
    def test_write_project(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        artifacts.write_project(
            goal="Research AI protocols",
            description="Compare A2A and MCP",
            criteria=["Report produced"],
        )
        content = (tmp_path / "PROJECT.md").read_text()
        assert "Research AI protocols" in content
        assert "Report produced" in content

    def test_write_plan(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        artifacts.write_plan("Research then write", [
            {"title": "Research", "suggested_for": "researcher", "status": "open"},
            {"title": "Write", "suggested_for": "writer", "status": "proposed"},
        ])
        content = (tmp_path / "PLAN.md").read_text()
        assert "Research" in content
        assert "researcher" in content

    def test_add_decision(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        artifacts.add_decision("Use IMF data for developed markets", "More recent methodology")
        artifacts.add_decision("Focus on architecture, not ecosystem")
        content = (tmp_path / "DECISIONS.md").read_text()
        assert "Use IMF data" in content
        assert "Focus on architecture" in content

    def test_update_state(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        artifacts.update_state(
            tasks=[
                {"title": "Research", "status": "done", "assigned_to": "researcher"},
                {"title": "Write", "status": "in_progress", "assigned_to": "writer"},
            ],
            team_status=[
                {"agent_name": "researcher", "state": "idle"},
                {"agent_name": "writer", "state": "running"},
            ],
        )
        content = (tmp_path / "STATE.md").read_text()
        assert "1/2 tasks done" in content
        assert "researcher" in content

    def test_task_spec_and_output(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        artifacts.write_task_spec("task-123", "Research A2A", "Study architecture", "Read official docs")
        artifacts.write_task_output("task-123", "Research A2A", "A2A enables discovery", ["Finding 1"])
        assert (tmp_path / "tasks" / "task-123-spec.md").exists()
        assert (tmp_path / "tasks" / "task-123-output.md").exists()

    def test_read_methods(self, tmp_path):
        artifacts = ProjectArtifacts(tmp_path)
        assert artifacts.get_project_brief() == ""  # Not written yet
        artifacts.write_project(goal="Test goal")
        assert "Test goal" in artifacts.get_project_brief()


# ======================================================================
# Verifier
# ======================================================================

class TestTaskVerifier:
    def test_no_output_fails(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Test")
        result = verifier.verify(task, None)
        assert not result.passed
        assert result.recommendation == "failed"

    def test_empty_output_fails(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Test")
        result = verifier.verify(task, {})
        assert not result.passed

    def test_good_output_passes(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Research protocols", spec="Research A2A protocol architecture")
        result = verifier.verify(task, {
            "summary": "A2A protocol provides agent-to-agent discovery and task delegation.",
            "findings": [{"finding": "A2A uses JSON-RPC over HTTPS"}],
        })
        assert result.passed
        assert result.recommendation == "auto_accept"

    def test_output_without_findings_for_research(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Research something", spec="Research and analyze the topic")
        result = verifier.verify(task, {"summary": "Done with research."})
        assert "No findings" in str(result.issues) or result.recommendation == "needs_review"

    def test_spec_misalignment(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Research A2A", spec="Study A2A protocol architecture in detail")
        result = verifier.verify(task, {"summary": "The weather is nice today."})
        # Summary doesn't match spec keywords
        assert any("spec" in str(i).lower() or "address" in str(i).lower() for i in result.issues) or not result.passed

    def test_prepare_review_context(self):
        verifier = TaskVerifier()
        task = BacklogTask(title="Research", spec="Study protocols")
        output = {"summary": "Found 3 protocols", "findings": [{"finding": "A2A"}]}
        vr = verifier.verify(task, output)
        ctx = verifier.prepare_review_context(task, output, vr)
        assert ctx["task_title"] == "Research"
        assert ctx["output_summary"] == "Found 3 protocols"
        assert "A2A" in ctx["output_findings"]


# ======================================================================
# Backlog Spec Flow
# ======================================================================

class TestBacklogSpecFlow:
    def test_propose_creates_proposed(self, backlog):
        task = BacklogTask(title="Research")
        tid = backlog.propose_task(task)
        assert backlog.get_task(tid).status == BacklogTaskStatus.PROPOSED

    def test_cannot_claim_proposed(self, backlog):
        task = BacklogTask(title="Research")
        tid = backlog.propose_task(task)
        with pytest.raises(ValueError, match="Cannot claim"):
            backlog.claim_task(tid, "agent-a")

    def test_full_spec_flow(self, backlog):
        # Propose
        task = BacklogTask(title="Research A2A")
        tid = backlog.propose_task(task)
        assert backlog.get_task(tid).status == BacklogTaskStatus.PROPOSED

        # Start specifying (discussion opened)
        backlog.start_specifying(tid, "disc-1")
        assert backlog.get_task(tid).status == BacklogTaskStatus.SPECIFYING

        # Finalize spec (discussion resolved)
        backlog.finalize_spec(tid, "Study architecture", "Read docs", "Architecture report")
        t = backlog.get_task(tid)
        assert t.status == BacklogTaskStatus.OPEN
        assert t.spec == "Study architecture"
        assert t.spec_approach == "Read docs"

        # Now can claim
        backlog.claim_task(tid, "researcher")
        backlog.start_task(tid)
        assert backlog.get_task(tid).status == BacklogTaskStatus.IN_PROGRESS

        # Mark completed (agent done, awaiting review)
        backlog.mark_completed(tid, {"summary": "Found key insights"})
        assert backlog.get_task(tid).status == BacklogTaskStatus.COMPLETED

        # Start review (discussion opened)
        backlog.start_review(tid, "disc-2")
        assert backlog.get_task(tid).status == BacklogTaskStatus.IN_REVIEW

        # Accept review
        backlog.accept_review(tid, "accepted")
        assert backlog.get_task(tid).status == BacklogTaskStatus.DONE
        assert backlog.get_task(tid).review_verdict == "accepted"

    def test_revision_flow(self, backlog):
        task = BacklogTask(title="Test")
        tid = backlog.propose_task(task)
        backlog.finalize_spec(tid, "Write report")
        backlog.claim_task(tid, "writer")
        backlog.start_task(tid)
        backlog.mark_completed(tid, {"summary": "Draft 1"})
        backlog.start_review(tid, "disc-1")
        backlog.request_revision(tid, "Needs more detail")
        assert backlog.get_task(tid).status == BacklogTaskStatus.REVISION_NEEDED

        # Can restart after revision
        backlog.start_task(tid)
        backlog.mark_completed(tid, {"summary": "Draft 2"})
        backlog.start_review(tid, "disc-2")
        backlog.accept_review(tid)
        assert backlog.get_task(tid).status == BacklogTaskStatus.DONE
