"""Tests for tool description builder."""

from __future__ import annotations

from pydantic import BaseModel

from agentos.lm.tool_descriptions import build_tool_descriptions
from agentos.tools.base import BaseTool, SideEffect
from agentos.tools.registry import ToolRegistry


class _EchoInput(BaseModel):
    message: str


class _EchoOutput(BaseModel):
    echoed: str


class _EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return _EchoInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return _EchoOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, _EchoInput)
        return _EchoOutput(echoed=input_data.message)


class TestBuildToolDescriptions:
    def test_empty_registry(self) -> None:
        registry = ToolRegistry()
        result = build_tool_descriptions(registry)
        assert result == "No tools available."

    def test_registry_with_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(_EchoTool())
        result = build_tool_descriptions(registry)
        assert "## echo (v1.0.0)" in result
        assert "Side effect: PURE" in result
        assert '"message"' in result  # from input schema
        assert '"echoed"' in result  # from output schema

    def test_multiple_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(_EchoTool())

        # Create a second tool with a different name
        class _AddTool(BaseTool):
            @property
            def name(self) -> str:
                return "add"

            @property
            def version(self) -> str:
                return "0.1.0"

            @property
            def input_schema(self) -> type[BaseModel]:
                return _EchoInput

            @property
            def output_schema(self) -> type[BaseModel]:
                return _EchoOutput

            @property
            def side_effect(self) -> SideEffect:
                return SideEffect.READ

            def execute(self, input_data: BaseModel) -> BaseModel:
                return _EchoOutput(echoed="ok")

        registry.register(_AddTool())
        result = build_tool_descriptions(registry)
        assert "## echo" in result
        assert "## add" in result
