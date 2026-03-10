"""Click-based CLI entry point for AgentOS."""

from __future__ import annotations

import asyncio
import json
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
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import Confidence, Finding, TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig


@click.group()
def cli() -> None:
    """AgentOS — governance and orchestration for autonomous AI agents."""


# Register subcommand groups and standalone commands
from agentos.cli.gate import gate  # noqa: E402
from agentos.cli.status import cost, events, replay, status  # noqa: E402
from agentos.cli.workflow import workflow  # noqa: E402

cli.add_command(workflow)
cli.add_command(gate)
cli.add_command(status)
cli.add_command(events)
cli.add_command(cost)
cli.add_command(replay)


@cli.command()
@click.argument("db", type=click.Path())
@click.option("--port", default=8420, help="Port to serve the dashboard on.")
@click.option("--host", default="127.0.0.1", help="Host to bind to.")
def dashboard(db: str, port: int, host: str) -> None:
    """Start the web dashboard for monitoring workflows.

    Requires the dashboard extra: pip install agentos[dashboard]
    """
    try:
        import uvicorn  # noqa: F401
        from agentos.dashboard.app import create_app  # noqa: F401
    except ImportError:
        click.echo(click.style(
            "Dashboard dependencies not installed.\n"
            "Install with: pip install agentos[dashboard]",
            fg="red",
        ))
        raise SystemExit(1)

    from agentos.dashboard.app import create_app

    app = create_app(db)
    click.echo(f"AgentOS Dashboard")
    click.echo(f"  DB:   {db}")
    click.echo(f"  URL:  http://{host}:{port}")
    click.echo()

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


# -- V2+ CLI Commands -------------------------------------------------------


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--db", default=":memory:", help="SQLite database path for historical data")
def safety(yaml_file: str, db: str) -> None:
    """Display 6-dimension safety score for a workflow."""
    from agentos.security.safety_score import SafetyScoreCalculator

    raw = yaml.safe_load(Path(yaml_file).read_text())
    wf = WorkflowDefinition.model_validate(raw)
    event_log = SQLiteEventLog(db)

    policies = {}
    for name, agent_cfg in wf.agents.items():
        policies[name] = agent_cfg.to_capability_policy(name)

    calculator = SafetyScoreCalculator(event_log)
    report = calculator.calculate(wf, policies)

    grade_colors = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}
    color = grade_colors.get(report.grade, "white")

    click.echo(f"Workflow: {wf.name}")
    click.echo(f"Overall:  {click.style(f'Grade {report.grade}', fg=color, bold=True)} "
               f"({report.overall_score:.3f}/1.000)")
    click.echo(f"Minimum:  {'PASS' if report.meets_minimum else 'FAIL'} "
               f"(threshold: {report.minimum_threshold})")
    click.echo()

    for dim in report.dimensions:
        bar_len = int(dim.score * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        click.echo(f"  {dim.name:25s} {bar} {dim.score:.3f} (w={dim.weight})")
        click.echo(f"  {'':25s} {dim.rationale}")


@cli.command()
@click.argument("yaml_file", type=click.Path(exists=True))
def audit(yaml_file: str) -> None:
    """Audit agent capability policies for security risks."""
    from agentos.security.audit import AgentAuditor

    raw = yaml.safe_load(Path(yaml_file).read_text())
    wf = WorkflowDefinition.model_validate(raw)
    auditor = AgentAuditor()

    click.echo(f"Workflow: {wf.name}")
    click.echo(f"Agents:   {len(wf.agents)}")
    click.echo()

    total_findings = 0
    for name, agent_cfg in wf.agents.items():
        policy = agent_cfg.to_capability_policy(name)
        report = auditor.audit_policy(name, policy)
        total_findings += report.finding_count

        risk_colors = {"low": "green", "medium": "yellow", "high": "red", "critical": "red"}
        color = risk_colors.get(report.overall_risk.value, "white")
        click.echo(f"  {name:20s} risk={click.style(report.overall_risk.value, fg=color)} "
                   f"score={report.score:.0f}/100 findings={report.finding_count}")

        for finding in report.findings:
            fcolor = risk_colors.get(finding.risk.value, "white")
            click.echo(f"    [{click.style(finding.risk.value, fg=fcolor)}] "
                       f"{finding.category}: {finding.description}")
            click.echo(f"      → {finding.recommendation}")

    click.echo()
    if total_findings == 0:
        click.echo(click.style("All agents pass audit.", fg="green"))
    else:
        click.echo(f"Total findings: {total_findings}")


@cli.command(name="compliance-report")
@click.argument("workflow_id")
@click.option("--db", required=True, help="SQLite database path with workflow events")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "html"]),
              help="Output format")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
