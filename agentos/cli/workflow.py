"""CLI workflow commands — run and verify workflows."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime
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

# Mapping from YAML tool names to Claude Code CLI tool names for Tier 2 adapters.
TIER2_TOOL_MAP = {
    "file_read": "Read",
    "file_write": "Write",
    "shell_exec": "Bash",
    "web_search": "WebSearch",
}


def _build_live_executor(
    wf: WorkflowDefinition,
    budget_mgr: BudgetManager,
    gate_mgr: GateManager,
    ws_root: "Path",
    *,
    interactive: bool = False,
):
    """Build a task executor that uses real adapters for live execution.

    Creates Tier1Adapter or ClaudeCodeAdapter per agent based on the
    ``adapter`` field in the workflow YAML.  Returns a callable matching
    the DAGExecutor's ``TaskExecutorFn`` signature.
    """
    from anthropic import Anthropic

    from agentos.adapters.tier1 import Tier1Adapter
    from agentos.adapters.tier2_claude_code import ClaudeCodeAdapter

    # Check for required API key if any agents use tier1
    has_tier1 = any(a.adapter == "tier1" for a in wf.agents.values())
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if has_tier1 and not api_key:
        raise click.ClickException(
            "ANTHROPIC_API_KEY environment variable is required for Tier 1 agents. "
            "Set it with: export ANTHROPIC_API_KEY=sk-..."
        )

    # Create adapters for each agent
    adapters = {}
    client = Anthropic() if has_tier1 else None

    for name, agent_cfg in wf.agents.items():
        if agent_cfg.adapter == "tier1":
            adapters[name] = Tier1Adapter(
                client=client,
                model=agent_cfg.model,
                budget_manager=budget_mgr,
                agent_id=name,
            )
        elif agent_cfg.adapter == "tier2_claude_code":
            timeout = int(agent_cfg.budget.max_time_seconds
                          or wf.budget.max_time_seconds
                          or 300)

            def _make_log_fn(agent_name: str):
                def log_fn(msg: str) -> None:
                    ts = datetime.now().strftime("%H:%M:%S")
                    click.echo(f"  [{ts}]        {click.style(agent_name, fg='cyan')} | {msg}")
                return log_fn

            adapters[name] = ClaudeCodeAdapter(
                budget_manager=budget_mgr,
                agent_id=name,
                timeout=timeout,
                log_fn=_make_log_fn(name),
            )
        else:
            raise click.ClickException(
                f"Unknown adapter type: {agent_cfg.adapter!r} for agent {name!r}"
            )

    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def task_executor(task_name: str, config: TaskConfig, predecessors=None):
        predecessors = predecessors or []

        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            prompt_text = config.prompt or "Approve this gate?"
            click.echo()
            click.echo(f"  [{_ts()}] {click.style('GATE', fg='yellow', bold=True)}  {task_name}")
            click.echo(f"           {prompt_text}")
            click.echo()

            if not interactive:
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
                click.echo(f"           Auto-approved (use --interactive for manual gates)")
                return TaskStatus.SUCCEEDED, None

            response = click.prompt(
                click.style("           [Enter] to approve, or type feedback to reject", fg="yellow"),
                default="", show_default=False,
            )
            if response.strip() == "":
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="human")
                click.echo(f"           {click.style('Approved', fg='green')}")
                return TaskStatus.SUCCEEDED, None
            else:
                gate_mgr.resolve_gate(
                    gate_id, GateResolution.REJECTED,
                    reviewer="human", feedback=response.strip(),
                )
                click.echo(f"           {click.style('Rejected', fg='red')}: {response.strip()}")
                return TaskStatus.FAILED, None

        agent_id = config.agent or "unassigned"
        agent_cfg = wf.agents.get(agent_id)
        adapter = adapters.get(agent_id)

        if adapter is None:
            click.echo(f"  [{_ts()}] {click.style('FAIL', fg='red')}  {task_name} — no adapter for agent {agent_id!r}")
            return TaskStatus.FAILED, TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.FAILED,
                summary=f"No adapter configured for agent {agent_id!r}.",
            )

        tier_label = f"tier{adapter.tier}"
        click.echo(f"  [{_ts()}] {click.style('START', fg='blue')} {task_name} ({agent_id} / {tier_label})")

        # Map tool names for Tier 2
        allowed_tools = agent_cfg.tools if agent_cfg else []
        if agent_cfg and agent_cfg.adapter == "tier2_claude_code":
            allowed_tools = [TIER2_TOOL_MAP.get(t, t) for t in allowed_tools]

        workspace_path = ws_root / config.workspace
        workspace_path.mkdir(parents=True, exist_ok=True)

        try:
            output = asyncio.run(adapter.execute_task(
                task_description=config.description,
                role=agent_cfg.role if agent_cfg else "",
                workspace=workspace_path,
                predecessor_context=predecessors,
                allowed_tools=allowed_tools,
            ))
            output.task_id = task_name

            if output.status == TaskStatus.SUCCEEDED:
                click.echo(f"  [{_ts()}] {click.style('DONE', fg='green')}  {task_name}")
            else:
                click.echo(f"  [{_ts()}] {click.style('FAIL', fg='red')}  {task_name}")

            if output.metrics:
                click.echo(
                    f"           tokens={output.metrics.tokens_consumed} "
                    f"cost=${output.metrics.estimated_cost_usd:.4f} "
                    f"time={output.metrics.execution_time_seconds:.1f}s"
                )
            if output.summary:
                # Truncate long summaries for terminal readability
                summary = output.summary if len(output.summary) <= 120 else output.summary[:117] + "..."
                click.echo(f"           {click.style(summary, dim=True)}")

            return output.status, output

        except Exception as exc:
            click.echo(f"  [{_ts()}] {click.style('FAIL', fg='red')}  {task_name} — {exc}")
            return TaskStatus.FAILED, TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.FAILED,
                summary=f"Adapter error: {exc}",
            )

    return task_executor


@click.group()
def workflow() -> None:
    """Manage workflows — run, verify."""


@workflow.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--db", default=":memory:", help="SQLite database path (default: in-memory)")
@click.option("--live", is_flag=True, default=False,
              help="Use real adapters (Tier 1 API / Tier 2 Claude Code).")
@click.option("--interactive", is_flag=True, default=False,
              help="Prompt for manual approval at gates instead of auto-approving.")
def run(yaml_file: str, db: str, live: bool, interactive: bool) -> None:
    """Run a workflow from a YAML file.

    By default uses stub executors for testing. Use --live for real
    adapters (requires ANTHROPIC_API_KEY for Tier 1 agents).
    Use --interactive for manual gate approval prompts.
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

    if live:
        task_executor = _build_live_executor(wf, budget_mgr, gate_mgr, ws_root, interactive=interactive)
    else:
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

    mode = click.style("LIVE", fg="yellow", bold=True) if live else "stub"
    click.echo(f"{'─' * 60}")
    click.echo(f"  Workflow:  {wf.name}")
    click.echo(f"  ID:        {workflow_id}")
    click.echo(f"  Tasks:     {len(wf.tasks)}  |  Agents: {len(wf.agents)}  |  Mode: {mode}")
    if db != ":memory:":
        click.echo(f"  DB:        {db}")
    click.echo(f"{'─' * 60}")
    click.echo()

    run_start = time.monotonic()

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
    )
    result = executor.run(workflow_id)

    elapsed = time.monotonic() - run_start

    click.echo()
    click.echo(f"{'─' * 60}")
    status_color = {"succeeded": "green", "failed": "red"}.get(result.status, "yellow")
    click.echo(f"  Result:    {click.style(result.status.upper(), fg=status_color, bold=True)}")
    click.echo(f"  Completed: {len(result.completed_tasks)}  |  "
               f"Failed: {len(result.failed_tasks)}  |  "
               f"Skipped: {len(result.skipped_tasks)}")
    click.echo(f"  Wall time: {elapsed:.1f}s")
    if db != ":memory:":
        click.echo(f"  DB:        {db}")
    click.echo(f"{'─' * 60}")


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
