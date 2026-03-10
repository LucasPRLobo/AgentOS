"""Unit tests for ManagerAgentAdapter — team orchestration adapter."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.adapters.base import AgentAdapter
from agentos.adapters.manager_adapter import ManagerAgentAdapter
from agentos.kernel.budget_manager import BudgetManager
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.task import TaskOutput, TaskStatus


class StubAdapter(AgentAdapter):
    """A stub adapter for testing that returns a configurable TaskOutput."""

    def __init__(self, output: TaskOutput | None = None):
        self._output = output or TaskOutput(
            task_id="", agent_id="stub",
            status=TaskStatus.SUCCEEDED,
            summary="Stub completed.",
        )
        self._terminated = False
        self.execute_calls: list[dict] = []

    @property
    def tier(self) -> int:
        return 2

    async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
        self.execute_calls.append({
            "task_description": task_description,
            "role": role,
            "workspace": workspace,
        })
        return self._output

    async def terminate(self):
        self._terminated = True


def _make_budget_mgr() -> BudgetManager:
    """Create a minimal BudgetManager for tests."""
    from agentos.kernel.event_log import SQLiteEventLog
    from agentos.kernel.seq import SeqCounter

    event_log = SQLiteEventLog(":memory:")
    seq = SeqCounter()
    return BudgetManager(
        workflow_spec=BudgetSpec(),
        event_log=event_log, seq=seq, workflow_id="test",
    )


class TestManagerAdapterTerminated:
    def test_returns_failed_when_terminated(self, tmp_path):
        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
        )
        adapter._terminated = True
        result = asyncio.run(adapter.execute_task(
            "test", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.FAILED
        assert "terminated" in result.summary.lower()


class TestManagerAdapterLegacy:
    """Tests for legacy (teamless) manager behavior."""

    def test_legacy_delegates_to_first_downstream(self, tmp_path):
        downstream_output = TaskOutput(
            task_id="", agent_id="worker",
            status=TaskStatus.SUCCEEDED,
            summary="Worker did it.",
        )
        worker = StubAdapter(output=downstream_output)

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            downstream_adapters={"worker": worker},
            role="legacy manager",
        )
        result = asyncio.run(adapter.execute_task(
            "do the thing", "role", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.SUCCEEDED
        assert result.summary == "Worker did it."
        assert len(worker.execute_calls) == 1

    def test_legacy_no_downstream_fails(self, tmp_path):
        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            downstream_adapters={},
        )
        result = asyncio.run(adapter.execute_task(
            "do the thing", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.FAILED


class TestManagerAdapterTeamOrchestration:
    """Tests for team-based orchestration flow."""

    def test_no_manager_adapter_fails(self, tmp_path):
        """If no manager_adapter is set and no downstream, should fail."""
        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            member_adapters={"worker": StubAdapter()},
        )
        result = asyncio.run(adapter.execute_task(
            "task", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.FAILED

    def test_planning_failure_propagates(self, tmp_path):
        mgr_cc = StubAdapter(output=TaskOutput(
            task_id="", agent_id="mgr_cc",
            status=TaskStatus.FAILED,
            summary="Planning failed.",
        ))
        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=mgr_cc,
            team_name="alpha",
            member_adapters={"w1": StubAdapter()},
            member_roles={"w1": "Worker"},
        )
        result = asyncio.run(adapter.execute_task(
            "task", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.FAILED
        assert "planning" in result.summary.lower()

    def test_no_assignments_uses_manager_output(self, tmp_path):
        """If manager produces no assignments, use its output directly."""
        mgr_cc = StubAdapter(output=TaskOutput(
            task_id="", agent_id="mgr_cc",
            status=TaskStatus.SUCCEEDED,
            summary="No delegation needed, I handled it myself.",
        ))
        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=mgr_cc,
            team_name="alpha",
            member_adapters={"w1": StubAdapter()},
            member_roles={"w1": "Worker"},
        )
        result = asyncio.run(adapter.execute_task(
            "task", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.SUCCEEDED
        assert "handled it" in result.summary

    def test_full_plan_execute_review_cycle(self, tmp_path):
        """Test the full plan → execute → review cycle."""
        plan_json = json.dumps({
            "reasoning": "Need analysis",
            "assignments": [
                {"member": "analyst", "instruction": "Analyze data", "priority": 1},
            ],
        })

        # Manager CC: first call returns plan, second call returns review
        call_count = 0

        class PlanThenReviewAdapter(AgentAdapter):
            @property
            def tier(self):
                return 2

            async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Planning round
                    return TaskOutput(
                        task_id="", agent_id="mgr_cc",
                        status=TaskStatus.SUCCEEDED,
                        summary=plan_json,
                    )
                else:
                    # Review round — write manifest
                    manifest = {
                        "summary": "Team work consolidated",
                        "findings": [{"finding": "Data looks good", "confidence": "high"}],
                    }
                    (workspace / "manifest.json").write_text(json.dumps(manifest))
                    return TaskOutput(
                        task_id="", agent_id="mgr_cc",
                        status=TaskStatus.SUCCEEDED,
                        summary="Reviewed and approved.",
                    )

            async def terminate(self):
                pass

        analyst = StubAdapter(output=TaskOutput(
            task_id="", agent_id="analyst",
            status=TaskStatus.SUCCEEDED,
            summary="Analysis complete.",
        ))

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=PlanThenReviewAdapter(),
            team_name="research",
            team_description="Research team",
            member_adapters={"analyst": analyst},
            member_roles={"analyst": "Data analyst"},
        )
        result = asyncio.run(adapter.execute_task(
            "Analyze the market", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.SUCCEEDED
        assert "consolidated" in result.summary
        assert len(analyst.execute_calls) == 1
        assert "Analyze data" in analyst.execute_calls[0]["task_description"]

    def test_member_not_found_recorded(self, tmp_path):
        """If a member is not in the team, result is recorded as error."""
        plan_json = json.dumps({
            "assignments": [
                {"member": "nonexistent", "instruction": "Do stuff"},
            ],
        })

        call_count = 0

        class PlanAdapter(AgentAdapter):
            @property
            def tier(self):
                return 2

            async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return TaskOutput(
                        task_id="", agent_id="mgr_cc",
                        status=TaskStatus.SUCCEEDED,
                        summary=plan_json,
                    )
                else:
                    return TaskOutput(
                        task_id="", agent_id="mgr_cc",
                        status=TaskStatus.SUCCEEDED,
                        summary="Reviewed.",
                    )

            async def terminate(self):
                pass

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=PlanAdapter(),
            team_name="t",
            member_adapters={},
            member_roles={},
        )
        result = asyncio.run(adapter.execute_task(
            "task", "", tmp_path, [], [],
        ))
        assert result.status == TaskStatus.SUCCEEDED


class TestManagerAdapterTerminate:
    def test_terminate_cascades(self):
        mgr_cc = StubAdapter()
        worker = StubAdapter()

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=mgr_cc,
            member_adapters={"w": worker},
        )
        asyncio.run(adapter.terminate())
        assert adapter._terminated
        assert mgr_cc._terminated
        assert worker._terminated


class TestMemberToolScoping:
    """Members should receive their own tool lists, not the manager's."""

    @staticmethod
    def _make_plan_review_adapter(assignments: list[dict]):
        """Create a stub that returns an assignment plan then a review manifest."""
        call_count = 0
        plan_json = json.dumps({"reasoning": "test", "assignments": assignments})

        class _Adapter(AgentAdapter):
            @property
            def tier(self):
                return 2

            async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return TaskOutput(
                        task_id="", agent_id="mgr_cc",
                        status=TaskStatus.SUCCEEDED, summary=plan_json,
                    )
                manifest = {"summary": "Done", "findings": []}
                (workspace / "manifest.json").write_text(json.dumps(manifest))
                return TaskOutput(
                    task_id="", agent_id="mgr_cc",
                    status=TaskStatus.SUCCEEDED, summary="Reviewed.",
                )

            async def terminate(self):
                pass

        return _Adapter()

    def test_member_gets_own_tools(self, tmp_path):
        """Member adapter receives member-specific tools, not fallback."""

        class ToolTrackingAdapter(StubAdapter):
            def __init__(self):
                super().__init__()
                self.received_tools: list[str] | None = None

            async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
                self.received_tools = allowed_tools
                return self._output

        worker = ToolTrackingAdapter()
        mgr_cc = self._make_plan_review_adapter([
            {"member": "analyst", "instruction": "analyze data", "priority": 1}
        ])

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=mgr_cc,
            member_adapters={"analyst": worker},
            member_roles={"analyst": "Data analyst"},
            member_tools={"analyst": ["Read", "Bash", "Glob", "Grep"]},
        )

        output = asyncio.run(adapter.execute_task(
            task_description="Run analysis",
            role="manager",
            workspace=tmp_path,
            predecessor_context=[],
            allowed_tools=["Read", "Write"],  # Manager's tools
        ))

        # Member should get its own tools, not the manager's ["Read", "Write"]
        assert worker.received_tools == ["Read", "Bash", "Glob", "Grep"]

    def test_member_falls_back_to_task_tools(self, tmp_path):
        """If member has no specific tools, falls back to task-level tools."""

        class ToolTrackingAdapter(StubAdapter):
            def __init__(self):
                super().__init__()
                self.received_tools: list[str] | None = None

            async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools):
                self.received_tools = allowed_tools
                return self._output

        worker = ToolTrackingAdapter()
        mgr_cc = self._make_plan_review_adapter([
            {"member": "writer", "instruction": "write report", "priority": 1}
        ])

        adapter = ManagerAgentAdapter(
            budget_manager=_make_budget_mgr(),
            agent_id="mgr",
            manager_adapter=mgr_cc,
            member_adapters={"writer": worker},
            member_roles={"writer": "Writer"},
            # No member_tools for "writer" — should fall back
        )

        output = asyncio.run(adapter.execute_task(
            task_description="Write report",
            role="manager",
            workspace=tmp_path,
            predecessor_context=[],
            allowed_tools=["Read", "Write", "Edit"],
        ))

        # Should fall back to task-level tools
        assert worker.received_tools == ["Read", "Write", "Edit"]
