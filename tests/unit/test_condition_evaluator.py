"""Tests for condition_evaluator — safe expression evaluation."""

from __future__ import annotations

import pytest

from agentos.kernel.condition_evaluator import (
    ConditionEvaluationError,
    evaluate_condition,
)
from agentos.schemas.task import Confidence, Finding, FileReference, TaskOutput, TaskStatus


def _make_output(**overrides) -> TaskOutput:
    defaults = {
        "task_id": "test-task",
        "agent_id": "test-agent",
        "status": TaskStatus.SUCCEEDED,
        "summary": "All tests passed successfully",
    }
    defaults.update(overrides)
    return TaskOutput(**defaults)


class TestBasicEvaluation:
    def test_true_expression(self):
        output = _make_output(summary="All tests passed")
        assert evaluate_condition("'passed' in summary.lower()", output) is True

    def test_false_expression(self):
        output = _make_output(summary="All tests passed")
        assert evaluate_condition("'fail' in summary.lower()", output) is False

    def test_status_check(self):
        output = _make_output(status=TaskStatus.SUCCEEDED)
        assert evaluate_condition("status == 'succeeded'", output) is True

    def test_status_failed(self):
        output = _make_output(status=TaskStatus.FAILED)
        assert evaluate_condition("status == 'failed'", output) is True

    def test_boolean_literal_true(self):
        output = _make_output()
        assert evaluate_condition("True", output) is True

    def test_boolean_literal_false(self):
        output = _make_output()
        assert evaluate_condition("False", output) is False


class TestFindingsAccess:
    def test_findings_list(self):
        output = _make_output(key_findings=[
            Finding(finding="Market is growing", confidence=Confidence.HIGH),
            Finding(finding="Revenue up 20%", confidence=Confidence.MEDIUM),
        ])
        assert evaluate_condition("len(findings) == 2", output) is True

    def test_findings_content(self):
        output = _make_output(key_findings=[
            Finding(finding="Tests passing", confidence=Confidence.HIGH),
        ])
        assert evaluate_condition("any('passing' in f for f in findings)", output) is True

    def test_empty_findings(self):
        output = _make_output()
        assert evaluate_condition("len(findings) == 0", output) is True


class TestFilesAccess:
    def test_files_produced(self):
        output = _make_output(files_produced=[
            FileReference(path="output.md", description="Results"),
        ])
        assert evaluate_condition("len(files) == 1", output) is True

    def test_specific_file(self):
        output = _make_output(files_produced=[
            FileReference(path="report.pdf", description="Report"),
        ])
        assert evaluate_condition("any('report' in f for f in files)", output) is True


class TestIterationAccess:
    def test_iteration_first(self):
        output = _make_output(iteration=1)
        assert evaluate_condition("iteration == 1", output) is True

    def test_iteration_retry(self):
        output = _make_output(iteration=3)
        assert evaluate_condition("iteration > 2", output) is True


class TestSafeBuiltins:
    def test_len(self):
        output = _make_output(summary="hello")
        assert evaluate_condition("len(summary) == 5", output) is True

    def test_any(self):
        output = _make_output(open_questions=["q1", "q2"])
        assert evaluate_condition("any(q.startswith('q') for q in open_questions)", output) is True

    def test_all(self):
        output = _make_output(open_questions=["q1", "q2"])
        assert evaluate_condition("all(q.startswith('q') for q in open_questions)", output) is True

    def test_min_max(self):
        output = _make_output()
        assert evaluate_condition("max(1, 2, 3) == 3", output) is True

    def test_abs(self):
        output = _make_output()
        assert evaluate_condition("abs(-5) == 5", output) is True


class TestErrorHandling:
    def test_empty_expression(self):
        output = _make_output()
        with pytest.raises(ConditionEvaluationError, match="Empty"):
            evaluate_condition("", output)

    def test_whitespace_expression(self):
        output = _make_output()
        with pytest.raises(ConditionEvaluationError, match="Empty"):
            evaluate_condition("   ", output)

    def test_syntax_error(self):
        output = _make_output()
        with pytest.raises(ConditionEvaluationError, match="Failed to evaluate"):
            evaluate_condition("if True:", output)

    def test_undefined_variable(self):
        output = _make_output()
        with pytest.raises(ConditionEvaluationError, match="Failed to evaluate"):
            evaluate_condition("undefined_var == 1", output)

    def test_import_blocked(self):
        output = _make_output()
        with pytest.raises(ConditionEvaluationError, match="Failed to evaluate"):
            evaluate_condition("__import__('os')", output)

    def test_truthiness_conversion(self):
        """Non-bool results are converted via bool()."""
        output = _make_output(summary="nonempty")
        assert evaluate_condition("summary", output) is True

    def test_none_is_falsy(self):
        output = _make_output()
        assert evaluate_condition("None", output) is False
