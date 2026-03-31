"""Task verifier — checks output against specification before accepting.

Auto-verification runs immediately after an agent completes.
If issues are found, a review discussion is opened.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.workspace.schemas import BacklogTask


class VerificationCheck(BaseModel):
    check: str
    passed: bool
    detail: str = ""


class VerificationResult(BaseModel):
    passed: bool = False
    checks: list[VerificationCheck] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    recommendation: str = "needs_review"  # auto_accept | needs_review | failed


class TaskVerifier:
    """Verifies task output against specification."""

    def verify(self, task: BacklogTask, output: dict | None) -> VerificationResult:
        """Run automated verification checks."""
        checks: list[VerificationCheck] = []
        issues: list[str] = []

        # Check 1: Output exists
        has_output = output is not None and bool(output)
        checks.append(VerificationCheck(
            check="output_exists",
            passed=has_output,
            detail="Output provided" if has_output else "No output from agent",
        ))
        if not has_output:
            return VerificationResult(
                passed=False, checks=checks,
                issues=["Agent did not produce output"],
                recommendation="failed",
            )

        # Check 2: Summary present
        summary = output.get("summary", "")
        has_summary = bool(summary and len(summary) > 10)
        checks.append(VerificationCheck(
            check="summary_present",
            passed=has_summary,
            detail=f"Summary: {summary[:100]}" if has_summary else "Summary missing or too short",
        ))
        if not has_summary:
            issues.append("Output summary is missing or too brief")

        # Check 3: Spec alignment (if spec exists)
        if task.spec:
            # Basic check: does the summary reference the task topic?
            spec_words = set(task.spec.lower().split())
            summary_words = set(summary.lower().split())
            overlap = spec_words & summary_words
            # Exclude common words
            overlap -= {"the", "a", "an", "to", "of", "in", "for", "and", "or", "is", "it", "on", "with"}
            has_overlap = len(overlap) >= 2
            checks.append(VerificationCheck(
                check="spec_alignment",
                passed=has_overlap,
                detail=f"Spec keywords found in output" if has_overlap else "Output may not address the spec",
            ))
            if not has_overlap:
                issues.append("Output may not address the task specification")

        # Check 4: Findings present (for research/analysis tasks)
        findings = output.get("findings", output.get("key_findings", []))
        if task.spec and any(
            w in task.spec.lower()
            for w in ("research", "analyze", "investigate", "find", "compare")
        ):
            has_findings = bool(findings)
            checks.append(VerificationCheck(
                check="findings_present",
                passed=has_findings,
                detail=f"{len(findings)} findings" if has_findings else "No findings for research task",
            ))
            if not has_findings:
                issues.append("Research/analysis task produced no findings")

        # Check 5: Files produced (if expected)
        if task.spec_expected_output and "file" in task.spec_expected_output.lower():
            files = output.get("files_produced", [])
            has_files = bool(files)
            checks.append(VerificationCheck(
                check="files_produced",
                passed=has_files,
                detail=f"Files: {', '.join(files[:3])}" if has_files else "Expected files not produced",
            ))
            if not has_files:
                issues.append("Expected output files were not produced")

        # Determine recommendation
        all_passed = all(c.passed for c in checks)
        critical_failed = any(
            not c.passed for c in checks
            if c.check in ("output_exists", "summary_present")
        )

        if critical_failed:
            recommendation = "failed"
        elif all_passed and not issues:
            recommendation = "auto_accept"
        else:
            recommendation = "needs_review"

        return VerificationResult(
            passed=all_passed,
            checks=checks,
            issues=issues,
            recommendation=recommendation,
        )

    def prepare_review_context(
        self, task: BacklogTask, output: dict | None,
        verification: VerificationResult,
    ) -> dict:
        """Prepare context for the coordinator's review discussion."""
        return {
            "task_title": task.title,
            "task_spec": task.spec or task.description,
            "output_summary": (output or {}).get("summary", "No summary"),
            "output_findings": [
                f.get("finding", str(f)) if isinstance(f, dict) else str(f)
                for f in (output or {}).get("findings", [])
            ],
            "verification_passed": verification.passed,
            "verification_issues": verification.issues,
            "recommendation": verification.recommendation,
            "checks": [c.model_dump() for c in verification.checks],
        }