def compliance_report(workflow_id: str, db: str, fmt: str, output: str | None) -> None:
    """Generate a compliance/audit report for a completed workflow."""
    from agentos.security.compliance import ComplianceReportGenerator

    event_log = SQLiteEventLog(db)
    generator = ComplianceReportGenerator(event_log)
    report = generator.generate(workflow_id)

    if fmt == "html":
        content = report.to_html()
    else:
        content = report.to_json()

    if output:
        Path(output).write_text(content)
        click.echo(f"Report written to: {output}")
    else:
        click.echo(content)


@cli.group()
def finetune() -> None:
    """Fine-tuning data management."""


@finetune.command(name="export")
@click.option("--db", required=True, help="SQLite database path with workflow history")
@click.option("--format", "fmt", default="openai", type=click.Choice(["openai", "anthropic"]),
              help="Export format")
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
def finetune_export(db: str, fmt: str, output: str | None) -> None:
    """Export fine-tuning training data from past workflow runs."""
    try:
        from agentos.intelligence.finetune import ExportConfig, ExportFormat, FineTuneExporter
    except ImportError:
        click.echo(click.style(
            "Intelligence dependencies not installed.\n"
            "Install with: pip install agentos[intelligence]",
            fg="red",
        ))
        raise SystemExit(1)
    from agentos.schemas.events import EventType

    event_log = SQLiteEventLog(db)
    exporter = FineTuneExporter()

    # Extract records from event log
    output_events = event_log.query(event_type=EventType.TASK_OUTPUT_PRODUCED)

    from agentos.intelligence.finetune import TaskRecord  # noqa: E811

    for event in output_events:
        payload = event.payload
        task_output = payload.get("output", {})
        exporter.add_record(TaskRecord(
            task_id=payload.get("task_id", ""),
            workflow_id=event.workflow_id,
            system_prompt="",
            user_input=payload.get("task_id", ""),
            assistant_output=task_output.get("summary", ""),
            quality_score=0.8 if task_output.get("status") == "succeeded" else 0.3,
            approved=task_output.get("status") == "succeeded",
        ))

    export_format = ExportFormat.JSONL_OPENAI if fmt == "openai" else ExportFormat.JSONL_ANTHROPIC
    config = ExportConfig(format=export_format)
    result = exporter.export(config)

    click.echo(f"Candidates: {result.total_candidates}")
    click.echo(f"Exported:   {result.exported}")
    click.echo(f"Filtered:   quality={result.filtered_quality} approval={result.filtered_approval}")

    if result.lines:
        content = "\n".join(result.lines)
        if output:
            Path(output).write_text(content)
            click.echo(f"Written to: {output}")
        else:
            click.echo()
            click.echo(content)


cli.add_command(finetune)


