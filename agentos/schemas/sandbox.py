"""Sandbox isolation configuration schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SandboxLevel(StrEnum):
    NONE = "none"  # V1 default — process-level only
    NAMESPACE = "namespace"  # Linux namespace isolation (PID, mount, network)
    CONTAINER = "container"  # Docker-based full isolation


class SandboxConfig(BaseModel):
    """Sandbox configuration for an agent."""

    level: SandboxLevel = Field(default=SandboxLevel.NONE)
    network_enabled: bool = Field(default=True, description="Allow network access within sandbox")
    filesystem_readonly: bool = Field(default=False, description="Mount workspace as read-only")
    memory_limit_mb: int = Field(default=0, ge=0, description="Memory limit in MB (0 = unlimited)")
    cpu_limit: float = Field(default=0.0, ge=0.0, description="CPU cores limit (0 = unlimited)")
    allowed_paths: list[str] = Field(
        default_factory=list,
        description="Paths accessible within sandbox (workspace always included)",
    )
