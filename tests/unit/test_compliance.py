"""Tests for compliance report generation."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.security.compliance import ComplianceReportGenerator


@pytest.fixture
def event_log(tmp_path):
    return SQLiteEventLog(str(tmp_path / "events.db"))


@pytest.fixture
def seq():
    return SeqCounter()


def _emit(event_log, seq, workflow_id, event_type, payload=None):
    event_log.append(Event(
        event_type=event_type,
        workflow_id=workflow_id,
        seq=seq.next(),
        payload=payload or {},
    ))


class TestComplianceReportEmpty:
    def test_empty_workflow(self, event_log, seq):
        gen = ComplianceReportGenerator(event_log)
        report = gen.generate("wf-nonexistent")
        assert report.total_events == 0
        assert report.workflow_id == "wf-nonexistent"


class TestComplianceReportBasic:
    def test_basic_workflow_report(self, event_log, seq):
        wid = "wf-1"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {
            "workflow_name": "test-flow", "task_count": 2
        })
        _emit(event_log, seq, wid, EventType.AGENT_SPAWNED, {
            "agent_id": "a1", "agent_name": "researcher"
        })
        _emit(event_log, seq, wid, EventType.TASK_STATE_CHANGED, {
            "task": "t1", "from": "pending", "to": "running"
        })
        _emit(event_log, seq, wid, EventType.AGENT_TOOL_CALL, {
            "agent_id": "a1", "tool": "Read"
        })
        _emit(event_log, seq, wid, EventType.BUDGET_CONSUMED, {
            "agent_id": "a1", "tokens": 500, "cost_usd": 0.01
        })
        _emit(event_log, seq, wid, EventType.TASK_STATE_CHANGED, {
            "task": "t1", "from": "running", "to": "succeeded"
        })
        _emit(event_log, seq, wid, EventType.WORKFLOW_COMPLETED, {
            "status": "succeeded"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.workflow_name == "test-flow"
        assert report.task_count == 2
        assert report.status == "succeeded"
        assert report.total_tokens == 500
        assert report.total_cost_usd == pytest.approx(0.01)
        assert report.tasks_succeeded == 1
        assert len(report.agent_actions) == 1
        assert report.agent_actions[0].tool_calls == 1

    def test_workflow_duration(self, event_log, seq):
        wid = "wf-dur"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {
            "workflow_name": "dur-test"
        })
        _emit(event_log, seq, wid, EventType.WORKFLOW_COMPLETED, {
            "status": "succeeded"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.started_at is not None
        assert report.completed_at is not None
        assert report.duration_seconds >= 0


class TestComplianceReportGates:
    def test_gate_events_tracked(self, event_log, seq):
        wid = "wf-2"
        _emit(event_log, seq, wid, EventType.GATE_WAITING, {
            "task": "gate1", "gate_type": "approval"
        })
        _emit(event_log, seq, wid, EventType.GATE_RESOLVED, {
            "task": "gate1", "resolution": "approved", "resolved_by": "admin"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert len(report.gate_events) == 2
        assert report.total_approvals == 1

    def test_gate_rejection_tracked(self, event_log, seq):
        wid = "wf-rej"
        _emit(event_log, seq, wid, EventType.GATE_RESOLVED, {
            "task": "gate1", "resolution": "rejected", "resolved_by": "reviewer"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.total_rejections == 1
        assert report.total_approvals == 0


class TestComplianceReportAnomalies:
    def test_anomaly_repeated_failure(self, event_log, seq):
        wid = "wf-3"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {"task_count": 4})
        for i in range(3):
            _emit(event_log, seq, wid, EventType.TASK_STATE_CHANGED, {
                "task": f"t{i}", "to": "failed"
            })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.tasks_failed == 3
        failure_anomalies = [a for a in report.anomalies if a.category == "repeated_failure"]
        assert len(failure_anomalies) == 1

    def test_budget_exceeded_anomaly(self, event_log, seq):
        wid = "wf-budg"
        _emit(event_log, seq, wid, EventType.BUDGET_EXCEEDED, {
            "agent_id": "a1", "dimension": "tokens"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.budget_exceeded_events == 1
        budget_anomalies = [a for a in report.anomalies if a.category == "budget_exceeded"]
        assert len(budget_anomalies) == 1
        assert budget_anomalies[0].severity == "critical"


class TestComplianceReportOutput:
    def test_json_output(self, event_log, seq):
        wid = "wf-4"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {"workflow_name": "test"})

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        json_str = report.to_json()
        assert "wf-4" in json_str

    def test_html_output(self, event_log, seq):
        wid = "wf-5"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {"workflow_name": "test"})

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        html = report.to_html()
        assert "<html>" in html
        assert "wf-5" in html
        assert "Compliance Report" in html


class TestComplianceReportSecurity:
    def test_security_events(self, event_log, seq):
        wid = "wf-6"
        _emit(event_log, seq, wid, EventType.CAPABILITY_GRANTED, {})
        _emit(event_log, seq, wid, EventType.CAPABILITY_GRANTED, {})
        _emit(event_log, seq, wid, EventType.CAPABILITY_DENIED, {})
        _emit(event_log, seq, wid, EventType.POLICY_VIOLATION_DETECTED, {})

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.capability_grants == 2
        assert report.capability_denials == 1
        assert report.policy_violations == 1

    def test_no_security_events_defaults_zero(self, event_log, seq):
        wid = "wf-nosec"
        _emit(event_log, seq, wid, EventType.WORKFLOW_STARTED, {"workflow_name": "test"})

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.capability_grants == 0
        assert report.capability_denials == 0
        assert report.policy_violations == 0


class TestComplianceReportAgentActions:
    def test_multiple_agents_tracked(self, event_log, seq):
        wid = "wf-multi"
        _emit(event_log, seq, wid, EventType.AGENT_SPAWNED, {
            "agent_id": "a1", "agent_name": "researcher"
        })
        _emit(event_log, seq, wid, EventType.AGENT_SPAWNED, {
            "agent_id": "a2", "agent_name": "writer"
        })
        _emit(event_log, seq, wid, EventType.AGENT_TOOL_CALL, {
            "agent_id": "a1", "tool": "Read"
        })
        _emit(event_log, seq, wid, EventType.AGENT_TOOL_CALL, {
            "agent_id": "a1", "tool": "Grep"
        })
        _emit(event_log, seq, wid, EventType.AGENT_TOOL_CALL, {
            "agent_id": "a2", "tool": "Write"
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert len(report.agent_actions) == 2
        a1 = next(a for a in report.agent_actions if a.agent_id == "a1")
        a2 = next(a for a in report.agent_actions if a.agent_id == "a2")
        assert a1.tool_calls == 2
        assert a2.tool_calls == 1
        assert "Read" in a1.tools_used
        assert "Grep" in a1.tools_used

    def test_budget_consumed_per_agent(self, event_log, seq):
        wid = "wf-budg-agent"
        _emit(event_log, seq, wid, EventType.AGENT_SPAWNED, {
            "agent_id": "a1", "agent_name": "researcher"
        })
        _emit(event_log, seq, wid, EventType.BUDGET_CONSUMED, {
            "agent_id": "a1", "tokens": 1000, "cost_usd": 0.05
        })
        _emit(event_log, seq, wid, EventType.BUDGET_CONSUMED, {
            "agent_id": "a1", "tokens": 500, "cost_usd": 0.02
        })

        gen = ComplianceReportGenerator(event_log)
        report = gen.generate(wid)

        assert report.total_tokens == 1500
        assert report.total_cost_usd == pytest.approx(0.07)
        a1 = report.agent_actions[0]
        assert a1.tokens_consumed == 1500
        assert a1.estimated_cost_usd == pytest.approx(0.07)
