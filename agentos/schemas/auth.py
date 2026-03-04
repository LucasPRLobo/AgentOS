"""Authentication and authorization schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    ADMIN = "admin"  # Full access + user management
    OPERATOR = "operator"  # Run workflows, resolve gates
    VIEWER = "viewer"  # Read-only dashboard access


class User(BaseModel):
    """A registered user."""

    user_id: str
    username: str
    role: Role = Field(default=Role.OPERATOR)
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class APIKey(BaseModel):
    """An API key for programmatic access."""

    key_id: str
    user_id: str
    name: str = Field(description="Human-readable key name")
    prefix: str = Field(description="First 8 chars of key for identification")
    role: Role = Field(default=Role.OPERATOR)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


class AuthConfig(BaseModel):
    """Authentication configuration."""

    enabled: bool = Field(default=False, description="Auth disabled by default (local-first)")
    jwt_secret: str = Field(default="", description="JWT signing secret")
    token_expiry_hours: int = Field(default=24)
    allow_anonymous: bool = Field(default=True, description="Allow unauthenticated local access")
