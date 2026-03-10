"""Compliance report generation from event logs.

Enterprises need audit artifacts — this is the governance moat.
Generates structured compliance reports from workflow event history.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.kernel.event_log import EventLog
from agentos.schemas.events import Event, EventType


class AgentActionSummary(BaseModel):
    """Summary of a single agent's actions during workflow execution."""

    agent_id: str
    agent_name: str = ""
    tool_calls: int = 0
    tokens_consumed: int = 0
    estimated_cost_usd: float = 0.0
    tools_used: list[str] = Field(default_factory=list)


class GateEvent(BaseModel):
    """Record of a human oversight gate event."""

    task_id: str
    gate_type: str = ""
    action: str  # "waiting" or "resolved"
    resolution: str = ""
    resolved_by: str = ""
    timestamp: datetime


class AnomalyFlag(BaseModel):
    """Anomaly detected during compliance analysis."""

    category: str  # "budget_spike", "repeated_failure", "escalation_attempt"
    description: str
    severity: str = "warning"  # "warning" or "critical"


class ComplianceReport(BaseModel):
    """Complete compliance report for a workflow execution."""

    workflow_id: str
    workflow_name: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Execution summary
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    status: str = ""
    task_count: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0

    # Agent actions
    agent_actions: list[AgentActionSummary] = Field(default_factory=list)

    # Human oversight
    gate_events: list[GateEvent] = Field(default_factory=list)
    total_approvals: int = 0
    total_rejections: int = 0

    # Budget compliance
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    budget_exceeded_events: int = 0

    # Security
    capability_grants: int = 0
    capability_denials: int = 0
    policy_violations: int = 0

    # Anomalies
    anomalies: list[AnomalyFlag] = Field(default_factory=list)

    # Raw event count
    total_events: int = 0

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def to_html(self) -> str:
        """Generate a standalone HTML report with inline CSS."""
        sections = []

        sections.append(f"""
<div class="section">
  <h2>Execution Summary</h2>
  <table>
    <tr><td>Workflow ID</td><td>{self.workflow_id}</td></tr>
    <tr><td>Workflow Name</td><td>{self.workflow_name}</td></tr>
    <tr><td>Status</td><td>{self.status}</td></tr>
    <tr><td>Duration</td><td>{self.duration_seconds:.1f}s</td></tr>
    <tr><td>Tasks</td><td>{self.tasks_succeeded} succeeded, {self.tasks_failed} failed of {self.task_count}</td></tr>
    <tr><td>Total Events</td><td>{self.total_events}</td></tr>
  </table>
</div>""")

        if self.agent_actions:
            rows = ""
            for a in self.agent_actions:
                rows += f"<tr><td>{a.agent_id}</td><td>{a.agent_name}</td><td>{a.tool_calls}</td><td>{a.tokens_consumed}</td><td>${a.estimated_cost_usd:.4f}</td></tr>\n"
            sections.append(f"""
<div class="section">
  <h2>Agent Actions</h2>
  <table>
    <tr><th>Agent ID</th><th>Name</th><th>Tool Calls</th><th>Tokens</th><th>Cost</th></tr>
    {rows}
  </table>
</div>""")

        if self.gate_events:
            rows = ""
            for g in self.gate_events:
                rows += f"<tr><td>{g.task_id}</td><td>{g.action}</td><td>{g.resolution}</td><td>{g.resolved_by}</td></tr>\n"
            sections.append(f"""
<div class="section">
  <h2>Human Oversight</h2>
  <p>Approvals: {self.total_approvals} | Rejections: {self.total_rejections}</p>
  <table>
    <tr><th>Task</th><th>Action</th><th>Resolution</th><th>Resolved By</th></tr>
    {rows}
  </table>
</div>""")

        sections.append(f"""
<div class="section">
  <h2>Budget Compliance</h2>
  <table>
    <tr><td>Total Tokens</td><td>{self.total_tokens:,}</td></tr>
    <tr><td>Total Cost</td><td>${self.total_cost_usd:.4f}</td></tr>
    <tr><td>Budget Exceeded Events</td><td>{self.budget_exceeded_events}</td></tr>
  </table>
</div>""")

        sections.append(f"""
<div class="section">
  <h2>Security</h2>
  <table>
    <tr><td>Capability Grants</td><td>{self.capability_grants}</td></tr>
    <tr><td>Capability Denials</td><td>{self.capability_denials}</td></tr>
    <tr><td>Policy Violations</td><td>{self.policy_violations}</td></tr>
  </table>
</div>""")

        if self.anomalies:
            anomaly_rows = ""
            for a in self.anomalies:
                color = "#dc3545" if a.severity == "critical" else "#ffc107"
                anomaly_rows += f'<tr><td style="color:{color}">{a.severity}</td><td>{a.category}</td><td>{a.description}</td></tr>\n'
            sections.append(f"""
<div class="section">
  <h2>Anomalies</h2>
  <table>
    <tr><th>Severity</th><th>Category</th><th>Description</th></tr>
    {anomaly_rows}
  </table>
</div>""")

        body = "\n".join(sections)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AgentOS Compliance Report — {self.workflow_id[:12]}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
  h2 {{ color: #555; margin-top: 30px; }}
  .section {{ margin-bottom: 30px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
  th {{ background-color: #f5f5f5; }}
  tr:nth-child(even) {{ background-color: #fafafa; }}
  .meta {{ color: #888; font-size: 0.9em; }}
</style>
</head>
<body>
<h1>AgentOS Compliance Report</h1>
<p class="meta">Generated: {self.generated_at.isoformat()} | Workflow: {self.workflow_id}</p>
{body}
</body>
</html>"""


class ComplianceReportGenerator:
    """Generates compliance reports from workflow event logs."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def generate(self, workflow_id: str) -> ComplianceReport:
        """Generate a compliance report for the given workflow."""
        events = self._event_log.query(workflow_id=workflow_id)

        report = ComplianceReport(workflow_id=workflow_id)
        report.total_events = len(events)

        agents: dict[str, AgentActionSummary] = {}
        task_states: dict[str, str] = {}
        budget_deltas: list[float] = []

        for event in events:
            self._process_event(event, report, agents, task_states, budget_deltas)

        report.agent_actions = list(agents.values())

        # Calculate duration
        if report.started_at and report.completed_at:
            report.duration_seconds = (
                report.completed_at - report.started_at
            ).total_seconds()

        # Count task outcomes
        report.tasks_succeeded = sum(1 for s in task_states.values() if s == "succeeded")
        report.tasks_failed = sum(1 for s in task_states.values() if s == "failed")

        # Detect anomalies
        self._detect_anomalies(report, budget_deltas, task_states)

        return report

    def _process_event(
        self,
        event: Event,
        report: ComplianceReport,
        agents: dict[str, AgentActionSummary],
        task_states: dict[str, str],
        budget_deltas: list[float],
    ) -> None:
        payload = event.payload

        if event.event_type == EventType.WORKFLOW_STARTED:
            report.workflow_name = payload.get("workflow_name", "")
            report.task_count = payload.get("task_count", 0)
            report.started_at = event.timestamp

        elif event.event_type == EventType.WORKFLOW_COMPLETED:
            report.status = payload.get("status", "")
            report.completed_at = event.timestamp

        elif event.event_type == EventType.TASK_STATE_CHANGED:
            task_name = payload.get("task", "")
            new_state = payload.get("to", "")
            if task_name and new_state:
                task_states[task_name] = new_state

        elif event.event_type == EventType.AGENT_SPAWNED:
            agent_id = payload.get("agent_id", "")
            if agent_id and agent_id not in agents:
                agents[agent_id] = AgentActionSummary(
                    agent_id=agent_id,
                    agent_name=payload.get("agent_name", ""),
                )

        elif event.event_type == EventType.AGENT_TOOL_CALL:
            agent_id = payload.get("agent_id", "")
            if agent_id:
                if agent_id not in agents:
                    agents[agent_id] = AgentActionSummary(agent_id=agent_id)
                agents[agent_id].tool_calls += 1
                tool_name = payload.get("tool", "")
                if tool_name and tool_name not in agents[agent_id].tools_used:
                    agents[agent_id].tools_used.append(tool_name)

        elif event.event_type == EventType.BUDGET_CONSUMED:
            agent_id = payload.get("agent_id", "")
            tokens = payload.get("tokens", 0)
            cost = payload.get("cost_usd", 0.0)
            report.total_tokens += tokens
            report.total_cost_usd += cost
            budget_deltas.append(cost)
            if agent_id and agent_id in agents:
                agents[agent_id].tokens_consumed += tokens
                agents[agent_id].estimated_cost_usd += cost

        elif event.event_type == EventType.BUDGET_EXCEEDED:
            report.budget_exceeded_events += 1

        elif event.event_type == EventType.GATE_WAITING:
            report.gate_events.append(GateEvent(
                task_id=payload.get("task", ""),
                gate_type=payload.get("gate_type", ""),
                action="waiting",
                timestamp=event.timestamp,
            ))

        elif event.event_type == EventType.GATE_RESOLVED:
            resolution = payload.get("resolution", "")
            report.gate_events.append(GateEvent(
                task_id=payload.get("task", ""),
                action="resolved",
                resolution=resolution,
                resolved_by=payload.get("resolved_by", ""),
                timestamp=event.timestamp,
            ))
            if resolution == "approved":
                report.total_approvals += 1
            elif resolution == "rejected":
                report.total_rejections += 1

        elif event.event_type == EventType.CAPABILITY_GRANTED:
            report.capability_grants += 1

        elif event.event_type == EventType.CAPABILITY_DENIED:
            report.capability_denials += 1

        elif event.event_type == EventType.POLICY_VIOLATION_DETECTED:
            report.policy_violations += 1

    def _detect_anomalies(
        self,
        report: ComplianceReport,
        budget_deltas: list[float],
        task_states: dict[str, str],
    ) -> None:
        """Detect anomalies in the workflow execution."""
        # Budget spikes: any single delta > 2x average
        if len(budget_deltas) >= 3:
            avg = sum(budget_deltas) / len(budget_deltas)
            if avg > 0:
                for i, delta in enumerate(budget_deltas):
                    if delta > 2 * avg:
                        report.anomalies.append(AnomalyFlag(
                            category="budget_spike",
                            description=f"Budget event #{i+1} (${delta:.4f}) exceeds 2x average (${avg:.4f})",
                        ))
                        break  # Report only first spike

        # Repeated failures: >2 consecutive failures
        if report.tasks_failed > 2:
            report.anomalies.append(AnomalyFlag(
                category="repeated_failure",
                description=f"{report.tasks_failed} tasks failed in this workflow",
                severity="critical" if report.tasks_failed > 3 else "warning",
            ))

        # Budget exceeded is always an anomaly
        if report.budget_exceeded_events > 0:
            report.anomalies.append(AnomalyFlag(
                category="budget_exceeded",
                description=f"Budget was exceeded {report.budget_exceeded_events} time(s)",
                severity="critical",
            ))
