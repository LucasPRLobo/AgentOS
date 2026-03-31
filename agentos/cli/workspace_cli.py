"""CLI commands for the workspace runtime."""

from __future__ import annotations

from pathlib import Path

import click

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter


def _init_runtime(yaml_path: str, db: str):
    """Helper: load config + create runtime."""
    from agentos.workspace.loader import load_workspace_config
    from agentos.workspace.runtime import WorkspaceRuntime

    config = load_workspace_config(Path(yaml_path))
    event_log = SQLiteEventLog(db)
    seq = SeqCounter()
    wf_id = f"ws-{config.name.lower().replace(' ', '-')}"
    runtime = WorkspaceRuntime(config, event_log, seq, wf_id)
    return runtime


# ======================================================================
# Workspace group
# ======================================================================

@click.group("workspace")
def workspace_group() -> None:
    """Manage collaborative workspaces."""


@workspace_group.command("create")
@click.argument("yaml_path", type=click.Path(exists=True))
@click.option("--db", default="agentos.db", help="Database path")
def workspace_create(yaml_path: str, db: str) -> None:
    """Create and start a workspace from a YAML config."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()

    board = runtime.get_board_state()
    summary = runtime.get_backlog_summary()

    click.echo(f"Workspace '{runtime.config.name}' created.")
    click.echo(f"Goal: {runtime.config.goal}")
    click.echo(f"Team: {len(runtime.config.team)} participants")
    click.echo(f"Team mode: {runtime.config.team_mode}")
    click.echo(runtime.board.render_compact(max_tokens=300))


@workspace_group.command("show")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db", help="Database path")
def workspace_show(yaml_path: str, db: str) -> None:
    """Show workspace status — board, backlog, team."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()

    click.echo(runtime.board.render_compact(max_tokens=500))
    click.echo("")

    summary = runtime.get_backlog_summary()
    click.echo(f"Backlog: {summary['total']} tasks "
               f"({summary['open']} open, {summary['in_progress']} active, "
               f"{summary['done']} done, {summary['blocked']} blocked)")


@workspace_group.command("lock-team")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db")
def workspace_lock_team(yaml_path: str, db: str) -> None:
    """Lock the team structure — no more changes."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()
    runtime.lock_team()
    click.echo("Team locked.")


@workspace_group.command("export")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
def workspace_export(yaml_path: str) -> None:
    """Export the workspace config as YAML."""
    import yaml as _yaml
    from agentos.workspace.loader import load_workspace_config

    config = load_workspace_config(Path(yaml_path))
    click.echo(_yaml.dump({"workspace": config.model_dump(mode="json")}, default_flow_style=False))


# ======================================================================
# Task group
# ======================================================================

@click.group("task")
def task_group() -> None:
    """Manage workspace backlog tasks."""


@task_group.command("add")
@click.argument("title")
@click.option("--description", "-d", default="")
@click.option("--depends-on", multiple=True, help="Task IDs this depends on")
@click.option("--priority", type=click.Choice(["low", "normal", "high", "critical"]), default="normal")
@click.option("--suggested-for", default=None)
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db")
def task_add(title, description, depends_on, priority, suggested_for, yaml_path, db):
    """Add a task to the backlog."""
    from agentos.workspace.schemas import BacklogTask

    runtime = _init_runtime(yaml_path, db)
    runtime.start()

    task = BacklogTask(
        title=title,
        description=description,
        created_by="human",
        depends_on=list(depends_on),
        priority=priority,
        suggested_for=suggested_for,
    )
    tid = runtime.add_task(task)
    click.echo(f"Task created: {tid}")
    click.echo(f"  Title: {title}")
    click.echo(f"  Status: {task.status}")


@task_group.command("claim")
@click.argument("task_id")
@click.option("--as", "participant", default="human", help="Claim as this participant")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db")
def task_claim(task_id, participant, yaml_path, db):
    """Claim a task from the backlog."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()
    runtime.claim_task(task_id, participant)
    click.echo(f"Task {task_id} claimed by {participant}.")


@task_group.command("complete")
@click.argument("task_id")
@click.option("--summary", "-s", default="Task completed.")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db")
def task_complete(task_id, summary, yaml_path, db):
    """Mark a task as done."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()
    runtime.complete_task(task_id, {"summary": summary})
    click.echo(f"Task {task_id} completed.")


@task_group.command("list")
@click.option("--status", type=click.Choice(["open", "claimed", "in_progress", "done", "blocked", "all"]),
              default="all")
@click.option("--yaml", "yaml_path", type=click.Path(exists=True), required=True)
@click.option("--db", default="agentos.db")
def task_list(status, yaml_path, db):
    """List backlog tasks."""
    runtime = _init_runtime(yaml_path, db)
    runtime.start()

    tasks = runtime.backlog.get_all_tasks()
    if status != "all":
        tasks = [t for t in tasks if t.status == status]

    if not tasks:
        click.echo("No tasks found.")
        return

    for t in tasks:
        assigned = f" → {t.assigned_to}" if t.assigned_to else ""
        click.echo(f"  [{t.status:12s}] {t.task_id[:8]}  {t.title}{assigned}")
