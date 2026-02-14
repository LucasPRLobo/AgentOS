"""Unit tests for SessionConfig and AgentSlotConfig schemas."""

import pytest
from pydantic import ValidationError

from agentos.schemas.budget import BudgetSpec
from agentos.schemas.session import AgentSlotConfig, SessionConfig


class TestAgentSlotConfig:
    def test_creation(self) -> None:
        slot = AgentSlotConfig(role="planner", model="llama3.1:latest")
        assert slot.role == "planner"
        assert slot.model == "llama3.1:latest"
        assert slot.count == 1
        assert slot.budget_override is None
        assert slot.system_prompt_override is None

    def test_with_overrides(self) -> None:
        budget = BudgetSpec(
            max_tokens=5000, max_tool_calls=10,
            max_time_seconds=60.0, max_recursion_depth=1,
        )
        slot = AgentSlotConfig(
            role="coder",
            model="claude-sonnet",
            count=3,
            budget_override=budget,
            system_prompt_override="Custom prompt",
        )
        assert slot.count == 3
        assert slot.budget_override is not None
        assert slot.budget_override.max_tokens == 5000
        assert slot.system_prompt_override == "Custom prompt"

    def test_invalid_count_raises(self) -> None:
        with pytest.raises(ValidationError):
            AgentSlotConfig(role="bad", model="bad", count=0)


class TestSessionConfig:
    def test_creation(self) -> None:
        config = SessionConfig(
            domain_pack="labos",
            workflow="multi_agent_research",
            agents=[
                AgentSlotConfig(role="planner", model="llama3.1:latest"),
                AgentSlotConfig(role="reviewer", model="llama3.1:latest"),
            ],
            workspace_root="/tmp/test_workspace",
        )
        assert config.domain_pack == "labos"
        assert config.workflow == "multi_agent_research"
        assert len(config.agents) == 2
        assert config.max_parallel == 1
        assert config.task_description == ""
        assert config.session_id  # auto-generated

    def test_auto_generated_session_id(self) -> None:
        c1 = SessionConfig(
            domain_pack="labos", workflow="test",
            agents=[], workspace_root="/tmp/w",
        )
        c2 = SessionConfig(
            domain_pack="labos", workflow="test",
            agents=[], workspace_root="/tmp/w",
        )
        assert c1.session_id != c2.session_id

    def test_custom_session_id(self) -> None:
        config = SessionConfig(
            session_id="custom-123",
            domain_pack="codeos",
            workflow="agent_coding",
            agents=[AgentSlotConfig(role="coder", model="llama3.1:latest")],
            workspace_root="/tmp/w",
        )
        assert config.session_id == "custom-123"

    def test_invalid_max_parallel_raises(self) -> None:
        with pytest.raises(ValidationError):
            SessionConfig(
                domain_pack="labos", workflow="test",
                agents=[], workspace_root="/tmp/w",
                max_parallel=0,
            )

    def test_roundtrip(self) -> None:
        config = SessionConfig(
            domain_pack="labos",
            workflow="multi_agent_research",
            agents=[AgentSlotConfig(role="planner", model="llama3.1:latest")],
            workspace_root="/tmp/w",
            max_parallel=2,
            task_description="Run an experiment",
        )
        dumped = config.model_dump()
        restored = SessionConfig.model_validate(dumped)
        assert restored.domain_pack == config.domain_pack
        assert restored.session_id == config.session_id
        assert len(restored.agents) == 1
