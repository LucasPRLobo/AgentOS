"""Tests for adapter validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentos.adapters.base import ADAPTER_API_VERSION, AgentAdapter, validate_adapter
from agentos.schemas.task import TaskMetrics, TaskOutput, TaskStatus


class ValidAdapter(AgentAdapter):
    @property
    def tier(self) -> int:
        return 2

    async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools, progress_callback=None):
        return TaskOutput(
            task_id="", agent_id="test", status=TaskStatus.SUCCEEDED,
            summary="done", metrics=TaskMetrics(tokens_consumed=0, api_calls_made=0, execution_time_seconds=0),
        )

    async def terminate(self):
        pass


class BadTierAdapter(AgentAdapter):
    @property
    def tier(self) -> int:
        return 99

    async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools, progress_callback=None):
        return TaskOutput(
            task_id="", agent_id="test", status=TaskStatus.SUCCEEDED,
            summary="done", metrics=TaskMetrics(tokens_consumed=0, api_calls_made=0, execution_time_seconds=0),
        )

    async def terminate(self):
        pass


class Tier1Adapter(AgentAdapter):
    @property
    def tier(self) -> int:
        return 1

    async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools, progress_callback=None):
        return TaskOutput(
            task_id="", agent_id="test", status=TaskStatus.SUCCEEDED,
            summary="done", metrics=TaskMetrics(tokens_consumed=0, api_calls_made=0, execution_time_seconds=0),
        )

    async def terminate(self):
        pass


class Tier3Adapter(AgentAdapter):
    @property
    def tier(self) -> int:
        return 3

    async def execute_task(self, task_description, role, workspace, predecessor_context, allowed_tools, progress_callback=None):
        return TaskOutput(
            task_id="", agent_id="test", status=TaskStatus.SUCCEEDED,
            summary="done", metrics=TaskMetrics(tokens_consumed=0, api_calls_made=0, execution_time_seconds=0),
        )

    async def terminate(self):
        pass


class TestAdapterAPIVersion:
    def test_version_defined(self):
        assert ADAPTER_API_VERSION == "1.0"

    def test_version_is_string(self):
        assert isinstance(ADAPTER_API_VERSION, str)


class TestValidateAdapter:
    def test_valid_adapter(self):
        adapter = ValidAdapter()
        issues = validate_adapter(adapter)
        assert issues == []

    def test_not_an_adapter(self):
        issues = validate_adapter("not an adapter")
        assert len(issues) == 1
        assert "AgentAdapter" in issues[0]

    def test_bad_tier(self):
        adapter = BadTierAdapter()
        issues = validate_adapter(adapter)
        assert any("tier" in issue for issue in issues)

    def test_tier1_valid(self):
        adapter = Tier1Adapter()
        issues = validate_adapter(adapter)
        assert issues == []

    def test_tier3_valid(self):
        adapter = Tier3Adapter()
        issues = validate_adapter(adapter)
        assert issues == []

    def test_none_not_adapter(self):
        issues = validate_adapter(None)
        assert len(issues) == 1
        assert "AgentAdapter" in issues[0]

    def test_dict_not_adapter(self):
        issues = validate_adapter({"tier": 1})
        assert len(issues) == 1
        assert "AgentAdapter" in issues[0]

    def test_integer_not_adapter(self):
        issues = validate_adapter(42)
        assert len(issues) == 1
        assert "AgentAdapter" in issues[0]


class TestAdapterABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AgentAdapter()

    def test_valid_adapter_is_instance(self):
        adapter = ValidAdapter()
        assert isinstance(adapter, AgentAdapter)

    def test_tier_property(self):
        adapter = ValidAdapter()
        assert adapter.tier == 2

    def test_execute_task_is_coroutine(self):
        import asyncio
        adapter = ValidAdapter()
        result = adapter.execute_task("test", "role", Path("/tmp"), [], [])
        assert asyncio.iscoroutine(result)
        # Clean up the coroutine to avoid warnings
        result.close()

    def test_terminate_is_coroutine(self):
        import asyncio
        adapter = ValidAdapter()
        result = adapter.terminate()
        assert asyncio.iscoroutine(result)
        result.close()
