"""Marketplace schemas for workflow templates."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TemplateMetrics(BaseModel):
    """Verified performance metrics for a marketplace template."""

    avg_cost_usd: float = Field(default=0.0, ge=0.0)
    avg_duration_seconds: float = Field(default=0.0, ge=0.0)
    approval_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    completion_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    total_runs: int = Field(default=0, ge=0)


class MarketplaceTemplate(BaseModel):
    """A workflow template in the marketplace."""

    template_id: str
    name: str
    description: str = ""
    author: str = ""
    category: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    workflow_yaml: str
    metrics: TemplateMetrics = Field(default_factory=TemplateMetrics)
    verified: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())
    downloads: int = Field(default=0, ge=0)