@cli.command()
@click.option("--db", required=True, help="SQLite database path with workflow history")
def suggest(db: str) -> None:
    """Show workflow optimization recommendations based on past runs."""
    try:
        from agentos.intelligence.learning import ConfigRecommender, PatternDetector, WorkflowRecord
    except ImportError:
        click.echo(click.style(
            "Intelligence dependencies not installed.\n"
            "Install with: pip install agentos[intelligence]",
            fg="red",
        ))
        raise SystemExit(1)

    event_log = SQLiteEventLog(db)
    detector = PatternDetector()

    # Build records from completed workflows
    completed_events = event_log.query(event_type=EventType.WORKFLOW_COMPLETED)
    records = []
    for event in completed_events:
        records.append(WorkflowRecord(
            workflow_id=event.workflow_id,
            workflow_name=event.payload.get("workflow_name", ""),
            team_composition=[],
            total_cost_usd=0.0,
            total_duration_seconds=0.0,
            quality_score=0.8 if event.payload.get("status") == "succeeded" else 0.3,
            success=event.payload.get("status") == "succeeded",
        ))
        detector.add_record(records[-1])

    if not records:
        click.echo("No workflow history found.")
        return

    patterns = detector.detect_patterns()
    recommender = ConfigRecommender()
    recommendations = recommender.recommend(patterns, records)

    click.echo(f"Analyzed {len(records)} past workflow runs.")
    click.echo()

    if patterns:
        click.echo("Detected patterns:")
        for p in patterns:
            click.echo(f"  [{p.confidence:.0%}] {p.description}")
            if p.recommendation:
                click.echo(f"    → {p.recommendation}")
        click.echo()

    if recommendations:
        click.echo("Recommendations:")
        for r in recommendations:
            click.echo(f"  [{r.category}] {r.description}")
            click.echo(f"    Expected: {r.expected_improvement}")
    else:
        click.echo("No recommendations yet (need more data).")


@cli.group()
def memory() -> None:
    """Cross-run memory management."""


@memory.command(name="query")
@click.option("--db", required=True, help="SQLite database path for memory store")
@click.option("--type", "mem_type", default=None, help="Filter by memory type")
@click.option("--limit", default=10, help="Max results")
def memory_query(db: str, mem_type: str | None, limit: int) -> None:
    """Query cross-run memories."""
    try:
        from agentos.kernel.memory_store import SQLiteMemoryStore
        from agentos.schemas.memory import MemoryConfig, MemoryQuery, MemoryType
    except ImportError:
        click.echo(click.style(
            "Memory store dependencies not available.\n"
            "Ensure the memory module is installed.",
            fg="red",
        ))
        raise SystemExit(1)

    store = SQLiteMemoryStore(MemoryConfig(enabled=True), db)

    query_type = None
    if mem_type:
        try:
            query_type = MemoryType(mem_type)
        except ValueError:
            click.echo(f"Unknown memory type: {mem_type}")
            click.echo(f"Valid types: {', '.join(t.value for t in MemoryType)}")
            return

    results = store.query(MemoryQuery(memory_type=query_type, limit=limit))

    click.echo(f"Found {len(results)} memories (total: {store.count()})")
    click.echo()

    for entry in results:
        click.echo(f"  [{entry.memory_type.value}] {entry.content[:80]}")
        click.echo(f"    confidence={entry.confidence:.2f} task={entry.task_id} workflow={entry.workflow_id[:12]}")


cli.add_command(memory)


@cli.group()
def knowledge() -> None:
    """Knowledge graph management."""


@knowledge.command(name="query")
@click.option("--db", required=True, help="SQLite database path for knowledge graph")
@click.option("--type", "entity_type", default=None, help="Filter by entity type")
@click.option("--name", "name_pattern", default=None, help="Search by name pattern")
def knowledge_query(db: str, entity_type: str | None, name_pattern: str | None) -> None:
    """Query knowledge graph entities."""
    try:
        from agentos.intelligence.knowledge_graph import SQLiteKnowledgeGraph
    except ImportError:
        click.echo(click.style(
            "Intelligence dependencies not installed.\n"
            "Install with: pip install agentos[intelligence]",
            fg="red",
        ))
        raise SystemExit(1)

    kg = SQLiteKnowledgeGraph(db)
    entities = kg.search_entities(entity_type=entity_type, name_pattern=name_pattern)

    click.echo(f"Entities: {kg.entity_count()} | Relationships: {kg.relationship_count()}")
    click.echo()

    for entity in entities[:20]:
        click.echo(f"  [{entity.entity_type}] {entity.name}")
        if entity.properties:
            click.echo(f"    props: {entity.properties}")

        observations = kg.get_observations(entity.entity_id)
        for obs in observations[:3]:
            click.echo(f"    obs: {obs.content[:60]} (conf={obs.confidence:.2f})")


