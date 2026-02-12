"""Tool substrate — base tool class and side-effect classification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class SideEffect(StrEnum):
    """Classification of a tool's side effects."""

    PURE = "PURE"
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class BaseTool(ABC):
    """Abstract base class for all AgentOS tools.

    Tools are the syscalls of AgentOS. Each tool declares typed input/output
    schemas, a side-effect class, and an execute method.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this tool."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version of this tool."""

    @property
    @abstractmethod
    def input_schema(self) -> type[BaseModel]:
        """Pydantic model class for validating input."""

    @property
    @abstractmethod
    def output_schema(self) -> type[BaseModel]:
        """Pydantic model class for validating output."""

    @property
    @abstractmethod
    def side_effect(self) -> SideEffect:
        """Side-effect classification of this tool."""

    @abstractmethod
    def execute(self, input_data: BaseModel) -> BaseModel:
        """Execute the tool with validated input. Returns validated output."""

    def validate_input(self, raw: dict[str, Any]) -> BaseModel:
        """Validate raw input dict against the input schema."""
        return self.input_schema.model_validate(raw)

    def validate_output(self, raw: dict[str, Any]) -> BaseModel:
        """Validate raw output dict against the output schema."""
        return self.output_schema.model_validate(raw)
