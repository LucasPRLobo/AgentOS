"""Runtime policy verification for Tier 2/3 agents — workspace diff auditing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import Event, EventType


@dataclass
class PolicyViolation:
    """A detected policy violation."""

    agent_id: str
    violation_type: str  # "path" | "domain" | "tool" | "workspace_escape"
    detail: str
    severity: str  # "warning" | "error" | "critical"


@dataclass
class VerificationResult:
    """Result of post-hoc policy verification."""

    agent_id: str
    violations: list[PolicyViolation] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    files_allowed: list[str] = field(default_factory=list)
    files_unauthorized: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0


class PostHocVerifier:
    """Verifies Tier 2/3 agent compliance after task execution.

    Checks:
    1. Workspace diff — what files did the agent actually touch?
    2. Path compliance — are all touched files within allowed paths?
    3. No workspace escape — agent stayed within its assigned workspace
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

    def verify(
        self,
        agent_id: str,
        policy: CapabilityPolicy,
        workspace: Path,
        pre_snapshot: dict[str, float],
        post_snapshot: dict[str, float],
    ) -> VerificationResult:
        """Compare workspace state before/after agent execution.

        Args:
            agent_id: The agent being verified.
            policy: The agent's capability policy.
            workspace: The workspace root path.
            pre_snapshot: {path: mtime} before execution.
            post_snapshot: {path: mtime} after execution.
        """
        result = VerificationResult(agent_id=agent_id)
        workspace_str = str(workspace.resolve())

        for path, mtime in post_snapshot.items():
            if path not in pre_snapshot or pre_snapshot[path] != mtime:
                result.files_touched.append(path)

                # Check workspace escape
                if not path.startswith(workspace_str):
                    result.files_unauthorized.append(path)
                    result.violations.append(
                        PolicyViolation(
                            agent_id=agent_id,
                            violation_type="workspace_escape",
                            detail=f"File outside workspace: {path}",
                            severity="critical",
                        )
                    )
                elif policy.has_path(path):
                    result.files_allowed.append(path)
                else:
                    result.files_unauthorized.append(path)
                    result.violations.append(
                        PolicyViolation(
                            agent_id=agent_id,
                            violation_type="path",
                            detail=f"Unauthorized file access: {path}",
                            severity="error",
                        )
                    )

        # Emit events for violations
        for violation in result.violations:
            self._event_log.append(
                Event(
                    event_type=EventType.POLICY_VIOLATION_DETECTED,
                    workflow_id=self._workflow_id,
                    seq=self._seq.next(),
                    schema_version="0.2",
                    payload={
                        "agent_id": agent_id,
                        "violation_type": violation.violation_type,
                        "detail": violation.detail,
                        "severity": violation.severity,
                    },
                )
            )

        return result

    @staticmethod
    def snapshot_directory(directory: Path) -> dict[str, float]:
        """Create a snapshot of file modification times in a directory."""
        snapshot: dict[str, float] = {}
        if directory.exists():
            for p in directory.rglob("*"):
                if p.is_file():
                    snapshot[str(p.resolve())] = p.stat().st_mtime
        return snapshot
