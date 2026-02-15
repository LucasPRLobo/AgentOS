"""Domain pack registry — plugin discovery and manifest management."""

from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel, Field

from agentos.runtime.role_template import RoleTemplate
from agentos.tools.base import BaseTool


class ToolManifestEntry(BaseModel):
    """Declares a tool available in a domain pack."""

    name: str = Field(description="Tool name as registered in ToolRegistry")
    description: str = Field(description="Human-readable description of what the tool does")
    side_effect: str = Field(description="Side-effect classification: PURE, READ, WRITE, DESTRUCTIVE")
    factory: str = Field(
        description=(
            "Dotted import path to the tool class, e.g. 'labos.tools.dataset:DatasetTool'"
        )
    )


class WorkflowManifestEntry(BaseModel):
    """Declares a workflow available in a domain pack."""

    name: str = Field(description="Workflow identifier")
    description: str = Field(description="Human-readable description")
    factory: str = Field(
        description=(
            "Dotted import path to the workflow builder function, "
            "e.g. 'labos.workflows.multi_agent_research:build_research_dag'"
        )
    )
    default_roles: list[str] = Field(
        default_factory=list,
        description="Role template names used by this workflow",
    )


class DomainPackManifest(BaseModel):
    """Declares a domain pack's capabilities — tools, roles, and workflows."""

    name: str = Field(description="Unique pack identifier (e.g. 'labos', 'codeos')")
    display_name: str = Field(description="Human-readable name (e.g. 'Lab Research OS')")
    description: str = Field(description="What this domain pack provides")
    version: str = Field(description="Semantic version string")
    tools: list[ToolManifestEntry] = Field(default_factory=list)
    role_templates: list[RoleTemplate] = Field(default_factory=list)
    workflows: list[WorkflowManifestEntry] = Field(default_factory=list)


def _import_from_path(dotted_path: str) -> Any:
    """Import a class or function from a 'module.path:ClassName' string."""
    if ":" not in dotted_path:
        raise ValueError(
            f"Invalid factory path '{dotted_path}': expected 'module.path:ClassName'"
        )
    module_path, attr_name = dotted_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


class DomainRegistry:
    """Registry for discovering and loading domain packs.

    Domain packs register themselves via DomainPackManifest. The registry
    provides lookup by name and dynamic tool instantiation.
    """

    def __init__(self) -> None:
        self._packs: dict[str, DomainPackManifest] = {}

    def register(self, manifest: DomainPackManifest) -> None:
        """Register a domain pack. Raises ValueError if name already taken."""
        if manifest.name in self._packs:
            raise ValueError(f"Domain pack '{manifest.name}' is already registered")
        self._packs[manifest.name] = manifest

    def list_packs(self) -> list[DomainPackManifest]:
        """Return all registered domain packs."""
        return list(self._packs.values())

    def get_pack(self, name: str) -> DomainPackManifest:
        """Look up a domain pack by name. Raises KeyError if not found."""
        if name not in self._packs:
            raise KeyError(f"Domain pack '{name}' is not registered")
        return self._packs[name]

    def has_pack(self, name: str) -> bool:
        """Check if a domain pack is registered."""
        return name in self._packs

    def load_tool(self, entry: ToolManifestEntry, **kwargs: Any) -> BaseTool:
        """Dynamically import and instantiate a tool from its manifest entry.

        Additional keyword arguments are passed to the tool constructor.
        """
        tool_class = _import_from_path(entry.factory)
        return tool_class(**kwargs)

    def get_role_template(self, pack_name: str, role_name: str) -> RoleTemplate:
        """Look up a role template by pack and role name.

        Raises KeyError if not found.
        """
        pack = self.get_pack(pack_name)
        for role in pack.role_templates:
            if role.name == role_name:
                return role
        raise KeyError(f"Role '{role_name}' not found in domain pack '{pack_name}'")

    def __len__(self) -> int:
        return len(self._packs)
