"""EvalCase — abstract evaluation case and result schemas."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvalOutcome(StrEnum):
    """Possible outcomes of an evaluation case."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class EvalResult(BaseModel):
    """Result of running a single evaluation case."""

    case_name: str
    outcome: EvalOutcome
    duration_seconds: float = Field(ge=0.0)
    error_message: str | None = None
    error_type: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvalCase(ABC):
    """Abstract base class for evaluation cases.

    Each case defines a name, setup/teardown, and a run method that
    produces an EvalResult.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this eval case."""

    @property
    def tags(self) -> list[str]:
        """Optional tags for filtering eval cases."""
        return []

    def setup(self) -> None:
        """Optional setup before running the case."""

    def teardown(self) -> None:
        """Optional cleanup after running the case."""

    @abstractmethod
    def run(self) -> EvalResult:
        """Execute the evaluation and return a result."""