cli.add_command(knowledge)


@cli.group()
def marketplace() -> None:
    """Workflow template marketplace."""


@marketplace.command(name="list")
@click.option("--db", default=":memory:", help="Marketplace database path")
@click.option("--category", default=None, help="Filter by category")
@click.option("--verified", is_flag=True, help="Show only verified templates")
def marketplace_list(db: str, category: str | None, verified: bool) -> None:
    """List marketplace workflow templates."""
    try:
        from agentos.marketplace.registry import MarketplaceRegistry
    except ImportError:
        click.echo(click.style(
            "Marketplace dependencies not installed.\n"
            "Install with: pip install agentos[marketplace]",
            fg="red",
        ))
        raise SystemExit(1)

    registry = MarketplaceRegistry(db)
    templates = registry.list_templates(category=category, verified_only=verified)

    if not templates:
        click.echo("No templates found.")
        return

    for t in templates:
        verified_badge = " ✓" if t.verified else ""
        click.echo(f"  {t.template_id[:8]}  {t.name}{verified_badge}")
        click.echo(f"    {t.category} | {t.downloads} downloads | by {t.author or 'anonymous'}")
        if t.description:
            click.echo(f"    {t.description[:80]}")


@marketplace.command(name="publish")
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--db", required=True, help="Marketplace database path")
@click.option("--name", required=True, help="Template name")
@click.option("--description", default="", help="Template description")
@click.option("--author", default="", help="Author name")
@click.option("--category", default="general", help="Category")
def marketplace_publish(yaml_file: str, db: str, name: str, description: str, author: str, category: str) -> None:
    """Publish a workflow YAML as a marketplace template."""
    try:
        from agentos.marketplace.registry import MarketplaceRegistry
    except ImportError:
        click.echo(click.style(
            "Marketplace dependencies not installed.\n"
            "Install with: pip install agentos[marketplace]",
            fg="red",
        ))
        raise SystemExit(1)

    workflow_yaml = Path(yaml_file).read_text()
    registry = MarketplaceRegistry(db)
    template = registry.publish(
        name=name, workflow_yaml=workflow_yaml,
        description=description, author=author, category=category,
    )
    click.echo(f"Published template: {template.template_id}")
    click.echo(f"  Name: {template.name}")


@marketplace.command(name="import")
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--db", required=True, help="Marketplace database path")
def marketplace_import(json_file: str, db: str) -> None:
    """Import a workflow template from JSON."""
    try:
        from agentos.marketplace.registry import MarketplaceRegistry
    except ImportError:
        click.echo(click.style(
            "Marketplace dependencies not installed.\n"
            "Install with: pip install agentos[marketplace]",
            fg="red",
        ))
        raise SystemExit(1)

    json_data = Path(json_file).read_text()
    registry = MarketplaceRegistry(db)
    template = registry.import_template(json_data)
    click.echo(f"Imported template: {template.template_id}")
    click.echo(f"  Name: {template.name}")


cli.add_command(marketplace)


@cli.group()
def benchmark() -> None:
    """Benchmark workflows across backends."""


@benchmark.command(name="run")
@click.argument("yaml_file", type=click.Path(exists=True))
@click.option("--backends", default="tier1-claude,tier1-openai", help="Comma-separated backend names")
def benchmark_run(yaml_file: str, backends: str) -> None:
    """Benchmark a workflow across multiple backends (framework only)."""
    from agentos.intelligence.benchmark import BenchmarkRunner

    raw = yaml.safe_load(Path(yaml_file).read_text())
    wf = WorkflowDefinition.model_validate(raw)

    backend_list = [b.strip() for b in backends.split(",")]
    runner = BenchmarkRunner()
    run = runner.create_run(wf.name, backend_list)

    click.echo(f"Benchmark run created: {run.run_id[:12]}")
    click.echo(f"  Workflow: {wf.name}")
    click.echo(f"  Backends: {', '.join(backend_list)}")
    click.echo()
    click.echo("Note: Actual execution requires live adapters per backend.")
    click.echo("Use the benchmark API programmatically for full runs.")

    # Record stub results for demo
    for backend in backend_list:
        runner.record_result(
            run_id=run.run_id,
            backend=backend,
            duration_seconds=0.0,
            total_tokens=0,
            estimated_cost_usd=0.0,
            output_summary=f"Stub result for {backend}",
        )

    report = runner.generate_report(run.run_id)
    click.echo()
    click.echo(f"  Fastest:  {report.fastest_backend or 'N/A'}")
    click.echo(f"  Cheapest: {report.cheapest_backend or 'N/A'}")
    click.echo(f"  Best:     {report.best_quality_backend or 'N/A'}")


