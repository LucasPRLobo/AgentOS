"""Tests for agent audit tool."""

from __future__ import annotations

import pytest

from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.sandbox import SandboxLevel
from agentos.security.audit import AgentAuditor, AuditReport, RiskLevel


@pytest.fixture
def auditor() -> AgentAuditor:
    return AgentAuditor()


class TestPolicyAudit:
    def test_secure_policy_low_risk(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[
                CapabilityGrant(type="tool:read_file"),
                CapabilityGrant(type="tool:write_file"),
                CapabilityGrant(type="path:/workspace"),
                CapabilityGrant(type="domain:api.example.com"),
            ],
            deny_by_default=True,
            sandbox=SandboxLevel.CONTAINER,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert report.overall_risk == RiskLevel.LOW
        assert report.score > 80

    def test_no_sandbox_high_risk(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[CapabilityGrant(type="tool:read_file")],
            deny_by_default=True,
            sandbox=SandboxLevel.NONE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert any(f.category == "isolation" for f in report.findings)
        assert report.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_not_deny_by_default_no_grants_critical(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[],
            deny_by_default=False,
            sandbox=SandboxLevel.NAMESPACE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert any(f.risk == RiskLevel.CRITICAL for f in report.findings)
        assert report.overall_risk == RiskLevel.CRITICAL

    def test_wildcard_grant_high_risk(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[CapabilityGrant(type="tool:*")],
            deny_by_default=True,
            sandbox=SandboxLevel.NAMESPACE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert any("wildcard" in f.description.lower() for f in report.findings)

    def test_broad_tool_grants_medium(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[CapabilityGrant(type=f"tool:tool_{i}") for i in range(25)],
            deny_by_default=True,
            sandbox=SandboxLevel.NAMESPACE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert any(f.category == "permissions" and f.risk == RiskLevel.MEDIUM for f in report.findings)

    def test_not_deny_by_default(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[CapabilityGrant(type="tool:read")],
            deny_by_default=False,
            sandbox=SandboxLevel.NAMESPACE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert any(f.category == "policy" for f in report.findings)

    def test_score_decreases_with_findings(self, auditor):
        secure = CapabilityPolicy(
            agent_id="a1",
            grants=[
                CapabilityGrant(type="tool:read"),
                CapabilityGrant(type="path:/ws"),
                CapabilityGrant(type="domain:x.com"),
            ],
            deny_by_default=True,
            sandbox=SandboxLevel.CONTAINER,
        )
        insecure = CapabilityPolicy(
            agent_id="a2",
            grants=[],
            deny_by_default=False,
            sandbox=SandboxLevel.NONE,
        )
        r1 = auditor.audit_policy("a1", secure)
        r2 = auditor.audit_policy("a2", insecure)
        assert r1.score > r2.score

    def test_score_minimum_zero(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[
                CapabilityGrant(type="tool:*"),
                CapabilityGrant(type="path:*"),
                CapabilityGrant(type="domain:*"),
            ],
            deny_by_default=False,
            sandbox=SandboxLevel.NONE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert report.score >= 0.0


class TestReportSerialization:
    def test_report_to_dict(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[CapabilityGrant(type="tool:read")],
            deny_by_default=True,
            sandbox=SandboxLevel.NONE,
        )
        report = auditor.audit_policy("agent-1", policy)
        d = report.to_dict()
        assert d["agent_id"] == "agent-1"
        assert isinstance(d["findings"], list)
        assert "overall_risk" in d
        assert "score" in d

    def test_finding_count(self, auditor):
        policy = CapabilityPolicy(
            agent_id="agent-1",
            grants=[],
            deny_by_default=False,
            sandbox=SandboxLevel.NONE,
        )
        report = auditor.audit_policy("agent-1", policy)
        assert report.finding_count == len(report.findings)
        assert report.finding_count > 0
