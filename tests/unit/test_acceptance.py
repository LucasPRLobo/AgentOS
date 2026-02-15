"""Tests for acceptance criteria checking."""

from __future__ import annotations

from typing import Any

from agentos.lm.acceptance import (
    AcceptanceChecker,
    AcceptanceCriterion,
    AcceptanceResult,
)


class _AlwaysPass(AcceptanceCriterion):
    @property
    def name(self) -> str:
        return "always_pass"

    def check(self, context: dict[str, Any]) -> AcceptanceResult:
        return AcceptanceResult(name=self.name, passed=True, message="OK")


class _AlwaysFail(AcceptanceCriterion):
    @property
    def name(self) -> str:
        return "always_fail"

    def check(self, context: dict[str, Any]) -> AcceptanceResult:
        return AcceptanceResult(name=self.name, passed=False, message="Not OK")


class _ResultContains(AcceptanceCriterion):
    def __init__(self, keyword: str) -> None:
        self._keyword = keyword

    @property
    def name(self) -> str:
        return f"result_contains_{self._keyword}"

    def check(self, context: dict[str, Any]) -> AcceptanceResult:
        result = context.get("result", "")
        passed = self._keyword in result
        return AcceptanceResult(
            name=self.name,
            passed=passed,
            message=f"Found '{self._keyword}'" if passed else f"Missing '{self._keyword}'",
        )


class TestAcceptanceChecker:
    def test_all_pass(self) -> None:
        checker = AcceptanceChecker([_AlwaysPass(), _AlwaysPass()])
        all_passed, results = checker.check_all({})
        assert all_passed is True
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_one_fails(self) -> None:
        checker = AcceptanceChecker([_AlwaysPass(), _AlwaysFail()])
        all_passed, results = checker.check_all({})
        assert all_passed is False
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_empty_criteria_passes(self) -> None:
        checker = AcceptanceChecker()
        all_passed, results = checker.check_all({})
        assert all_passed is True
        assert results == []

    def test_context_passed_to_criteria(self) -> None:
        checker = AcceptanceChecker([_ResultContains("success")])

        passed, results = checker.check_all({"result": "task success"})
        assert passed is True

        passed, results = checker.check_all({"result": "task failed"})
        assert passed is False