cli.add_command(benchmark)


@cli.command()
@click.argument("yaml_file", default="examples/linear_research.yaml", type=click.Path(exists=True))
@click.option("--db", default=":memory:", help="SQLite database path (default: in-memory)")
@click.option("--tier", default=0, type=click.IntRange(0, 2),
              help="Adapter tier: 0=stub (default), 2=Tier 2 Claude Code (mocked)")
@click.option("--pause-at-gates", is_flag=True, default=False,
              help="Pause at gates instead of auto-approving (requires --db)")
def demo(yaml_file: str, db: str, tier: int, pause_at_gates: bool) -> None:
    """Run a workflow with stub or adapter-based executors (no real LLM calls).

    Loads a workflow YAML, validates the DAG, runs it with simulated agents,
    enforces budgets, and prints a summary of the full event log.

    Use --tier 2 to exercise the Tier 2 Claude Code adapter path (with a
    mocked subprocess that simulates Claude Code's JSON output).

    Use --pause-at-gates to stop at gates for manual resolution via
    `agentos gate approve <gate-id> --db <path>`.
    """
    if pause_at_gates and db == ":memory:":
        click.echo(click.style("Error: --pause-at-gates requires --db to persist state.", fg="red"))
        raise SystemExit(1)
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

    tier_label = {0: "stub", 2: "Tier 2 (Claude Code, mocked)"}
    click.echo(f"  Workspace: {ws_root}")
    click.echo(f"  Executor:  {tier_label.get(tier, f'Tier {tier}')}")
    click.echo()

    # --- Build Tier 2 adapters if requested ---
    tier2_adapters: dict[str, object] = {}
    tier2_mock_sub = None
    if tier == 2:
        from agentos.adapters.tier2_claude_code import ClaudeCodeAdapter

        def _mock_subprocess(cmd, *, cwd=None, capture_output=True, text=True, timeout=None, env=None):
            """Simulates Claude Code: writes manifest.json, returns usage JSON."""
            if cwd:
                manifest = {
                    "summary": f"Completed work in {Path(cwd).name}.",
                    "findings": [{"finding": "Demo finding", "confidence": "medium"}],
                    "open_questions": [],
                }
                (Path(cwd) / "manifest.json").write_text(json.dumps(manifest))

            class _Result:
                returncode = 0
                stdout = json.dumps({
                    "usage": {"input_tokens": 250, "output_tokens": 250},
                    "cost_usd": 0.01,
                })
                stderr = ""

            return _Result()

        tier2_mock_sub = _mock_subprocess
        for agent_name in workflow.agents:
            tier2_adapters[agent_name] = ClaudeCodeAdapter(
                budget_mgr, agent_name, run_subprocess=tier2_mock_sub,
            )

    # --- Task executor ---
    def task_executor(task_name: str, config: TaskConfig, predecessors=None):
        predecessors = predecessors or []

        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            click.echo(click.style(f"  GATE  {task_name}", fg="yellow") +
                       f" — {config.prompt or 'Awaiting approval'}")

            if pause_at_gates:
                click.echo(click.style(f"        PAUSED — resolve with:", fg="yellow"))
                click.echo(click.style(f"        agentos gate approve {gate_id} --db {db}", fg="yellow"))
                return TaskStatus.WAITING, None

            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="demo")
            click.echo(click.style("        auto-approved (demo mode)", fg="yellow"))
            time.sleep(0.2)
            output = TaskOutput(
                task_id=task_name, agent_id="gate",
                status=TaskStatus.SUCCEEDED,
                summary=f"Gate approved: {config.prompt or task_name}",
            )
            return TaskStatus.SUCCEEDED, output

        if config.type == "consultation":
            agent_id = config.consult_agent or "unassigned"
            click.echo(click.style(f"  ASK   {task_name}", fg="magenta") +
                       f" (agent: {agent_id})")
            question = config.consult_question or config.description
            if question:
                desc = question.strip()
                if len(desc) > 100:
                    desc = desc[:97] + "..."
                click.echo(f"        {desc}")

            time.sleep(0.3)
            budget_mgr.apply(agent_id, BudgetDelta(
                tokens=300, api_calls=1, time_seconds=0.3, cost_usd=0.005,
            ))

            output = TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.SUCCEEDED,
                summary=f"Consultation: {agent_id} responded to query",
                key_findings=[Finding(
                    finding=f"Response from {agent_id}: clarification provided",
                    confidence=Confidence.MEDIUM,
                )],
            )
            click.echo(click.style(f"  DONE  {task_name}", fg="green") +
                       f" → consultation response from {agent_id}")
            return TaskStatus.SUCCEEDED, output

        agent_id = config.agent or "unassigned"

        # Show predecessor handoffs
        if predecessors:
            ctx_ids = [c.task_id for c in predecessors]
            click.echo(click.style(f"  RECV  {task_name}", fg="cyan") +
                       f" ← context from: {', '.join(ctx_ids)}")

        if tier == 2 and agent_id in tier2_adapters:
            status = _run_tier2_task(
                task_name, config, agent_id, tier2_adapters[agent_id],
                workflow, workspace, ws_root,
            )
            output = TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=status, summary=f"Tier 2: {task_name}",
            )
            return status, output

        # Default: stub executor (tier 0)
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

        output = TaskOutput(
            task_id=task_name, agent_id=agent_id,
            status=TaskStatus.SUCCEEDED,
            summary=f"All checks passed. Stub completed {task_name} successfully.",
            key_findings=[Finding(
                finding=f"Demo finding from {task_name}",
                confidence=Confidence.MEDIUM,
            )],
        )
        return TaskStatus.SUCCEEDED, output

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

    color_map = {"succeeded": "green", "failed": "red", "paused": "yellow"}
    status_color = color_map.get(result.status, "white")
    click.echo(f"  Workflow: {click.style(result.status.upper(), fg=status_color, bold=True)}")
    click.echo(f"  Completed: {len(result.completed_tasks)}")
    click.echo(f"  Failed:    {len(result.failed_tasks)}")
    click.echo(f"  Skipped:   {len(result.skipped_tasks)}")
    if result.waiting_tasks:
        click.echo(f"  Waiting:   {len(result.waiting_tasks)}")

    # --- Structured handoffs summary ---
    if result.task_outputs:
        click.echo()
        click.echo(click.style(" Structured Handoffs", fg="cyan", bold=True))
        click.echo(click.style("-" * 40, fg="cyan"))
        for task_name, output in result.task_outputs.items():
            findings_count = len(output.key_findings)
            questions_count = len(output.open_questions)
            click.echo(f"  {task_name:20s} → {output.summary[:50]}")
            if findings_count:
                click.echo(f"  {'':20s}   {findings_count} finding(s)")
            if questions_count:
                click.echo(f"  {'':20s}   {questions_count} open question(s)")

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

    # --- V1.5 event counts ---
    branch_count = len(event_log.query(workflow_id=workflow_id, event_type=EventType.BRANCH_EVALUATED))
    retry_count = len(event_log.query(workflow_id=workflow_id, event_type=EventType.TASK_RETRIED))
    message_count = len(event_log.query(workflow_id=workflow_id, event_type=EventType.MESSAGE_SENT))
    if branch_count or retry_count or message_count:
        click.echo()
        click.echo(click.style(" V1.5 Features", fg="cyan", bold=True))
        click.echo(click.style("-" * 40, fg="cyan"))
        if branch_count:
            click.echo(f"  Branches:     {branch_count}")
        if retry_count:
            click.echo(f"  Retries:      {retry_count}")
        if message_count:
            click.echo(f"  Messages:     {message_count}")

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
    if result.status == "paused":
        pending = gate_mgr.list_pending()
        if pending:
            click.echo()
            click.echo(click.style(" Pending Gates — resolve to continue", fg="yellow", bold=True))
            click.echo(click.style("-" * 40, fg="yellow"))
            for g in pending:
                click.echo(f"  {g.gate_id}  {g.prompt}")
                click.echo(f"    agentos gate approve {g.gate_id} --db {db}")
            click.echo()
            click.echo(f"  Then resume:")
            click.echo(f"    agentos workflow resume {yaml_file} {workflow_id} --db {db}")

    if db != ":memory:":
        click.echo(f"  Persisted to: {db}")
    click.echo()


