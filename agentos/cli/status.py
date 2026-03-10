"""CLI status commands — inspect workflow state, events, costs, and replay."""

from __future__ import annotations

import click

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.replayer import WorkflowReplayer
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskStatus


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


@click.command("replay")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--workflow-id", required=True, help="Workflow ID to replay")
def replay(db: str, workflow_id: str) -> None:
    """Replay a workflow execution — full state reconstruction from events."""
    event_log = SQLiteEventLog(db)
    replayer = WorkflowReplayer(event_log)
    snap = replayer.replay(workflow_id)

    if snap.event_count == 0:
        click.echo(f"No events found for workflow: {workflow_id}")
        return

    # Header
    color_map = {"succeeded": "green", "failed": "red", "paused": "yellow", "running": "blue"}
    status_color = color_map.get(snap.status, "white")

    click.echo(click.style("=" * 60, fg="cyan"))
    click.echo(click.style(f" Workflow Replay: {snap.workflow_name or workflow_id}", fg="cyan", bold=True))
    click.echo(click.style("=" * 60, fg="cyan"))
    click.echo(f"  ID:      {snap.workflow_id}")
    click.echo(f"  Status:  {click.style(snap.status.upper(), fg=status_color, bold=True)}")
    click.echo(f"  Tasks:   {snap.task_count}")
    click.echo(f"  Events:  {snap.event_count}")
    if snap.started_at:
        click.echo(f"  Started: {snap.started_at}")
    if snap.completed_at:
        click.echo(f"  Ended:   {snap.completed_at}")

    # Tasks
    if snap.tasks:
        click.echo()
        click.echo(click.style(" Tasks", fg="cyan", bold=True))
        click.echo(click.style("-" * 50, fg="cyan"))
        state_colors = {
            TaskStatus.SUCCEEDED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.WAITING: "yellow",
            TaskStatus.RUNNING: "blue",
            TaskStatus.PENDING: "white",
        }
        for name, task in sorted(snap.tasks.items()):
            sc = state_colors.get(task.state, "white")
            state_str = click.style(task.state.value.upper(), fg=sc)
            click.echo(f"  {name:25s} {state_str:20s} agent={task.agent_id or '-'}")
            if task.output and task.output.summary:
                summary = task.output.summary[:60]
                click.echo(f"  {'':25s} {summary}")

    # Agents
    if snap.agents:
        click.echo()
        click.echo(click.style(" Agents", fg="cyan", bold=True))
        click.echo(click.style("-" * 50, fg="cyan"))
        for aid, agent in sorted(snap.agents.items()):
            term = agent.termination_reason or "active"
            tier_str = f"T{agent.adapter_tier}"
            click.echo(f"  {aid:20s} {agent.agent_name:15s} {tier_str:5s} {term}")

    # Gates
    if snap.gates:
        click.echo()
        click.echo(click.style(" Gates", fg="cyan", bold=True))
        click.echo(click.style("-" * 50, fg="cyan"))
        for gid, gate in snap.gates.items():
            if gate.resolution:
                res_color = "green" if gate.resolution == "approved" else "red"
                res_str = click.style(gate.resolution.upper(), fg=res_color)
            else:
                res_str = click.style("PENDING", fg="yellow")
            click.echo(f"  {gid}  {res_str}  task={gate.task_id}")

    # Budget
    if snap.budgets:
        click.echo()
        click.echo(click.style(" Budget", fg="cyan", bold=True))
        click.echo(click.style("-" * 55, fg="cyan"))
        click.echo(f"  {'Agent':20s} {'Tokens':>8s} {'Calls':>6s} {'Time':>7s} {'Cost':>8s}")
        click.echo(click.style("-" * 55, fg="cyan"))
        for aid, budget in sorted(snap.budgets.items()):
            u = budget.usage
            exceeded_mark = click.style(" !", fg="red") if budget.exceeded else ""
            click.echo(f"  {aid:20s} {u.tokens_used:>8,} {u.api_calls_made:>6} "
                       f"{u.time_elapsed_seconds:>6.1f}s ${u.cost_usd:>7.2f}{exceeded_mark}")
        click.echo(click.style("-" * 55, fg="cyan"))
        click.echo(f"  {'TOTAL':20s} {snap.total_tokens:>8,} "
                   f"{'':>6} {'':>7s} ${snap.total_cost:>7.2f}")

    # Errors
    if snap.errors:
        click.echo()
        click.echo(click.style(" Errors", fg="red", bold=True))
        click.echo(click.style("-" * 50, fg="red"))
        for err in snap.errors:
            click.echo(f"  {err}")

    # Event timeline
    click.echo()
    click.echo(click.style(" Event Timeline", fg="cyan", bold=True))
    click.echo(click.style("-" * 60, fg="cyan"))
    for event in snap.events:
        etype = event.event_type.value
        ts = event.timestamp.strftime("%H:%M:%S")
        detail = _payload_summary(event.payload)
        click.echo(f"  [{event.seq:>3}] {ts} {etype:35s} {detail}")

    click.echo()
    click.echo(f"  Total: {snap.event_count} events")
    click.echo()


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
