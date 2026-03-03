"""Click-based CLI entry point for AgentOS."""

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
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig


@click.group()
def cli() -> None:
    """AgentOS — governance and orchestration for autonomous AI agents."""


# Register subcommand groups and standalone commands
from agentos.cli.gate import gate  # noqa: E402
from agentos.cli.status import cost, events, status  # noqa: E402
from agentos.cli.workflow import workflow  # noqa: E402

cli.add_command(workflow)
cli.add_command(gate)
cli.add_command(status)
cli.add_command(events)
cli.add_command(cost)


@cli.command()
@click.argument("yaml_file", default="examples/linear_research.yaml", type=click.Path(exists=True))
@click.option("--db", default=":memory:", help="SQLite database path (default: in-memory)")
def demo(yaml_file: str, db: str) -> None:
    """Run a workflow with stub executors (no real LLM calls).

    Loads a workflow YAML, validates the DAG, runs it with simulated agents,
    enforces budgets, and prints a summary of the full event log.
    """
    # --- Load workflow YAML ---
    yaml_path = Path(yaml_file)
    click.echo(click.style(f"Loading workflow: {yaml_path}", fg="cyan"))

    raw = yaml.safe_load(yaml_path.read_text())
    workflow = WorkflowDefinition.model_validate(raw)

    click.echo(f"  Name: {workflow.name}")
    click.echo(f"  Tasks: {len(workflow.tasks)}")
    click.echo(f"  Agents: {len(workflow.agents)}")
    click.echo()

    # --- Initialize kernel components ---
    event_log = SQLiteEventLog(db)
    seq = SeqCounter()
    workflow_id = f"demo-{uuid.uuid4().hex[:8]}"

    agent_specs = {name: agent.budget for name, agent in workflow.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=workflow.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs=agent_specs,
    )

    # --- Workspace ---
    ws_root = Path(f"/tmp/agentos-demo-{workflow_id}")
    ws_config = WorkspaceConfig(root=str(ws_root))
    workspace = Workspace(ws_config, event_log, seq, workflow_id=workflow_id)
    workspace.ensure_root()

    # --- Gate manager ---
    gate_mgr = GateManager(event_log, seq, workflow_id)

    click.echo(f"  Workspace: {ws_root}")
    click.echo()

    # --- Stub task executor ---
    def task_executor(task_name: str, config: TaskConfig) -> TaskStatus:
        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            click.echo(click.style(f"  GATE  {task_name}", fg="yellow") +
                       f" — {config.prompt or 'Awaiting approval'}")
            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="demo")
            click.echo(click.style("        ✓ auto-approved (demo mode)", fg="yellow"))
            time.sleep(0.2)
            return TaskStatus.SUCCEEDED

        agent_id = config.agent or "unassigned"
        click.echo(click.style(f"  RUN   {task_name}", fg="blue") +
                   f" (agent: {agent_id})")
        if config.description:
            desc = config.description.strip()
            if len(desc) > 100:
                desc = desc[:97] + "..."
            click.echo(f"        {desc}")

        time.sleep(0.5)

        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500,
            api_calls=1,
            time_seconds=0.5,
            cost_usd=0.01,
        ))

        # Write a stub output file into the workspace
        output_content = (
            f"# Task: {task_name}\n"
            f"Agent: {agent_id}\n"
            f"Status: succeeded\n"
            f"Summary: Stub output for demo — no real LLM call.\n"
        )
        workspace.write_file(
            f"{task_name}/output.md", output_content,
            agent_id=agent_id, task_id=task_name,
        )

        click.echo(click.style(f"  DONE  {task_name}", fg="green") +
                   f" → {task_name}/output.md")
        return TaskStatus.SUCCEEDED

    # --- Execute ---
    click.echo(click.style("=" * 60, fg="cyan"))
    click.echo(click.style(f" Executing workflow: {workflow.name}", fg="cyan", bold=True))
    click.echo(click.style("=" * 60, fg="cyan"))
    click.echo()

    executor = DAGExecutor(
        workflow=workflow,
        event_log=event_log,
        seq=seq,
        budget_manager=budget_mgr,
        task_executor=task_executor,
    )
    result = executor.run(workflow_id)

    # --- Summary ---
    click.echo()
    click.echo(click.style("=" * 60, fg="cyan"))
    click.echo(click.style(" Result", fg="cyan", bold=True))
    click.echo(click.style("=" * 60, fg="cyan"))

    status_color = "green" if result.status == "succeeded" else "red"
    click.echo(f"  Workflow: {click.style(result.status.upper(), fg=status_color, bold=True)}")
    click.echo(f"  Completed: {len(result.completed_tasks)}")
    click.echo(f"  Failed:    {len(result.failed_tasks)}")
    click.echo(f"  Skipped:   {len(result.skipped_tasks)}")

    # --- Budget summary ---
    click.echo()
    click.echo(click.style(" Budget Usage", fg="cyan", bold=True))
    click.echo(click.style("-" * 40, fg="cyan"))
    total = budget_mgr.total_usage
    click.echo(f"  Tokens:     {total.tokens_used:,}")
    click.echo(f"  API calls:  {total.api_calls_made}")
    click.echo(f"  Time:       {total.time_elapsed_seconds:.1f}s")
    click.echo(f"  Cost:       ${total.cost_usd:.2f}")

    if workflow.budget.max_tokens:
        pct = total.tokens_used / workflow.budget.max_tokens * 100
        click.echo(f"  Token cap:  {pct:.0f}% of {workflow.budget.max_tokens:,}")
    if workflow.budget.max_cost_usd:
        pct = total.cost_usd / workflow.budget.max_cost_usd * 100
        click.echo(f"  Cost cap:   {pct:.0f}% of ${workflow.budget.max_cost_usd:.2f}")

    # --- Workspace summary ---
    manifest = workspace.manifest
    if manifest:
        click.echo()
        click.echo(click.style(" Workspace Files", fg="cyan", bold=True))
        click.echo(click.style("-" * 40, fg="cyan"))
        for entry in manifest:
            click.echo(f"  {click.style(entry.operation.value, fg='green'):10s} "
                       f"{entry.path:30s} ({entry.agent_id}, {entry.size_bytes}B)")
        click.echo(f"  Root: {ws_root}")

    # --- Gate summary ---
    all_gates = gate_mgr.list_all()
    if all_gates:
        click.echo()
        click.echo(click.style(" Gates", fg="cyan", bold=True))
        click.echo(click.style("-" * 40, fg="cyan"))
        for g in all_gates:
            if g.pending:
                res_str = click.style("PENDING", fg="yellow")
            elif g.resolution == GateResolution.APPROVED:
                res_str = click.style("APPROVED", fg="green")
            else:
                res_str = click.style(str(g.resolution).upper(), fg="red")
            prompt_str = g.prompt[:50] + "..." if len(g.prompt) > 50 else g.prompt
            click.echo(f"  {g.gate_id}  {res_str}  {prompt_str}")

    # --- Event log replay ---
    click.echo()
    click.echo(click.style(" Event Log", fg="cyan", bold=True))
    click.echo(click.style("-" * 60, fg="cyan"))

    events = event_log.replay(workflow_id)
    for event in events:
        etype = event.event_type.value
        color = _event_color(etype)
        ts = event.timestamp.strftime("%H:%M:%S")
        detail = _event_detail(event)
        click.echo(f"  {click.style(f'[{event.seq:>3}]', dim=True)} "
                   f"{ts} {click.style(etype, fg=color):40s} {detail}")

    click.echo()
    click.echo(f"  Total events: {len(events)}")
    if db != ":memory:":
        click.echo(f"  Persisted to: {db}")
    click.echo()