def _run_tier2_task(
    task_name: str,
    config: TaskConfig,
    agent_id: str,
    adapter: object,
    workflow: WorkflowDefinition,
    workspace: Workspace,
    ws_root: Path,
) -> TaskStatus:
    """Execute a task via the Tier 2 Claude Code adapter."""
    click.echo(click.style(f"  T2    {task_name}", fg="magenta") +
               f" (agent: {agent_id}, adapter: Claude Code)")
    if config.description:
        desc = config.description.strip()
        if len(desc) > 100:
            desc = desc[:97] + "..."
        click.echo(f"        {desc}")

    task_ws = ws_root / task_name
    task_ws.mkdir(exist_ok=True)

    agent_cfg = workflow.agents.get(agent_id)
    role = agent_cfg.role if agent_cfg else ""

    output = asyncio.run(adapter.execute_task(  # type: ignore[attr-defined]
        task_description=config.description or task_name,
        role=role,
        workspace=task_ws,
        predecessor_context=[],
        allowed_tools=["Read", "Write", "Bash"],
    ))

    if output.status == TaskStatus.SUCCEEDED:
        click.echo(click.style(f"  DONE  {task_name}", fg="green") +
                   f" → manifest: {output.summary}")
        if output.metrics:
            click.echo(f"        tokens={output.metrics.tokens_consumed}, "
                       f"cost=${output.metrics.estimated_cost_usd:.3f}, "
                       f"calls={output.metrics.api_calls_made}")
        # Track the manifest in workspace
        manifest_path = task_ws / "manifest.json"
        if manifest_path.exists():
            workspace.write_file(
                f"{task_name}/manifest.json", manifest_path.read_text(),
                agent_id=agent_id, task_id=task_name,
            )
    else:
        click.echo(click.style(f"  FAIL  {task_name}", fg="red") +
                   f" — {output.summary}")

    return output.status


