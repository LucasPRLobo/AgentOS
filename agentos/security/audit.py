"""Agent Audit tool — scan agent usage and produce risk assessment reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.sandbox import SandboxLevel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditFinding:
    """A single finding from an agent audit."""

    category: str
    description: str
    risk: RiskLevel
    recommendation: str


@dataclass
class AuditReport:
    """Complete audit report for an agent or workflow."""

    agent_id: str
    findings: list[AuditFinding] = field(default_factory=list)
    overall_risk: RiskLevel = RiskLevel.LOW
    score: float = 100.0  # 0-100, higher is safer

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "findings": [
                {
                    "category": f.category,
                    "description": f.description,
                    "risk": f.risk.value,
                    "recommendation": f.recommendation,
                }
                for f in self.findings
            ],
            "overall_risk": self.overall_risk.value,
            "score": self.score,
        }


class AgentAuditor:
    """Scans agent configuration and produces risk assessment reports.

    Checks:
    - Capability grants (wildcard scopes, missing types)
    - Sandbox isolation level
    - Deny-by-default enforcement
    - Grant breadth
    """

    def audit_policy(self, agent_id: str, policy: CapabilityPolicy) -> AuditReport:
        """Audit a capability policy for security risks."""
        findings: list[AuditFinding] = []

        # Check sandbox level
        if policy.sandbox == SandboxLevel.NONE:
            findings.append(AuditFinding(
                category="isolation",
                description="Agent runs without sandbox isolation",
                risk=RiskLevel.HIGH,
                recommendation="Enable namespace or container sandbox",
            ))

        # Check deny-by-default
        if not policy.deny_by_default:
            findings.append(AuditFinding(
                category="policy",
                description="Policy is not deny-by-default",
                risk=RiskLevel.HIGH,
                recommendation="Enable deny_by_default for defense in depth",
            ))

        # Check grants
        if not policy.grants:
            if policy.deny_by_default:
                # No grants + deny-by-default = agent can do nothing (maybe intentional)
                pass
            else:
                findings.append(AuditFinding(
                    category="grants",
                    description="No explicit grants with allow-by-default policy",
                    risk=RiskLevel.CRITICAL,
                    recommendation="Define explicit grants and enable deny_by_default",
                ))

        # Check for wildcard grants
        tool_grants = [g for g in policy.grants if g.prefix == "tool"]
        path_grants = [g for g in policy.grants if g.prefix == "path"]
        domain_grants = [g for g in policy.grants if g.prefix == "domain"]

        for grant in policy.grants:
            if grant.value == "*":
                findings.append(AuditFinding(
                    category="grants",
                    description=f"Wildcard grant: {grant.type}",
                    risk=RiskLevel.HIGH,
                    recommendation=f"Narrow the scope of '{grant.type}' grant",
                ))

        # Check for broad tool grants
        if len(tool_grants) > 20:
            findings.append(AuditFinding(
                category="permissions",
                description=f"Broad tool grants ({len(tool_grants)} tools)",
                risk=RiskLevel.MEDIUM,
                recommendation="Reduce tool grants to minimum necessary",
            ))

        # Check missing grant types (no path restrictions at all)
        if not path_grants and policy.deny_by_default:
            # With deny-by-default, no path grants means no file access — that's fine
            pass
        elif not path_grants and not policy.deny_by_default:
            findings.append(AuditFinding(
                category="filesystem",
                description="No path restrictions with allow-by-default policy",
                risk=RiskLevel.HIGH,
                recommendation="Add path grants and enable deny_by_default",
            ))

        if not domain_grants and not policy.deny_by_default:
            findings.append(AuditFinding(
                category="network",
                description="No domain restrictions with allow-by-default policy",
                risk=RiskLevel.MEDIUM,
                recommendation="Add domain grants and enable deny_by_default",
            ))

        # Calculate score and overall risk
        score = 100.0
        risk_penalties = {
            RiskLevel.LOW: 5,
            RiskLevel.MEDIUM: 15,
            RiskLevel.HIGH: 25,
            RiskLevel.CRITICAL: 40,
        }
        for f in findings:
            score -= risk_penalties[f.risk]
        score = max(0.0, score)

        # Determine overall risk
        if any(f.risk == RiskLevel.CRITICAL for f in findings):
            overall_risk = RiskLevel.CRITICAL
        elif any(f.risk == RiskLevel.HIGH for f in findings):
            overall_risk = RiskLevel.HIGH
        elif any(f.risk == RiskLevel.MEDIUM for f in findings):
            overall_risk = RiskLevel.MEDIUM
        else:
            overall_risk = RiskLevel.LOW

        return AuditReport(
            agent_id=agent_id,
            findings=findings,
            overall_risk=overall_risk,
            score=score,
        )