def _event_color(event_type: str) -> str:
    """Pick a terminal color based on event type prefix."""
    if event_type.startswith("workflow"):
        return "cyan"
    if event_type.startswith("task"):
        return "blue"
    if event_type.startswith("budget.exceeded"):
        return "red"
    if event_type.startswith("budget"):
        return "magenta"
    if event_type.startswith("gate"):
        return "yellow"
    if event_type.startswith("file"):
        return "green"
    return "white"


def _event_detail(event: object) -> str:
    """Extract a short detail string from an event's payload."""
    payload = event.payload  # type: ignore[attr-defined]
    if "path" in payload:
        return f"{payload.get('operation', '')} {payload['path']}"
    if "gate_id" in payload:
        parts = [payload["gate_id"]]
        if "resolution" in payload:
            parts.append(f"→ {payload['resolution']}")
        elif "prompt" in payload and payload["prompt"]:
            prompt = payload["prompt"]
            parts.append(f'"{prompt[:40]}"')
        return " ".join(parts)
    if "task_id" in payload:
        parts = [payload["task_id"]]
        if "to_state" in payload:
            parts.append(f"→ {payload['to_state']}")
        return " ".join(parts)
    if "status" in payload:
        return payload["status"]
    if "agent_id" in payload:
        return payload["agent_id"]
    if "workflow_name" in payload:
        return payload["workflow_name"]
    return ""


if __name__ == "__main__":
    cli()