def _event_color(event_type: str) -> str:
    """Pick a terminal color based on event type prefix."""
    if event_type.startswith("workflow"):
        return "cyan"
    if event_type == "task.retried":
        return "yellow"
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
    if event_type.startswith("branch"):
        return "cyan"
    if event_type.startswith("revision"):
        return "yellow"
    if event_type.startswith("message"):
        return "magenta"
    return "white"


def _event_detail(event: object) -> str:
    """Extract a short detail string from an event's payload."""
    payload = event.payload  # type: ignore[attr-defined]
    etype = event.event_type.value  # type: ignore[attr-defined]

    # V1.5 event types
    if etype == "branch.evaluated":
        target = payload.get("target", "")
        label = "activated" if payload.get("result") else "skipped"
        return f"{payload.get('task_id', '')} → {target} ({label})"

    if etype == "task.retried":
        return f"{payload.get('task_id', '')} iteration {payload.get('iteration', '?')}"

    if etype == "revision.feedback":
        feedback = payload.get("feedback", "")
        if len(feedback) > 40:
            feedback = feedback[:37] + "..."
        return f"{payload.get('task_id', '')} \"{feedback}\""

    if etype in ("message.sent", "message.received"):
        agent = payload.get("consult_agent", "")
        question = payload.get("question", "")
        if question:
            if len(question) > 40:
                question = question[:37] + "..."
            return f"{agent} \"{question}\""
        return f"{payload.get('task_id', '')} → {agent}"

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
