"""CLI workflow commands — run and verify workflows."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
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
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig


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

    def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
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

    errors: list[str] = []
    warnings: list[str] = []
    task_names = set(wf.tasks.keys())
    agent_names = set(wf.agents.keys())

    # Check missing dependencies
    for name, config in wf.tasks.items():
        for dep in config.depends_on:
            if dep not in task_names:
                errors.append(f"Task {name!r} depends on {dep!r}, which does not exist")

    # Check agent references
    for name, config in wf.tasks.items():
        if config.agent and config.agent not in agent_names:
            errors.append(f"Task {name!r} references agent {config.agent!r}, which is not defined")

    # Cycle detection via Kahn's algorithm
    adj: dict[str, list[str]] = defaultdict(list)
    in_deg: dict[str, int] = {name: 0 for name in task_names}
    for name, config in wf.tasks.items():
        for dep in config.depends_on:
            if dep in task_names:
                adj[dep].append(name)
                in_deg[name] += 1

    queue = [n for n, d in in_deg.items() if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for dep in adj[node]:
            in_deg[dep] -= 1
            if in_deg[dep] == 0:
                queue.append(dep)

    if visited != len(task_names):
        errors.append("Workflow contains a cycle")

    # Check for unreachable tasks (no path from any root)
    roots = {name for name, config in wf.tasks.items() if not config.depends_on}
    if not roots and wf.tasks:
        errors.append("No root tasks found (all tasks have dependencies)")

    # Check gates have no agent assigned
    for name, config in wf.tasks.items():
        if config.type in ("approval_gate", "input_gate") and config.agent:
            warnings.append(f"Gate {name!r} has an agent assigned (will be ignored)")

    # Report
    click.echo(f"Workflow: {wf.name}")
    click.echo(f"Tasks: {len(wf.tasks)} | Agents: {len(wf.agents)}")
    click.echo()

    if errors:
        for err in errors:
            click.echo(click.style(f"  ERROR: {err}", fg="red"))
        click.echo()
        click.echo(click.style("Verification FAILED", fg="red", bold=True))
        raise SystemExit(1)

    if warnings:
        for warn in warnings:
            click.echo(click.style(f"  WARN: {warn}", fg="yellow"))
        click.echo()

    click.echo(click.style("Verification PASSED", fg="green", bold=True))
