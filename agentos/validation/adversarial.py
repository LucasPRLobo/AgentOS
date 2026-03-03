"""Adversarial validation — independent verification of task outputs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agentos.schemas.task import Finding, TaskOutput


class ValidationResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class ValidationFinding(BaseModel):
    """A single finding from the validation process."""

    claim: str = Field(description="The claim being verified")
    verdict: str = Field(description="pass | fail | inconclusive")
    reason: str = Field(default="", description="Explanation of the verdict")


class ValidationReport(BaseModel):
    """Report produced by an adversarial validation node."""

    task_id: str = Field(description="The task whose output was validated")
    validator_id: str = Field(description="ID of the validator agent")
    result: ValidationResult
    confidence: float = Field(ge=0.0, le=1.0, description="0.0–1.0")
    findings: list[ValidationFinding] = Field(default_factory=list)
    summary: str = Field(default="", description="Overall assessment")


class FailureAction(StrEnum):
    """What to do when validation fails."""

    RETRY = "retry"
    REVISE = "revise"  # Send feedback back to original agent
    GATE = "gate"  # Escalate to human approval gate
    FAIL = "fail"  # Hard fail the workflow


class AdversarialValidatorConfig(BaseModel):
    """Configuration for a validation node in the workflow."""

    validator_agent: str = Field(description="Agent ID to use as validator")
    target_task: str = Field(description="Task whose output to validate")
    on_failure: FailureAction = Field(
        default=FailureAction.FAIL,
        description="Action to take on validation failure",
    )
    max_retries: int = Field(
        default=1,
        description="Max retries before escalating (for retry/revise)",
    )
    min_confidence: float = Field(
        default=0.7,
        description="Minimum confidence threshold to pass",
    )


class AdversarialValidator:
    """Validates task output using a validation function.

    In production, the validate_fn would call a different LLM model
    to independently verify the task output. For testing and demos,
    a stub or rule-based validator can be injected.

    Key design principle: the validator MUST use a different model or
    approach than the producer agent. Using the same model for both
    undermines the purpose of adversarial validation.
    """

    def __init__(
        self,
        config: AdversarialValidatorConfig,
        validate_fn=None,
    ) -> None:
        self._config = config
        self._validate_fn = validate_fn or self._default_validate

    def validate(self, task_output: TaskOutput) -> ValidationReport:
        """Run validation on a task output.

        Returns a ValidationReport. The caller (DAG executor or task
        executor) decides what to do based on the result and config.
        """
        return self._validate_fn(task_output, self._config)

    @property
    def config(self) -> AdversarialValidatorConfig:
        return self._config

    @staticmethod
    def _default_validate(
        output: TaskOutput,
        config: AdversarialValidatorConfig,
    ) -> ValidationReport:
        """Default validation: check that output has required fields."""
        findings: list[ValidationFinding] = []

        # Check summary exists
        if not output.summary or output.summary.strip() == "":
            findings.append(ValidationFinding(
                claim="Task produced a summary",
                verdict="fail",
                reason="Summary is empty",
            ))

        # Check findings exist
        if not output.key_findings:
            findings.append(ValidationFinding(
                claim="Task produced findings",
                verdict="fail",
                reason="No key findings in output",
            ))
        else:
            for f in output.key_findings:
                if not f.finding.strip():
                    findings.append(ValidationFinding(
                        claim="Finding has content",
                        verdict="fail",
                        reason="Empty finding text",
                    ))
                else:
                    findings.append(ValidationFinding(
                        claim=f"Finding: {f.finding[:50]}",
                        verdict="pass",
                    ))

        # Check status
        if output.status != "succeeded":
            findings.append(ValidationFinding(
                claim="Task succeeded",
                verdict="fail",
                reason=f"Task status is {output.status}",
            ))

        failed = [f for f in findings if f.verdict == "fail"]
        total = len(findings) or 1
        confidence = 1.0 - (len(failed) / total)

        result = (
            ValidationResult.PASSED
            if confidence >= config.min_confidence
            else ValidationResult.FAILED
        )

        return ValidationReport(
            task_id=output.task_id,
            validator_id=config.validator_agent,
            result=result,
            confidence=round(confidence, 2),
            findings=findings,
            summary=(
                f"Validation {'passed' if result == 'passed' else 'failed'}: "
                f"{len(failed)}/{total} checks failed"
            ),
        )

    @staticmethod
    def check_model_separation(
        producer_model: str,
        validator_model: str,
    ) -> str | None:
        """Warn if producer and validator use the same model.

        Returns a warning message if models match, None if they differ.
        """
        if producer_model == validator_model:
            return (
                f"Adversarial validation warning: producer and validator "
                f"both use '{producer_model}'. Using the same model for "
                f"both roles undermines independent verification."
            )
        return None
