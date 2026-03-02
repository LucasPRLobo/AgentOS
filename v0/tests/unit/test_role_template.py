"""Unit tests for RoleTemplate schema."""

import pytest
from pydantic import ValidationError

from agentos.runtime.role_template import RoleTemplate
from agentos.schemas.budget import BudgetSpec


class TestRoleTemplate:
    def test_full_creation(self) -> None:
        role = RoleTemplate(
            name="planner",
            display_name="Planning Agent",
            description="Plans experiments",
            system_prompt="You are a planning agent.",
            tool_names=["file_write", "file_read"],
            suggested_model="claude-sonnet",
            budget_profile=BudgetSpec(
                max_tokens=10_000, max_tool_calls=5,
                max_time_seconds=60.0, max_recursion_depth=1,
            ),
            max_steps=20,
            max_instances=3,
        )
        assert role.name == "planner"
        assert role.display_name == "Planning Agent"
        assert role.tool_names == ["file_write", "file_read"]
        assert role.suggested_model == "claude-sonnet"
        assert role.budget_profile.max_tokens == 10_000
        assert role.max_steps == 20
        assert role.max_instances == 3

    def test_defaults(self) -> None:
        role = RoleTemplate(
            name="basic",
            display_name="Basic Agent",
            description="A basic role",
            system_prompt="Hello.",
        )
        assert role.tool_names == []
        assert role.suggested_model == "llama3.1:latest"
        assert role.max_steps == 50
        assert role.max_instances == 1
        assert role.budget_profile.max_tokens == 50_000

    def test_budget_roundtrip(self) -> None:
        budget = BudgetSpec(
            max_tokens=5000, max_tool_calls=10,
            max_time_seconds=120.0, max_recursion_depth=2,
        )
        role = RoleTemplate(
            name="rt",
            display_name="Roundtrip",
            description="Test roundtrip",
            system_prompt="Prompt.",
            budget_profile=budget,
        )
        dumped = role.model_dump()
        restored = RoleTemplate.model_validate(dumped)
        assert restored.budget_profile == budget
        assert restored.name == "rt"

    def test_invalid_max_steps_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleTemplate(
                name="bad",
                display_name="Bad",
                description="Bad",
                system_prompt="Bad",
                max_steps=0,
            )

    def test_invalid_max_instances_raises(self) -> None:
        with pytest.raises(ValidationError):
            RoleTemplate(
                name="bad",
                display_name="Bad",
                description="Bad",
                system_prompt="Bad",
                max_instances=0,
            )
