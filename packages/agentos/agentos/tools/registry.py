"""Tool registry — registration, lookup, and listing of tools."""

from __future__ import annotations

from agentos.core.errors import ToolValidationError
from agentos.tools.base import BaseTool


class ToolRegistry:
    """Registry for managing available tools.

    Enforces unique tool names and provides lookup by name.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool. Raises ToolValidationError if name is already taken."""
        if tool.name in self._tools:
            raise ToolValidationError(
                f"Tool '{tool.name}' is already registered"
            )
        self._tools[tool.name] = tool

    def lookup(self, name: str) -> BaseTool:
        """Look up a tool by name. Raises ToolValidationError if not found."""
        if name not in self._tools:
            raise ToolValidationError(f"Tool '{name}' is not registered")
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
