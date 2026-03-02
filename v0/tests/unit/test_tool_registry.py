"""Tests for ToolRegistry — register, lookup, duplicate prevention."""

import pytest
from pydantic import BaseModel

from agentos.core.errors import ToolValidationError
from agentos.tools.base import BaseTool, SideEffect
from agentos.tools.registry import ToolRegistry


class DummyInput(BaseModel):
    x: str


class DummyOutput(BaseModel):
    y: str


class DummyTool(BaseTool):
    def __init__(self, tool_name: str = "dummy") -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return DummyInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return DummyOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, DummyInput)
        return DummyOutput(y=input_data.x.upper())


class TestToolRegistry:
    def test_register_and_lookup(self) -> None:
        registry = ToolRegistry()
        tool = DummyTool("my_tool")
        registry.register(tool)
        assert registry.lookup("my_tool") is tool

    def test_lookup_not_found(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(ToolValidationError, match="not registered"):
            registry.lookup("nonexistent")

    def test_duplicate_registration(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("dup"))
        with pytest.raises(ToolValidationError, match="already registered"):
            registry.register(DummyTool("dup"))

    def test_list_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("a"))
        registry.register(DummyTool("b"))
        tools = registry.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"a", "b"}

    def test_has(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool("exists"))
        assert registry.has("exists") is True
        assert registry.has("nope") is False

    def test_len(self) -> None:
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(DummyTool("one"))
        assert len(registry) == 1
