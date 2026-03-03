"""Tests for adversarial validation — independent verification of task outputs."""

from __future__ import annotations

import pytest

from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskOutput,
    TaskStatus,
)
from agentos.validation.adversarial import (
    AdversarialValidator,
    AdversarialValidatorConfig,
    FailureAction,
    ValidationFinding,
    ValidationReport,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _good_output(task_id: str = "t1", agent_id: str = "ag1") -> TaskOutput:
    """A well-formed task output that should pass default validation."""
    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.SUCCEEDED,
        summary="Completed analysis of the dataset.",
        key_findings=[
            Finding(
                finding="Revenue grew 15% YoY",
                confidence=Confidence.HIGH,
                sources=["report.pdf"],
            ),
        ],
    )


def _bad_output(task_id: str = "t1", agent_id: str = "ag1") -> TaskOutput:
    """A poor task output — empty summary, no findings, wrong status."""
    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.FAILED,
        summary="",
        key_findings=[],
    )


def _default_config() -> AdversarialValidatorConfig:
    return AdversarialValidatorConfig(
        validator_agent="validator-1",
        target_task="t1",
    )


# ---------------------------------------------------------------------------
# Tests: Schema basics
# ---------------------------------------------------------------------------

class TestSchemas:

    def test_validation_result_values(self):
        assert ValidationResult.PASSED == "passed"
        assert ValidationResult.FAILED == "failed"

    def test_failure_action_values(self):
        assert FailureAction.RETRY == "retry"
        assert FailureAction.REVISE == "revise"
        assert FailureAction.GATE == "gate"
        assert FailureAction.FAIL == "fail"

    def test_validation_finding_fields(self):
        f = ValidationFinding(claim="test", verdict="pass", reason="ok")
        assert f.claim == "test"
        assert f.verdict == "pass"
        assert f.reason == "ok"

    def test_validation_report_fields(self):
        report = ValidationReport(
            task_id="t1",
            validator_id="v1",
            result=ValidationResult.PASSED,
            confidence=0.95,
            findings=[],
            summary="All good",
        )
        assert report.task_id == "t1"
        assert report.confidence == 0.95

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ValidationReport(
                task_id="t1",
                validator_id="v1",
                result=ValidationResult.PASSED,
                confidence=1.5,  # Out of range
            )

    def test_config_defaults(self):
        config = _default_config()
        assert config.on_failure == FailureAction.FAIL
        assert config.max_retries == 1
        assert config.min_confidence == 0.7


# ---------------------------------------------------------------------------
# Tests: Default validation logic
# ---------------------------------------------------------------------------

class TestDefaultValidation:

    def test_good_output_passes(self):
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(_good_output())

        assert report.result == ValidationResult.PASSED
        assert report.confidence >= 0.7
        assert report.task_id == "t1"
        assert report.validator_id == "validator-1"

    def test_bad_output_fails(self):
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(_bad_output())

        assert report.result == ValidationResult.FAILED
        assert report.confidence < 0.7

    def test_empty_summary_flagged(self):
        output = _good_output()
        output.summary = ""
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(output)

        failed_claims = [f for f in report.findings if f.verdict == "fail"]
        assert any("summary" in f.claim.lower() or "summary" in f.reason.lower()
                    for f in failed_claims)

    def test_no_findings_flagged(self):
        output = _good_output()
        output.key_findings = []
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(output)

        failed_claims = [f for f in report.findings if f.verdict == "fail"]
        assert any("finding" in f.claim.lower() or "finding" in f.reason.lower()
                    for f in failed_claims)

    def test_failed_status_flagged(self):
        output = _good_output()
        output.status = TaskStatus.FAILED
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(output)

        failed_claims = [f for f in report.findings if f.verdict == "fail"]
        assert any("status" in f.reason.lower() or "succeed" in f.claim.lower()
                    for f in failed_claims)

    def test_empty_finding_text_flagged(self):
        output = _good_output()
        output.key_findings = [Finding(finding="", confidence=Confidence.LOW)]
        config = _default_config()
        validator = AdversarialValidator(config)
        report = validator.validate(output)

        failed_claims = [f for f in report.findings if f.verdict == "fail"]
        assert any("empty" in f.reason.lower() for f in failed_claims)

    def test_high_confidence_threshold(self):
        """With min_confidence=1.0, even a good output fails if any check fails."""
        config = AdversarialValidatorConfig(
            validator_agent="v1",
            target_task="t1",
            min_confidence=1.0,
        )
        # Add a finding with one slightly weak aspect
        output = _good_output()
        output.status = TaskStatus.FAILED  # This alone drops confidence
        validator = AdversarialValidator(config)
        report = validator.validate(output)

        assert report.result == ValidationResult.FAILED

    def test_low_confidence_threshold(self):
        """With min_confidence=0.0, everything passes."""
        config = AdversarialValidatorConfig(
            validator_agent="v1",
            target_task="t1",
            min_confidence=0.0,
        )
        validator = AdversarialValidator(config)
        report = validator.validate(_bad_output())
        assert report.result == ValidationResult.PASSED


# ---------------------------------------------------------------------------
# Tests: Custom validation function
# ---------------------------------------------------------------------------

class TestCustomValidation:

    def test_injected_validate_fn(self):
        """Custom validation function overrides default logic."""

        def always_pass(output, config):
            return ValidationReport(
                task_id=output.task_id,
                validator_id=config.validator_agent,
                result=ValidationResult.PASSED,
                confidence=1.0,
                summary="Custom validator: auto-pass",
            )

        config = _default_config()
        validator = AdversarialValidator(config, validate_fn=always_pass)
        report = validator.validate(_bad_output())

        assert report.result == ValidationResult.PASSED
        assert report.confidence == 1.0

    def test_injected_fail_fn(self):
        def always_fail(output, config):
            return ValidationReport(
                task_id=output.task_id,
                validator_id=config.validator_agent,
                result=ValidationResult.FAILED,
                confidence=0.0,
                summary="Custom validator: auto-fail",
            )

        config = _default_config()
        validator = AdversarialValidator(config, validate_fn=always_fail)
        report = validator.validate(_good_output())

        assert report.result == ValidationResult.FAILED


# ---------------------------------------------------------------------------
# Tests: Model separation check
# ---------------------------------------------------------------------------

class TestModelSeparation:

    def test_same_model_warns(self):
        warning = AdversarialValidator.check_model_separation(
            "claude-sonnet-4-6", "claude-sonnet-4-6"
        )
        assert warning is not None
        assert "same model" in warning.lower() or "both use" in warning.lower()

    def test_different_models_ok(self):
        warning = AdversarialValidator.check_model_separation(
            "claude-sonnet-4-6", "gpt-4o"
        )
        assert warning is None

    def test_empty_models_match(self):
        warning = AdversarialValidator.check_model_separation("", "")
        assert warning is not None


# ---------------------------------------------------------------------------
# Tests: Config accessors
# ---------------------------------------------------------------------------

class TestConfigAccessor:

    def test_config_property(self):
        config = _default_config()
        validator = AdversarialValidator(config)
        assert validator.config is config

    def test_custom_failure_action(self):
        config = AdversarialValidatorConfig(
            validator_agent="v1",
            target_task="t1",
            on_failure=FailureAction.RETRY,
            max_retries=3,
        )
        assert config.on_failure == FailureAction.RETRY
        assert config.max_retries == 3
