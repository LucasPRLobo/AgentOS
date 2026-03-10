"""Tests for CLI commands using Click's CliRunner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from agentos.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(runner, db_path):
    """Run a workflow to populate the DB, return the db path."""
    result = runner.invoke(cli, ["workflow", "run", "examples/linear_research.yaml", "--db", db_path])
    assert result.exit_code == 0
    return db_path


class TestWorkflowRun:
    """agentos workflow run"""

    def test_run_linear(self, runner, db_path):
        result = runner.invoke(cli, ["workflow", "run", "examples/linear_research.yaml", "--db", db_path])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output
        assert "Completed: 3" in result.output

    def test_run_parallel(self, runner, db_path):
        result = runner.invoke(cli, ["workflow", "run", "examples/parallel_analysis.yaml", "--db", db_path])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output

    def test_run_fanout(self, runner, db_path):
        result = runner.invoke(cli, ["workflow", "run", "examples/fanout_with_gate.yaml", "--db", db_path])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output
        assert "Completed: 6" in result.output

    def test_run_nonexistent_file(self, runner):
        result = runner.invoke(cli, ["workflow", "run", "nonexistent.yaml"])
        assert result.exit_code != 0

    def test_run_persists_to_db(self, runner, db_path):
        runner.invoke(cli, ["workflow", "run", "examples/linear_research.yaml", "--db", db_path])
        # Verify we can read events from the persisted DB
        result = runner.invoke(cli, ["status", "--db", db_path])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output


class TestWorkflowVerify:
    """agentos workflow verify"""

    def test_verify_valid_linear(self, runner):
        result = runner.invoke(cli, ["workflow", "verify", "examples/linear_research.yaml"])
        assert result.exit_code == 0
        assert "PASSED" in result.output

    def test_verify_valid_parallel(self, runner):
        result = runner.invoke(cli, ["workflow", "verify", "examples/parallel_analysis.yaml"])
        assert result.exit_code == 0
        assert "PASSED" in result.output

    def test_verify_valid_fanout(self, runner):
        result = runner.invoke(cli, ["workflow", "verify", "examples/fanout_with_gate.yaml"])
        assert result.exit_code == 0
        assert "PASSED" in result.output

    def test_verify_invalid_yaml(self, runner, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: test\ntasks:\n  a:\n    name: a\n    depends_on: [nonexistent]")
        result = runner.invoke(cli, ["workflow", "verify", str(bad)])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_verify_cycle(self, runner, tmp_path):
        cyclic = tmp_path / "cyclic.yaml"
        cyclic.write_text(
            "name: cyclic\n"
            "tasks:\n"
            "  a:\n    name: a\n    depends_on: [b]\n"
            "  b:\n    name: b\n    depends_on: [a]\n"
        )
        result = runner.invoke(cli, ["workflow", "verify", str(cyclic)])
        assert result.exit_code == 1
        assert "cycle" in result.output.lower()

    def test_verify_missing_agent(self, runner, tmp_path):
        bad_agent = tmp_path / "bad_agent.yaml"
        bad_agent.write_text(
            "name: test\n"
            "agents:\n  a1:\n    adapter: tier1\n"
            "tasks:\n  t1:\n    name: t1\n    agent: nonexistent\n"
        )
        result = runner.invoke(cli, ["workflow", "verify", str(bad_agent)])
        assert result.exit_code == 1
        assert "nonexistent" in result.output


class TestStatus:
    """agentos status"""

    def test_status_shows_workflow(self, runner, populated_db):
        result = runner.invoke(cli, ["status", "--db", populated_db])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output
        assert "research_and_implement" in result.output

    def test_status_empty_db(self, runner, db_path):
        # Create an empty DB by running SQLiteEventLog
        from agentos.kernel.event_log import SQLiteEventLog
        SQLiteEventLog(db_path)
        result = runner.invoke(cli, ["status", "--db", db_path])
        assert result.exit_code == 0
        assert "No workflows found" in result.output


class TestEvents:
    """agentos events"""

    def test_events_shows_log(self, runner, populated_db):
        result = runner.invoke(cli, ["events", "--db", populated_db])
        assert result.exit_code == 0
        assert "workflow.started" in result.output
        assert "workflow.completed" in result.output
        assert "task.state_changed" in result.output

    def test_events_filter_by_type(self, runner, populated_db):
        result = runner.invoke(cli, ["events", "--db", populated_db, "--type", "budget.consumed"])
        assert result.exit_code == 0
        assert "budget.consumed" in result.output
        # Should not contain other event types
        assert "workflow.started" not in result.output

    def test_events_empty_db(self, runner, db_path):
        from agentos.kernel.event_log import SQLiteEventLog
        SQLiteEventLog(db_path)
        result = runner.invoke(cli, ["events", "--db", db_path])
        assert result.exit_code == 0
        assert "No events found" in result.output


class TestCost:
    """agentos cost"""

    def test_cost_shows_agents(self, runner, populated_db):
        result = runner.invoke(cli, ["cost", "--db", populated_db])
        assert result.exit_code == 0
        assert "researcher" in result.output
        assert "implementer" in result.output
        assert "TOTAL" in result.output

    def test_cost_filter_by_agent(self, runner, populated_db):
        result = runner.invoke(cli, ["cost", "--db", populated_db, "--agent", "researcher"])
        assert result.exit_code == 0
        assert "researcher" in result.output
        assert "implementer" not in result.output

    def test_cost_empty_db(self, runner, db_path):
        from agentos.kernel.event_log import SQLiteEventLog
        SQLiteEventLog(db_path)
        result = runner.invoke(cli, ["cost", "--db", db_path])
        assert result.exit_code == 0
        assert "No budget data" in result.output


class TestGateCommands:
    """agentos gate list/approve/reject"""

    def test_gate_list_shows_resolved(self, runner, populated_db):
        result = runner.invoke(cli, ["gate", "list", "--db", populated_db, "--all"])
        assert result.exit_code == 0
        assert "APPROVED" in result.output

    def test_gate_list_no_pending(self, runner, populated_db):
        # All gates auto-approved during run, so no pending
        result = runner.invoke(cli, ["gate", "list", "--db", populated_db])
        assert result.exit_code == 0
        assert "No pending gates" in result.output

    def test_gate_approve_nonexistent(self, runner, populated_db):
        result = runner.invoke(cli, ["gate", "approve", "gate-bogus", "--db", populated_db])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_gate_reject_nonexistent(self, runner, populated_db):
        result = runner.invoke(cli, ["gate", "reject", "gate-bogus", "--db", populated_db])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestDemo:
    """agentos demo (existing command still works)"""

    def test_demo_default(self, runner):
        result = runner.invoke(cli, ["demo"])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output

    def test_demo_with_file(self, runner):
        result = runner.invoke(cli, ["demo", "examples/parallel_analysis.yaml"])
        assert result.exit_code == 0
        assert "SUCCEEDED" in result.output
