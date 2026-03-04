"""Capability-based security schemas."""

from __future__ import annotations

from fnmatch import fnmatch

from pydantic import BaseModel, Field

from agentos.schemas.sandbox import SandboxLevel


class CapabilityGrant(BaseModel):
    """A single capability granted to an agent.

    Type prefixes:
        tool:<name>     — Allow a specific tool (e.g. "tool:file_read")
        path:<glob>     — Allow file access matching glob (e.g. "path:src/**")
        domain:<host>   — Allow network access to host (e.g. "domain:api.example.com")
        action:<name>   — Allow a named action (e.g. "action:secret:API_KEY")

    Scope restricts within the type (default "*" = full access within type).
    """

    type: str = Field(description="Capability type with prefix")
    scope: str = Field(
        default="*", description="Scope restriction within the type",
    )

    @property
    def prefix(self) -> str:
        """Extract the prefix (tool, path, domain, action)."""
        return self.type.split(":", 1)[0] if ":" in self.type else self.type

    @property
    def value(self) -> str:
        """Extract the value after the prefix."""
        return self.type.split(":", 1)[1] if ":" in self.type else ""

    def matches_tool(self, tool_name: str) -> bool:
        """Check if this grant covers the given tool name."""
        if self.prefix != "tool":
            return False
        return self.value == "*" or self.value == tool_name

    def matches_path(self, path: str) -> bool:
        """Check if this grant covers the given file path."""
        if self.prefix != "path":
            return False
        pattern = self.value
        if pattern == "*":
            return True
        return fnmatch(path, pattern)

    def matches_domain(self, domain: str) -> bool:
        """Check if this grant covers the given domain."""
        if self.prefix != "domain":
            return False
        granted = self.value
        if granted == "*":
            return True
        # Exact match or subdomain match
        return domain == granted or domain.endswith("." + granted)

    def matches_action(self, action: str) -> bool:
        """Check if this grant covers the given action."""
        if self.prefix != "action":
            return False
        if self.value == "*":
            return True
        return self.value == action or action.startswith(self.value + ":")


class CapabilityPolicy(BaseModel):
    """Complete capability policy for an agent.

    When deny_by_default is True (default), anything not explicitly granted
    is denied. When False, only explicitly denied capabilities are blocked.
    """

    agent_id: str
    grants: list[CapabilityGrant] = Field(default_factory=list)
    deny_by_default: bool = Field(
        default=True,
        description="Deny anything not explicitly granted",
    )
    sandbox: SandboxLevel = Field(
        default=SandboxLevel.NONE,
        description="Required sandbox isolation level for this agent",
    )

    def has_tool(self, tool_name: str) -> bool:
        """Check if the policy grants access to a tool."""
        if not self.deny_by_default:
            return True
        return any(g.matches_tool(tool_name) for g in self.grants)

    def has_path(self, path: str) -> bool:
        """Check if the policy grants access to a file path."""
        if not self.deny_by_default:
            return True
        return any(g.matches_path(path) for g in self.grants)

    def has_domain(self, domain: str) -> bool:
        """Check if the policy grants access to a domain."""
        if not self.deny_by_default:
            return True
        return any(g.matches_domain(domain) for g in self.grants)

    def has_action(self, action: str) -> bool:
        """Check if the policy grants a named action."""
        if not self.deny_by_default:
            return True
        return any(g.matches_action(action) for g in self.grants)
