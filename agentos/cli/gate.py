"""CLI gate commands — list, approve, and reject gates."""

from __future__ import annotations

import click

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateError, GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.gate import GateResolution


@click.group()
def gate() -> None:
    """Manage approval and input gates."""


@gate.command("list")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--workflow-id", default=None, help="Filter by workflow ID")
@click.option("--all", "show_all", is_flag=True, help="Show resolved gates too")
def list_gates(db: str, workflow_id: str | None, show_all: bool) -> None:
    """List gates from a persisted database."""
    event_log = SQLiteEventLog(db)
    seq = SeqCounter()

    # Find workflow IDs if not specified
    from agentos.schemas.events import EventType
    wf_ids = _get_workflow_ids(event_log, workflow_id)

    if not wf_ids:
        click.echo("No workflows found.")
        return

    found = False
    for wf_id in wf_ids:
        mgr = GateManager(event_log, seq, wf_id)
        gates = mgr.list_all() if show_all else mgr.list_pending()

        if not gates:
            continue

        found = True
        click.echo(f"  Workflow: {click.style(wf_id, bold=True)}")
        for g in gates:
            if g.pending:
                status_str = click.style("PENDING", fg="yellow")
            else:
                res = str(g.resolution).upper() if g.resolution else "?"
                color = "green" if g.resolution == GateResolution.APPROVED else "red"
                status_str = click.style(res, fg=color)

            click.echo(f"    {g.gate_id}  {status_str:10s}  {g.gate_type}  {g.prompt}")

            if g.feedback:
                click.echo(f"      Feedback: {g.feedback}")
            if g.reviewer:
                click.echo(f"      Reviewer: {g.reviewer}")
        click.echo()

    if not found:
        label = "gates" if show_all else "pending gates"
        click.echo(f"No {label} found.")


@gate.command("approve")
@click.argument("gate_id")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--reviewer", default="cli-user", help="Reviewer name")
@click.option("--feedback", default=None, help="Optional feedback")
def approve_gate(gate_id: str, db: str, reviewer: str, feedback: str | None) -> None:
    """Approve a pending gate."""
    event_log = SQLiteEventLog(db)
    seq = _resume_seq(event_log)

    wf_id = _find_gate_workflow(event_log, gate_id)
    if wf_id is None:
        click.echo(click.style(f"Gate not found: {gate_id}", fg="red"))
        raise SystemExit(1)

    mgr = GateManager(event_log, seq, wf_id)
    try:
        state = mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer, feedback)
        click.echo(click.style(f"Gate {gate_id} APPROVED", fg="green"))
        if feedback:
            click.echo(f"  Feedback: {feedback}")
    except GateError as exc:
        click.echo(click.style(str(exc), fg="red"))
        raise SystemExit(1)


@gate.command("reject")
@click.argument("gate_id")
@click.option("--db", required=True, type=click.Path(exists=True), help="SQLite database path")
@click.option("--reviewer", default="cli-user", help="Reviewer name")
@click.option("--feedback", default=None, help="Reason for rejection")
def reject_gate(gate_id: str, db: str, reviewer: str, feedback: str | None) -> None:
    """Reject a pending gate."""
    event_log = SQLiteEventLog(db)
    seq = _resume_seq(event_log)

    wf_id = _find_gate_workflow(event_log, gate_id)
    if wf_id is None:
        click.echo(click.style(f"Gate not found: {gate_id}", fg="red"))
        raise SystemExit(1)

    mgr = GateManager(event_log, seq, wf_id)
    try:
        state = mgr.resolve_gate(gate_id, GateResolution.REJECTED, reviewer, feedback)
        click.echo(click.style(f"Gate {gate_id} REJECTED", fg="red"))
        if feedback:
            click.echo(f"  Feedback: {feedback}")
    except GateError as exc:
        click.echo(click.style(str(exc), fg="red"))
        raise SystemExit(1)


def _get_workflow_ids(event_log: SQLiteEventLog, workflow_id: str | None) -> list[str]:
    """Get workflow IDs, either the specified one or all from the DB."""
    from agentos.schemas.events import EventType
    if workflow_id:
        return [workflow_id]
    started = event_log.query(event_type=EventType.WORKFLOW_STARTED)
    return [e.workflow_id for e in started]


def _find_gate_workflow(event_log: SQLiteEventLog, gate_id: str) -> str | None:
    """Find which workflow a gate belongs to by scanning GATE_WAITING events."""
    from agentos.schemas.events import EventType
    events = event_log.query(event_type=EventType.GATE_WAITING)
    for event in events:
        if event.payload.get("gate_id") == gate_id:
            return event.workflow_id
    return None


def _resume_seq(event_log: SQLiteEventLog) -> SeqCounter:
    """Create a SeqCounter that continues from the highest seq in the DB.

    This is needed when appending to a persisted DB from a separate process.
    """
    from agentos.schemas.events import EventType
    all_events = event_log.query()
    if not all_events:
        return SeqCounter()
    max_seq = max(e.seq for e in all_events)
    return SeqCounter(start=max_seq + 1)
