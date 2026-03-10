"""Serializers — convert dataclasses/models to JSON-serializable dicts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agentos.kernel.replayer import (
    AgentSnapshot,
    BudgetSnapshot,
    GateSnapshot,
    TaskSnapshot,
    WorkflowSnapshot,
)
from agentos.schemas.events import Event


def _dt(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string or None."""
    return dt.isoformat() if dt else None


def event_to_dict(event: Event) -> dict[str, Any]:
    """Convert an Event to a JSON-serializable dict."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "workflow_id": event.workflow_id,
        "seq": event.seq,
        "timestamp": event.timestamp.isoformat() if isinstance(event.timestamp, datetime) else str(event.timestamp),
        "schema_version": event.schema_version,
        "payload": event.payload,
        "metadata": event.metadata,
    }


def task_snapshot_to_dict(task: TaskSnapshot) -> dict[str, Any]:
    """Convert a TaskSnapshot to a JSON-serializable dict."""
    result: dict[str, Any] = {
        "name": task.name,
        "state": task.state.value,
        "agent_id": task.agent_id,
        "transitions": [
            {"from": t[0], "to": t[1], "timestamp": _dt(t[2])}
            for t in task.transitions
        ],
    }
    if task.output:
        result["output"] = task.output.model_dump(mode="json")
    return result


def agent_snapshot_to_dict(agent: AgentSnapshot) -> dict[str, Any]:
    """Convert an AgentSnapshot to a JSON-serializable dict."""
    return {
        "agent_id": agent.agent_id,
        "agent_name": agent.agent_name,
        "adapter_tier": agent.adapter_tier,
        "spawned_at": _dt(agent.spawned_at),
        "terminated_at": _dt(agent.terminated_at),
        "termination_reason": agent.termination_reason,
        "metrics": agent.metrics,
    }


def gate_snapshot_to_dict(gate: GateSnapshot) -> dict[str, Any]:
    """Convert a GateSnapshot to a JSON-serializable dict."""
    return {
        "gate_id": gate.gate_id,
        "task_id": gate.task_id,
        "gate_type": gate.gate_type,
        "resolution": gate.resolution,
        "resolved_by": gate.resolved_by,
        "pending": gate.resolution == "",
    }


def budget_snapshot_to_dict(budget: BudgetSnapshot) -> dict[str, Any]:
    """Convert a BudgetSnapshot to a JSON-serializable dict."""
    return {
        "agent_id": budget.agent_id,
        "usage": budget.usage.model_dump(),
        "exceeded": budget.exceeded,
        "exceeded_resource": budget.exceeded_resource,
    }


def snapshot_to_dict(snap: WorkflowSnapshot) -> dict[str, Any]:
    """Convert a full WorkflowSnapshot to a JSON-serializable dict."""
    return {
        "workflow_id": snap.workflow_id,
        "workflow_name": snap.workflow_name,
        "status": snap.status,
        "task_count": snap.task_count,
        "started_at": _dt(snap.started_at),
        "completed_at": _dt(snap.completed_at),
        "total_cost": snap.total_cost,
        "total_tokens": snap.total_tokens,
        "event_count": snap.event_count,
        "tasks": {name: task_snapshot_to_dict(t) for name, t in snap.tasks.items()},
        "agents": {aid: agent_snapshot_to_dict(a) for aid, a in snap.agents.items()},
        "gates": {gid: gate_snapshot_to_dict(g) for gid, g in snap.gates.items()},
        "budgets": {aid: budget_snapshot_to_dict(b) for aid, b in snap.budgets.items()},
        "events": [event_to_dict(e) for e in snap.events],
        "errors": snap.errors,
        "task_definitions": snap.task_definitions,
    }


def snapshot_to_summary(snap: WorkflowSnapshot) -> dict[str, Any]:
    """Convert a WorkflowSnapshot to a summary dict for the list view."""
    return {
        "workflow_id": snap.workflow_id,
        "name": snap.workflow_name,
        "status": snap.status,
        "task_count": snap.task_count,
        "started_at": _dt(snap.started_at),
        "completed_at": _dt(snap.completed_at),
        "total_cost": snap.total_cost,
        "event_count": snap.event_count,
        "task_definitions": snap.task_definitions,
    }
