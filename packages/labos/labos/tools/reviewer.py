"""ReviewerTool — validates reproducibility records."""

from __future__ import annotations

from pydantic import BaseModel

from agentos.tools.base import BaseTool, SideEffect

from labos.domain.schemas import ReviewerInput, ReviewerOutput, ReviewResult


class ReviewerTool(BaseTool):
    """Validate a ReproducibilityRecord for completeness and correctness."""

    @property
    def name(self) -> str:
        return "reviewer"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return ReviewerInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return ReviewerOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        data = input_data if isinstance(input_data, ReviewerInput) else ReviewerInput.model_validate(input_data.model_dump())
        rec = data.reproducibility_record

        missing: list[str] = []
        warnings: list[str] = []

        # Required field checks
        if not rec.dataset_checksum:
            missing.append("dataset_checksum")
        if not rec.config_hash:
            missing.append("config_hash")
        if not rec.environment_spec.python_version:
            missing.append("environment_spec.python_version")
        if rec.dataset_record and rec.dataset_record.n_samples <= 0:
            missing.append("dataset_record.n_samples > 0")

        # Warning checks
        if not rec.environment_spec.sklearn_version:
            warnings.append("sklearn_version is empty — version pinning recommended")
        if not rec.code_version:
            warnings.append("code_version is empty — consider tagging the commit")
        if rec.plot_record is None:
            warnings.append("No plot record — visualizations aid review")
        if rec.report_record is None:
            warnings.append("No report record — documentation aids reproducibility")

        passed = len(missing) == 0

        if passed:
            summary = "Reproducibility review PASSED."
            if warnings:
                summary += f" {len(warnings)} warning(s) noted."
        else:
            summary = f"Reproducibility review FAILED: {len(missing)} required field(s) missing."

        result = ReviewResult(
            passed=passed,
            missing_fields=missing,
            warnings=warnings,
            summary=summary,
        )
        return ReviewerOutput(result=result)
