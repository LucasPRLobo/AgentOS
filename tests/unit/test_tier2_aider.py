"""Tests for agentos.adapters.tier2_aider — Tier 2 Aider adapter.

All tests use a mock for subprocess.run to avoid launching real Aider.
Mirrors the test_tier2_adapter.py pattern with MockCompletedProcess.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agentos.adapters.tier2_aider import (
    AiderAdapter,
    _build_command,
    _parse_usage_from_api,
)
from agentos.adapters.tier2_shared import (
    build_prompt,
    parse_manifest,
    write_predecessor_context,
)
from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskOutput,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class MockCompletedProcess:
    """Mimics subprocess.CompletedProcess."""
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def make_mock_subprocess(
    *,
    returncode: int = 0,
    stdout: str = "",
    write_manifest: dict | None = None,
) -> Any:
    """Create a mock subprocess.run that optionally writes manifest.json."""
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
        if write_manifest is not None and cwd:
            manifest_path = Path(cwd) / "manifest.json"
            manifest_path.write_text(json.dumps(write_manifest))
        return MockCompletedProcess(returncode=returncode, stdout=stdout)
    return mock_run


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
def budget_manager(event_log, seq):
    spec = BudgetSpec(
        max_tokens=100000,
        max_api_calls=100,
        max_time_seconds=300,
        max_cost_usd=5.0,
    )
    return BudgetManager(
        workflow_spec=spec,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )


@pytest.fixture
def tight_budget(event_log, seq):
    spec = BudgetSpec(max_tokens=10, max_api_calls=1)
    return BudgetManager(
        workflow_spec=spec,
        event_log=event_log,
        seq=seq,
        workflow_id="test-wf",
    )


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# Tests: Command building
# ---------------------------------------------------------------------------

class TestAiderBuildCommand:
    def test_basic_command(self):
        cmd = _build_command("Do stuff")
        assert cmd[0] == "aider"
        assert "--message" in cmd
        assert "Do stuff" in cmd
        assert "--yes-always" in cmd
        assert "--no-auto-commits" in cmd
        assert "--no-stream" in cmd
        assert "--no-pretty" in cmd

    def test_file_scoping(self):
        cmd = _build_command("Fix bug", files=["src/main.py", "src/util.py"])
        assert "--file" in cmd
        idx1 = cmd.index("--file")
        assert cmd[idx1 + 1] == "src/main.py"
        # Second --file
        remaining = cmd[idx1 + 2:]
        assert "--file" in remaining
        idx2 = remaining.index("--file")
        assert remaining[idx2 + 1] == "src/util.py"

    def test_model_flag(self):
        cmd = _build_command("Task", model="claude-sonnet-4-6")
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"

    def test_map_tokens_zero(self):
        cmd = _build_command("Task")
        assert "--map-tokens" in cmd
        idx = cmd.index("--map-tokens")
        assert cmd[idx + 1] == "0"

    def test_no_auto_commits(self):
        cmd = _build_command("Task")
        assert "--no-auto-commits" in cmd


# ---------------------------------------------------------------------------
# Tests: Prompt building (shared, but verify Aider uses it)
# ---------------------------------------------------------------------------

class TestAiderBuildPrompt:
    def test_basic_prompt(self):
        prompt = build_prompt("Do research", "You are a researcher", [])
        assert "Do research" in prompt
        assert "You are a researcher" in prompt
        assert "manifest.json" in prompt

    def test_with_predecessor_context(self):
        ctx = TaskOutput(
            task_id="prev", agent_id="a1",
            status=TaskStatus.SUCCEEDED, summary="Found things.",
            key_findings=[Finding(finding="X", confidence=Confidence.HIGH)],
            open_questions=["Y?"],
        )
        prompt = build_prompt("Continue", "Role", [ctx])
        assert "prev" in prompt
        assert "Found things." in prompt
        assert "X" in prompt
        assert "Y?" in prompt

    def test_empty_role(self):
        prompt = build_prompt("Task", "", [])
        assert "Task" in prompt
        assert "manifest.json" in prompt


# ---------------------------------------------------------------------------
# Tests: Usage parsing
# ---------------------------------------------------------------------------

class TestAiderParseUsageFromApi:
    def test_fallback_on_import_error(self):
        """When aider is not installed, returns (0, 0.0)."""
        tokens, cost = _parse_usage_from_api()
        assert tokens == 0
        assert cost == 0.0

    def test_with_metrics(self):
        """Even if aider is installed, subprocess mode returns (0, 0.0)."""
        tokens, cost = _parse_usage_from_api()
        assert isinstance(tokens, int)
        assert isinstance(cost, float)


# ---------------------------------------------------------------------------
# Tests: Adapter execute_task
# ---------------------------------------------------------------------------

class TestAiderAdapterExecute:
    def test_successful_with_manifest(self, budget_manager, workspace):
        manifest = {"summary": "Code review complete.", "findings": [], "open_questions": []}
        mock_sub = make_mock_subprocess(write_manifest=manifest)
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        output = asyncio.run(adapter.execute_task(
            task_description="Review code",
            role="Reviewer",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Code review complete."
        assert output.metrics is not None
        assert output.metrics.api_calls_made == 1

    def test_missing_manifest_retries(self, budget_manager, workspace):
        """First call succeeds but no manifest -> retry -> second call writes manifest."""
        call_count = [0]
        manifest = {"summary": "Got it on retry."}

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
            call_count[0] += 1
            if call_count[0] >= 2:
                (Path(cwd) / "manifest.json").write_text(json.dumps(manifest))
            return MockCompletedProcess()

        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        output = asyncio.run(adapter.execute_task(
            task_description="Do work",
            role="Worker",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Got it on retry."
        assert call_count[0] == 2

    def test_retries_exhausted(self, budget_manager, workspace):
        """No manifest after all retries -> FAILED."""
        mock_sub = make_mock_subprocess()  # Never writes manifest
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        output = asyncio.run(adapter.execute_task(
            task_description="Do work",
            role="Worker",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.FAILED
        assert "manifest" in output.summary.lower()
        assert output.metrics.api_calls_made == 3  # 1 + 2 retries

    def test_nonzero_exit_code(self, budget_manager, workspace):
        mock_sub = make_mock_subprocess(returncode=1)
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        output = asyncio.run(adapter.execute_task(
            task_description="Do work",
            role="Worker",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.FAILED
        assert "exit" in output.summary.lower()

    def test_timeout_returns_failed(self, budget_manager, workspace):
        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
            raise subprocess.TimeoutExpired(cmd, timeout or 120)

        adapter = AiderAdapter(
            budget_manager, "agent1", timeout=5, run_subprocess=mock_run,
        )

        output = asyncio.run(adapter.execute_task(
            task_description="Slow task",
            role="Worker",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.FAILED
        assert "timed out" in output.summary.lower()

    def test_budget_applied(self, budget_manager, workspace):
        manifest = {"summary": "Done."}
        mock_sub = make_mock_subprocess(write_manifest=manifest)
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        usage = budget_manager.usage_for("agent1")
        assert usage.api_calls_made == 1

    def test_budget_exceeded_raises(self, event_log, seq, workspace):
        """Exceeding api_calls budget raises BudgetExceededError."""
        # max_api_calls=0 means any call will exceed
        spec = BudgetSpec(max_tokens=100000, max_api_calls=0)
        zero_budget = BudgetManager(
            workflow_spec=spec,
            event_log=event_log,
            seq=seq,
            workflow_id="test-wf",
        )
        manifest = {"summary": "Done."}
        mock_sub = make_mock_subprocess(write_manifest=manifest)
        adapter = AiderAdapter(zero_budget, "agent1", run_subprocess=mock_sub)

        with pytest.raises(BudgetExceededError):
            asyncio.run(adapter.execute_task(
                task_description="Work",
                role="Role",
                workspace=workspace,
                predecessor_context=[],
                allowed_tools=[],
            ))

    def test_workspace_cwd(self, budget_manager, workspace):
        """Subprocess is launched with cwd set to workspace."""
        captured_cwd = [None]

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
            captured_cwd[0] = cwd
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess()

        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert captured_cwd[0] == str(workspace)

    def test_allowed_tools_warning(self, budget_manager, workspace, caplog):
        """Aider adapter logs a warning when allowed_tools are specified."""
        manifest = {"summary": "Done."}
        mock_sub = make_mock_subprocess(write_manifest=manifest)
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        import logging
        with caplog.at_level(logging.WARNING, logger="agentos.adapters.tier2_aider"):
            asyncio.run(adapter.execute_task(
                task_description="Work",
                role="Role",
                workspace=workspace,
                predecessor_context=[],
                allowed_tools=["Read", "Write"],
            ))

        assert any("allowedTools" in r.message for r in caplog.records)

    def test_predecessor_context_written(self, budget_manager, workspace):
        """Predecessor context files are written before launch."""
        ctx = TaskOutput(
            task_id="prev", agent_id="a1",
            status=TaskStatus.SUCCEEDED, summary="Prior work.",
        )

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
            ctx_file = Path(cwd) / ".agentos_context" / "prev.json"
            assert ctx_file.exists()
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess()

        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Continue",
            role="Role",
            workspace=workspace,
            predecessor_context=[ctx],
            allowed_tools=[],
        ))

    def test_terminate_prevents_execution(self, budget_manager, workspace):
        mock_sub = make_mock_subprocess(write_manifest={"summary": "Done."})
        adapter = AiderAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        asyncio.run(adapter.terminate())

        output = asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert output.status == TaskStatus.FAILED
        assert "terminated" in output.summary.lower()

    def test_model_passed_to_command(self, budget_manager, workspace):
        """Custom model is passed to the aider command."""
        captured_cmd = [None]

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
            captured_cmd[0] = cmd
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess()

        adapter = AiderAdapter(
            budget_manager, "agent1", model="claude-sonnet-4-6",
            run_subprocess=mock_run,
        )

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        cmd = captured_cmd[0]
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Tests: Adapter properties
# ---------------------------------------------------------------------------

class TestAiderAdapterProperties:
    def test_tier_is_2(self, budget_manager):
        adapter = AiderAdapter(budget_manager, "agent1")
        assert adapter.tier == 2
