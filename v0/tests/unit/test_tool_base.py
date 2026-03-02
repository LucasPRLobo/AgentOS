"""Tests for BaseTool — validation, execution, side-effect classification."""

import pytest
from pydantic import BaseModel, ValidationError

from agentos.tools.base import BaseTool, SideEffect


class AddInput(BaseModel):
    a: int
    b: int


class AddOutput(BaseModel):
    result: int


class AddTool(BaseTool):
    @property
    def name(self) -> str:
        return "add"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AddInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return AddOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, AddInput)
        return AddOutput(result=input_data.a + input_data.b)


class TestBaseTool:
    def test_execute(self) -> None:
        tool = AddTool()
        inp = AddInput(a=2, b=3)
        out = tool.execute(inp)
        assert isinstance(out, AddOutput)
        assert out.result == 5

    def test_properties(self) -> None:
        tool = AddTool()
        assert tool.name == "add"
        assert tool.version == "1.0.0"
        assert tool.side_effect == SideEffect.PURE

    def test_validate_input(self) -> None:
        tool = AddTool()
        validated = tool.validate_input({"a": 1, "b": 2})
        assert isinstance(validated, AddInput)
        assert validated.a == 1

    def test_validate_input_invalid(self) -> None:
        tool = AddTool()
        with pytest.raises(ValidationError):
            tool.validate_input({"a": "not_an_int", "b": 2})

    def test_validate_output(self) -> None:
        tool = AddTool()
        validated = tool.validate_output({"result": 42})
        assert isinstance(validated, AddOutput)

    def test_validate_output_invalid(self) -> None:
        tool = AddTool()
        with pytest.raises(ValidationError):
            tool.validate_output({"result": "not_an_int"})


class TestSideEffect:
    def test_enum_values(self) -> None:
        assert SideEffect.PURE == "PURE"
        assert SideEffect.READ == "READ"
        assert SideEffect.WRITE == "WRITE"
        assert SideEffect.DESTRUCTIVE == "DESTRUCTIVE"

    def test_all_values(self) -> None:
        assert len(SideEffect) == 4
