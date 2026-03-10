"""Benchmarking schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class BenchmarkStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BenchmarkResult(BaseModel):
    """Result from a single backend run."""

    backend: str
    status: BenchmarkStatus = BenchmarkStatus.PENDING
    duration_seconds: float = 0.0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    output_summary: str = ""
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BenchmarkRun(BaseModel):
    """A complete benchmark run across multiple backends."""

    run_id: str
    task_description: str
    backends: list[str]
    results: dict[str, BenchmarkResult] = Field(default_factory=dict)
    status: BenchmarkStatus = BenchmarkStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now())


class BenchmarkConfig(BaseModel):
    """Configuration for benchmark runs."""

    backends: list[str] = Field(default_factory=lambda: ["tier1-claude", "tier1-openai"])
    timeout_seconds: int = Field(default=300, ge=1)
    quality_evaluator: str = Field(default="auto", description="auto or manual")
