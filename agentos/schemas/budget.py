"""Budget schemas — resource limits, usage tracking, and deltas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetSpec(BaseModel):
    """Resource limits. None means unlimited for that dimension."""

    max_tokens: int | None = None
    max_api_calls: int | None = None
    max_time_seconds: float | None = None
    max_cost_usd: float | None = None
    max_concurrent_tasks: int = Field(default=4, ge=1)


class BudgetUsage(BaseModel):
    """Accumulated resource usage."""

    tokens_used: int = 0
    api_calls_made: int = 0
    time_elapsed_seconds: float = 0.0
    cost_usd: float = 0.0


class BudgetDelta(BaseModel):
    """Incremental usage from a single operation."""

    tokens: int = 0
    api_calls: int = 0
    time_seconds: float = 0.0
    cost_usd: float = 0.0
