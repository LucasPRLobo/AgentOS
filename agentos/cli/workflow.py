"""CLI workflow commands — run and verify workflows."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import click
import yaml

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig
from agentos.validation.workflow_verifier import WorkflowVerifier


@click.group()
def workflow() -> None:
    """Manage workflows — run, verify."""


@workflow.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--db", default=":memory:", help="SQLite database path (default: in-memory)")
def run(yaml_file: str, db: str) -> None:
    """Run a workflow from a YAML file with stub executors.

    Gates are auto-approved. Use `agentos gate` commands for manual
    gate resolution with a persisted --db.
    """
    yaml_path = Path(yaml_file)
    raw = yaml.safe_load(yaml_path.read_text())
    wf = WorkflowDefinition.model_validate(raw)

    event_log = SQLiteEventLog(db)
    seq = SeqCounter()
    workflow_id = f"run-{uuid.uuid4().hex[:8]}"

    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs=agent_specs,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    ws_root = Path(f"/tmp/agentos-{workflow_id}")
    workspace = Workspace(
        WorkspaceConfig(root=str(ws_root)),
        event_log, seq, workflow_id=workflow_id,
    )
    workspace.ensure_root()

    def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
            click.echo(f"  GATE  {task_name} — auto-approved")
            return TaskStatus.SUCCEEDED

        agent_id = config.agent or "unassigned"
        click.echo(f"  RUN   {task_name} (agent: {agent_id})")
        time.sleep(0.3)

        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500, api_calls=1, time_seconds=0.3, cost_usd=0.01,
        ))

        workspace.write_file(
            f"{task_name}/output.md",
            f"# {task_name}\nAgent: {agent_id}\nStatus: succeeded\n",
            agent_id=agent_id, task_id=task_name,
        )

        click.echo(f"  DONE  {task_name}")
        return TaskStatus.SUCCEEDED

    click.echo(f"Running workflow: {wf.name} ({len(wf.tasks)} tasks)")
    click.echo(f"Workflow ID: {workflow_id}")
    click.echo()

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
    )
    result = executor.run(workflow_id)

    status_color = "green" if result.status == "succeeded" else "red"
    click.echo()
    click.echo(f"Result: {click.style(result.status.upper(), fg=status_color)}")
    click.echo(f"Completed: {len(result.completed_tasks)} | "
               f"Failed: {len(result.failed_tasks)} | "
               f"Skipped: {len(result.skipped_tasks)}")

    if db != ":memory:":
        click.echo(f"Persisted to: {db}")


@workflow.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.argument("workflow_id")
@click.option("--db", required=True, help="SQLite database path with the paused workflow")
def resume(yaml_file: str, workflow_id: str, db: str) -> None:
    """Resume a paused workflow after gates have been resolved.

    Requires the same YAML file used to start the workflow and the
    workflow ID printed during the initial run.
    """
    yaml_path = Path(yaml_file)
    raw = yaml.safe_load(yaml_path.read_text())
    wf = WorkflowDefinition.model_validate(raw)

    event_log = SQLiteEventLog(db)
    max_seq = event_log.last_seq(workflow_id)
    if max_seq < 0:
        click.echo(click.style(f"No events found for workflow {workflow_id!r}", fg="red"))
        raise SystemExit(1)

    seq = SeqCounter(start=max_seq + 1)
    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs=agent_specs,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    ws_root = Path(f"/tmp/agentos-{workflow_id}")
    workspace = Workspace(
        WorkspaceConfig(root=str(ws_root)),
        event_log, seq, workflow_id=workflow_id,
    )
    workspace.ensure_root()

    def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
        if config.type == "approval_gate":
            # On resume, gate tasks that are still waiting will be re-invoked
            # They should just return WAITING again
            gid = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            return TaskStatus.WAITING, None

        agent_id = config.agent or "unassigned"
        click.echo(f"  RUN   {task_name} (agent: {agent_id})")
        time.sleep(0.3)

        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500, api_calls=1, time_seconds=0.3, cost_usd=0.01,
        ))

        workspace.write_file(
            f"{task_name}/output.md",
            f"# {task_name}\nAgent: {agent_id}\nStatus: succeeded\n",
            agent_id=agent_id, task_id=task_name,
        )

        click.echo(f"  DONE  {task_name}")
        output = TaskOutput(
            task_id=task_name, agent_id=agent_id,
            status=TaskStatus.SUCCEEDED, summary=f"Completed {task_name}",
        )
        return TaskStatus.SUCCEEDED, output

    click.echo(f"Resuming workflow: {wf.name}")
    click.echo(f"Workflow ID: {workflow_id}")
    click.echo()

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
    )
    result = executor.resume(workflow_id)

    color = {"succeeded": "green", "failed": "red", "paused": "yellow"}
    click.echo()
    click.echo(f"Result: {click.style(result.status.upper(), fg=color.get(result.status, 'white'))}")
    click.echo(f"Completed: {len(result.completed_tasks)} | "
               f"Failed: {len(result.failed_tasks)} | "
               f"Waiting: {len(result.waiting_tasks)}")

    if result.status == "paused":
        pending = gate_mgr.list_pending()
        if pending:
            click.echo()
            click.echo("Pending gates:")
            for g in pending:
                click.echo(f"  {g.gate_id}  {g.prompt}")
            click.echo()
            click.echo(f"Resolve gates, then run:")
            click.echo(f"  agentos workflow resume {yaml_file} {workflow_id} --db {db}")

    if db != ":memory:":
        click.echo(f"Persisted to: {db}")


@workflow.command()
@click.argument("yaml_file", type=click.Path(exists=True))
def verify(yaml_file: str) -> None:
    """Verify a workflow YAML file without executing it.

    Checks: valid YAML, valid schema, no cycles, no missing dependencies,
    all task agents exist in agents section.
    """
    yaml_path = Path(yaml_file)

    try:
        raw = yaml.safe_load(yaml_path.read_text())
    except yaml.YAMLError as exc:
        click.echo(click.style(f"YAML parse error: {exc}", fg="red"))
        raise SystemExit(1)

    try:
        wf = WorkflowDefinition.model_validate(raw)
    except Exception as exc:
        click.echo(click.style(f"Schema validation error: {exc}", fg="red"))
        raise SystemExit(1)

    verifier = WorkflowVerifier()
    report = verifier.verify(wf)

    click.echo(f"Workflow: {wf.name}")
    click.echo(f"Tasks: {len(wf.tasks)} | Agents: {len(wf.agents)}")
    click.echo()

    if report.errors:
        for issue in report.errors:
            click.echo(click.style(f"  ERROR [{issue.code}]: {issue.message}", fg="red"))
        click.echo()
        click.echo(click.style("Verification FAILED", fg="red", bold=True))
        raise SystemExit(1)

    if report.warnings:
        for issue in report.warnings:
            click.echo(click.style(f"  WARN [{issue.code}]: {issue.message}", fg="yellow"))
        click.echo()

    click.echo(click.style("Verification PASSED", fg="green", bold=True))
