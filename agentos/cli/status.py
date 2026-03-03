"""CLI status commands — inspect workflow state, events, and costs."""

from __future__ import annotations

import click

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType


@click.command("status")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
def status(db: str) -> None:
    """Show the latest workflow status from a persisted database."""
    event_log = SQLiteEventLog(db)

    # Find all workflow IDs by scanning workflow.started events
    started = event_log.query(event_type=EventType.WORKFLOW_STARTED)
    if not started:
        click.echo("No workflows found in database.")
        return

    for ws_event in started:
        wf_id = ws_event.workflow_id
        wf_name = ws_event.payload.get("workflow_name", "unknown")
        task_count = ws_event.payload.get("task_count", "?")

        # Check completion
        completed = event_log.query(
            workflow_id=wf_id, event_type=EventType.WORKFLOW_COMPLETED,
        )
        if completed:
            wf_status = completed[-1].payload.get("status", "unknown")
            color = "green" if wf_status == "succeeded" else "red"
        else:
            wf_status = "running"
            color = "yellow"

        click.echo(f"  {click.style(wf_id, bold=True)}")
        click.echo(f"    Name:   {wf_name}")
        click.echo(f"    Tasks:  {task_count}")
        click.echo(f"    Status: {click.style(wf_status.upper(), fg=color)}")

        # Count events
        all_events = event_log.replay(wf_id)
        click.echo(f"    Events: {len(all_events)}")
        click.echo()


@click.command("events")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--type", "event_type", default=None, help="Filter by event type (e.g. task.state_changed)")
@click.option("--workflow-id", default=None, help="Filter by workflow ID")
def events(db: str, event_type: str | None, workflow_id: str | None) -> None:
    """Replay the event log from a persisted database."""
    event_log = SQLiteEventLog(db)

    et = EventType(event_type) if event_type else None
    results = event_log.query(workflow_id=workflow_id, event_type=et)

    if not results:
        click.echo("No events found.")
        return

    for event in results:
        ts = event.timestamp.strftime("%H:%M:%S")
        etype = event.event_type.value
        payload_summary = _payload_summary(event.payload)
        click.echo(f"  [{event.seq:>3}] {ts} {etype:35s} {payload_summary}")

    click.echo()
    click.echo(f"  Total: {len(results)} events")


@click.command("cost")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--agent", default=None, help="Filter by agent ID")
def cost(db: str, agent: str | None) -> None:
    """Show budget consumption from a persisted database."""
    event_log = SQLiteEventLog(db)

    budget_events = event_log.query(event_type=EventType.BUDGET_CONSUMED)
    if not budget_events:
        click.echo("No budget data found.")
        return

    # Aggregate by agent
    agent_totals: dict[str, dict[str, float]] = {}
    for event in budget_events:
        aid = event.payload.get("agent_id", "unknown")
        if agent and aid != agent:
            continue
        cumulative = event.payload.get("cumulative", {})
        agent_totals[aid] = {
            "tokens": cumulative.get("tokens_used", 0),
            "api_calls": cumulative.get("api_calls_made", 0),
            "time": cumulative.get("time_elapsed_seconds", 0.0),
            "cost": cumulative.get("cost_usd", 0.0),
        }

    if not agent_totals:
        click.echo(f"No budget data found for agent: {agent}")
        return

    click.echo(click.style(" Budget Usage by Agent", bold=True))
    click.echo("-" * 55)
    click.echo(f"  {'Agent':20s} {'Tokens':>8s} {'Calls':>6s} {'Time':>7s} {'Cost':>8s}")
    click.echo("-" * 55)

    total_tokens = 0
    total_calls = 0
    total_time = 0.0
    total_cost = 0.0

    for aid, totals in sorted(agent_totals.items()):
        t, c, s, usd = totals["tokens"], totals["api_calls"], totals["time"], totals["cost"]
        total_tokens += int(t)
        total_calls += int(c)
        total_time += s
        total_cost += usd
        click.echo(f"  {aid:20s} {int(t):>8,} {int(c):>6} {s:>6.1f}s ${usd:>7.2f}")

    click.echo("-" * 55)
    click.echo(f"  {'TOTAL':20s} {total_tokens:>8,} {total_calls:>6} "
               f"{total_time:>6.1f}s ${total_cost:>7.2f}")


def _payload_summary(payload: dict) -> str:
    """Short summary from event payload."""
    if "path" in payload:
        return f"{payload.get('operation', '')} {payload['path']}"
    if "task_id" in payload:
        parts = [payload["task_id"]]
        if "to_state" in payload:
            parts.append(f"→ {payload['to_state']}")
        return " ".join(parts)
    if "gate_id" in payload:
        parts = [payload["gate_id"]]
        if "resolution" in payload:
            parts.append(f"→ {payload['resolution']}")
        return " ".join(parts)
    if "status" in payload:
        return payload["status"]
    if "agent_id" in payload:
        return payload["agent_id"]
    if "workflow_name" in payload:
        return payload["workflow_name"]
    return ""
