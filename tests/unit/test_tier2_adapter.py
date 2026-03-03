"""Tests for agentos.adapters.tier2_claude_code — Tier 2 Claude Code adapter.

All tests use a mock for subprocess.run to avoid launching real Claude Code.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentos.adapters.tier2_claude_code import (
    ClaudeCodeAdapter,
    _build_command,
    _build_env,
    _build_prompt,
    _manifest_to_task_output,
    _parse_manifest,
    _parse_usage,
    _write_predecessor_context,
)
from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskMetrics,
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
    stdout: str = "{}"
    stderr: str = ""


def make_mock_subprocess(
    *,
    returncode: int = 0,
    stdout: str = "{}",
    write_manifest: dict | None = None,
) -> Any:
    """Create a mock subprocess.run that optionally writes manifest.json."""
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
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
# Tests: Prompt building
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_basic_prompt(self):
        prompt = _build_prompt("Do research", "You are a researcher", [])
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
        prompt = _build_prompt("Continue", "Role", [ctx])
        assert "prev" in prompt
        assert "Found things." in prompt
        assert "X" in prompt
        assert "Y?" in prompt

    def test_empty_role(self):
        prompt = _build_prompt("Task", "", [])
        assert "Task" in prompt
        assert "manifest.json" in prompt


# ---------------------------------------------------------------------------
# Tests: Command building
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def test_basic_command(self):
        cmd = _build_command("Do stuff", [])
        assert cmd[:2] == ["claude", "--print"]
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "-p" in cmd
        assert "Do stuff" in cmd

    def test_with_allowed_tools(self):
        cmd = _build_command("Task", ["Read", "Write"])
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Read,Write"

    def test_empty_tools_no_flag(self):
        cmd = _build_command("Task", [])
        assert "--allowedTools" not in cmd


# ---------------------------------------------------------------------------
# Tests: Environment
# ---------------------------------------------------------------------------

class TestBuildEnv:
    def test_strips_claudecode(self, monkeypatch):
        monkeypatch.setenv("CLAUDECODE", "1")
        env = _build_env()
        assert "CLAUDECODE" not in env

    def test_preserves_other_vars(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        env = _build_env()
        assert env["MY_VAR"] == "hello"


# ---------------------------------------------------------------------------
# Tests: Usage parsing
# ---------------------------------------------------------------------------

class TestParseUsage:
    def test_with_usage_data(self):
        output = {"usage": {"input_tokens": 500, "output_tokens": 200}}
        tokens, cost = _parse_usage(output)
        assert tokens == 700
        assert cost > 0

    def test_with_explicit_cost(self):
        output = {"usage": {"input_tokens": 100, "output_tokens": 50}, "cost_usd": 0.05}
        tokens, cost = _parse_usage(output)
        assert tokens == 150
        assert cost == 0.05

    def test_empty_output(self):
        tokens, cost = _parse_usage({})
        assert tokens == 0
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Tests: Manifest parsing
# ---------------------------------------------------------------------------

class TestParseManifest:
    def test_valid_manifest(self, workspace):
        (workspace / "manifest.json").write_text(json.dumps({
            "summary": "Done.", "findings": [], "open_questions": [],
        }))
        result = _parse_manifest(workspace)
        assert result is not None
        assert result["summary"] == "Done."

    def test_missing_manifest(self, workspace):
        assert _parse_manifest(workspace) is None

    def test_invalid_json(self, workspace):
        (workspace / "manifest.json").write_text("not json{{{")
        assert _parse_manifest(workspace) is None


# ---------------------------------------------------------------------------
# Tests: Manifest to TaskOutput conversion
# ---------------------------------------------------------------------------

class TestManifestToTaskOutput:
    def test_full_manifest(self):
        manifest = {
            "summary": "Found 3 issues.",
            "findings": [
                {"finding": "Bug A", "confidence": "high", "sources": ["log.txt"]},
                {"finding": "Bug B", "confidence": "low"},
            ],
            "open_questions": ["Is C affected?"],
        }
        output = _manifest_to_task_output(manifest, "t1", "a1", TaskMetrics())
        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Found 3 issues."
        assert len(output.key_findings) == 2
        assert output.key_findings[0].confidence == Confidence.HIGH
        assert output.open_questions == ["Is C affected?"]

    def test_minimal_manifest(self):
        output = _manifest_to_task_output({"summary": "Done."}, "t1", "a1", TaskMetrics())
        assert output.status == TaskStatus.SUCCEEDED
        assert output.key_findings == []


# ---------------------------------------------------------------------------
# Tests: Predecessor context writing
# ---------------------------------------------------------------------------

class TestWritePredecessorContext:
    def test_writes_context_files(self, workspace):
        ctx = TaskOutput(
            task_id="prev", agent_id="a1",
            status=TaskStatus.SUCCEEDED, summary="Done.",
        )
        _write_predecessor_context(workspace, [ctx])
        ctx_file = workspace / ".agentos_context" / "prev.json"
        assert ctx_file.exists()
        data = json.loads(ctx_file.read_text())
        assert data["task_id"] == "prev"

    def test_no_predecessors_no_dir(self, workspace):
        _write_predecessor_context(workspace, [])
        assert not (workspace / ".agentos_context").exists()


# ---------------------------------------------------------------------------
# Tests: Adapter execute_task
# ---------------------------------------------------------------------------

class TestClaudeCodeAdapterExecute:
    def test_successful_execution_with_manifest(self, budget_manager, workspace):
        manifest = {"summary": "Research complete.", "findings": [], "open_questions": []}
        mock_sub = make_mock_subprocess(
            stdout=json.dumps({"usage": {"input_tokens": 300, "output_tokens": 100}}),
            write_manifest=manifest,
        )
        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        output = asyncio.run(adapter.execute_task(
            task_description="Research topic X",
            role="Researcher",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=["Read", "Write"],
        ))

        assert output.status == TaskStatus.SUCCEEDED
        assert output.summary == "Research complete."
        assert output.metrics is not None
        assert output.metrics.api_calls_made == 1

    def test_missing_manifest_retries(self, budget_manager, workspace):
        """First call succeeds but no manifest → retry → second call writes manifest."""
        call_count = [0]
        manifest = {"summary": "Got it on retry."}

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            call_count[0] += 1
            if call_count[0] >= 2:
                # Second attempt writes manifest
                (Path(cwd) / "manifest.json").write_text(json.dumps(manifest))
            return MockCompletedProcess(stdout="{}")

        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_run)

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

    def test_all_retries_exhausted(self, budget_manager, workspace):
        """No manifest after all retries → FAILED."""
        mock_sub = make_mock_subprocess(stdout="{}")  # Never writes manifest
        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

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
        mock_sub = make_mock_subprocess(returncode=1, stdout="{}")
        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

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
        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            raise subprocess.TimeoutExpired(cmd, timeout or 120)

        adapter = ClaudeCodeAdapter(
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

    def test_budget_applied_from_usage(self, budget_manager, workspace):
        manifest = {"summary": "Done."}
        mock_sub = make_mock_subprocess(
            stdout=json.dumps({"usage": {"input_tokens": 1000, "output_tokens": 500}}),
            write_manifest=manifest,
        )
        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        usage = budget_manager.usage_for("agent1")
        assert usage.tokens_used == 1500
        assert usage.api_calls_made == 1

    def test_budget_exceeded_raises(self, tight_budget, workspace):
        mock_sub = make_mock_subprocess(
            stdout=json.dumps({"usage": {"input_tokens": 100, "output_tokens": 50}}),
            write_manifest={"summary": "Done."},
        )
        adapter = ClaudeCodeAdapter(tight_budget, "agent1", run_subprocess=mock_sub)

        with pytest.raises(BudgetExceededError):
            asyncio.run(adapter.execute_task(
                task_description="Work",
                role="Role",
                workspace=workspace,
                predecessor_context=[],
                allowed_tools=[],
            ))

    def test_workspace_scoping_cwd(self, budget_manager, workspace):
        """Subprocess is launched with cwd set to workspace."""
        captured_cwd = [None]

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            captured_cwd[0] = cwd
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess(stdout="{}")

        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert captured_cwd[0] == str(workspace)

    def test_claudecode_env_stripped(self, budget_manager, workspace, monkeypatch):
        """CLAUDECODE env var is NOT passed to subprocess."""
        monkeypatch.setenv("CLAUDECODE", "1")
        captured_env = [None]

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            captured_env[0] = env
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess(stdout="{}")

        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=[],
        ))

        assert "CLAUDECODE" not in captured_env[0]

    def test_allowed_tools_in_command(self, budget_manager, workspace):
        """--allowedTools flag is passed with the correct tools."""
        captured_cmd = [None]

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            captured_cmd[0] = cmd
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess(stdout="{}")

        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Work",
            role="Role",
            workspace=workspace,
            predecessor_context=[],
            allowed_tools=["Read", "Write"],
        ))

        cmd = captured_cmd[0]
        assert "--allowedTools" in cmd
        idx = cmd.index("--allowedTools")
        assert cmd[idx + 1] == "Read,Write"

    def test_predecessor_context_written(self, budget_manager, workspace):
        """Predecessor context files are written before launch."""
        ctx = TaskOutput(
            task_id="prev", agent_id="a1",
            status=TaskStatus.SUCCEEDED, summary="Prior work.",
        )

        def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            # Verify context was written before subprocess ran
            ctx_file = Path(cwd) / ".agentos_context" / "prev.json"
            assert ctx_file.exists()
            (Path(cwd) / "manifest.json").write_text('{"summary": "Done."}')
            return MockCompletedProcess(stdout="{}")

        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_run)

        asyncio.run(adapter.execute_task(
            task_description="Continue",
            role="Role",
            workspace=workspace,
            predecessor_context=[ctx],
            allowed_tools=[],
        ))

    def test_terminate_prevents_execution(self, budget_manager, workspace):
        mock_sub = make_mock_subprocess(write_manifest={"summary": "Done."})
        adapter = ClaudeCodeAdapter(budget_manager, "agent1", run_subprocess=mock_sub)

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


class TestClaudeCodeAdapterProperties:
    def test_tier_is_2(self, budget_manager):
        adapter = ClaudeCodeAdapter(budget_manager, "agent1")
        assert adapter.tier == 2
