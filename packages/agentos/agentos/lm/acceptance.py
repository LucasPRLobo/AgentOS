"""Acceptance criteria — verify agent results before marking success."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class AcceptanceResult(BaseModel):
    """Result of checking a single acceptance criterion."""

    name: str = Field(description="Name of the criterion")
    passed: bool = Field(description="Whether the criterion passed")
    message: str = Field(default="", description="Explanation of the result")


class AcceptanceCriterion(ABC):
    """Abstract base for acceptance criteria."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this criterion."""

    @abstractmethod
    def check(self, context: dict[str, Any]) -> AcceptanceResult:
        """Check if this criterion is satisfied.

        Args:
            context: Dictionary with keys like 'result', 'events', 'run_id', etc.

        Returns:
            AcceptanceResult indicating pass/fail.
        """


class AcceptanceChecker:
    """Evaluates a list of acceptance criteria."""

    def __init__(self, criteria: list[AcceptanceCriterion] | None = None) -> None:
        self._criteria = list(criteria) if criteria else []

    @property
    def criteria(self) -> list[AcceptanceCriterion]:
        return list(self._criteria)

    def check_all(self, context: dict[str, Any]) -> tuple[bool, list[AcceptanceResult]]:
        """Check all criteria.

        Returns:
            (all_passed, results) where all_passed is True only if every criterion passed.
        """
        if not self._criteria:
            return True, []

        results = [c.check(context) for c in self._criteria]
        all_passed = all(r.passed for r in results)
        return all_passed, results
