"""CLI workflow commands — run and verify workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

import click
import yaml

logger = logging.getLogger(__name__)

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor, ExecutionContext
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskMetrics, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig
from agentos.schemas.tool_mapping import TIER2_TOOL_MAP, TIER2_TOOL_EXPANSIONS
from agentos.validation.workflow_verifier import WorkflowVerifier


def _build_execution_context(
    wf: WorkflowDefinition,
    event_log: SQLiteEventLog,
    seq: SeqCounter,
    workflow_id: str,
    db: str,
    memory_db: str | None,
) -> ExecutionContext:
    """Instantiate V2+ modules based on workflow config and CLI flags."""
    ctx = ExecutionContext()

    # Channel Router
    if wf.channels:
        from agentos.kernel.channel_router import ChannelRouter

        ctx.channel_router = ChannelRouter(wf.channels, event_log, seq, workflow_id)

    # Memory Store
    if wf.memory.enabled and memory_db:
        from agentos.kernel.memory_store import SQLiteMemoryStore

        ctx.memory_store = SQLiteMemoryStore(wf.memory, memory_db)

    # Knowledge Graph (only with persistent DB)
    if db != ":memory:":
        try:
            from agentos.intelligence.knowledge_graph import SQLiteKnowledgeGraph

            ctx.knowledge_graph = SQLiteKnowledgeGraph(db)
        except Exception:
            logger.debug("Knowledge graph initialization skipped", exc_info=True)

    # Specialization Tracker
    try:
        from agentos.intelligence.specialization import SpecializationTracker

        ctx.specialization_tracker = SpecializationTracker()
    except Exception:
        logger.debug("Specialization tracker initialization skipped", exc_info=True)

    # Fine-Tune Exporter
    try:
        from agentos.intelligence.finetune import FineTuneExporter

        ctx.finetune_exporter = FineTuneExporter()
    except Exception:
        logger.debug("Fine-tune exporter initialization skipped", exc_info=True)

    # Team Composer
    if wf.spawn_policy is not None:
        from agentos.kernel.team_composer import TeamComposer

        ctx.team_composer = TeamComposer(wf.spawn_policy, wf.archetypes)

    return ctx


def _run_pre_run_analysis(
    wf: WorkflowDefinition,
    event_log: SQLiteEventLog,
) -> None:
    """Run pre-execution safety score and agent audit."""
    # Safety Score
    try:
        from agentos.security.safety_score import SafetyScoreCalculator

        policies = {}
        for name, agent_cfg in wf.agents.items():
            policies[name] = agent_cfg.to_capability_policy(name)

        calculator = SafetyScoreCalculator(event_log)
        report = calculator.calculate(wf, policies)
        grade_colors = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}
        color = grade_colors.get(report.grade, "white")
        click.echo(f"  Safety:    {click.style(f'Grade {report.grade}', fg=color)} "
                   f"({report.overall_score:.2f}/1.00)")
    except Exception:
        logger.debug("Safety score calculation skipped", exc_info=True)

    # Agent Audit
    try:
        from agentos.security.audit import AgentAuditor

        auditor = AgentAuditor()
        total_findings = 0
        for name, agent_cfg in wf.agents.items():
            policy = agent_cfg.to_capability_policy(name)
            audit_report = auditor.audit_policy(name, policy)
            total_findings += audit_report.finding_count
        if total_findings > 0:
            click.echo(f"  Audit:     {click.style(f'{total_findings} finding(s)', fg='yellow')}")
        else:
            click.echo(f"  Audit:     {click.style('clean', fg='green')}")
    except Exception:
        logger.debug("Agent audit skipped", exc_info=True)


def _run_post_run_intelligence(
    wf: WorkflowDefinition,
    result: object,
    budget_mgr: BudgetManager,
    ctx: ExecutionContext,
    memory_db: str | None,
) -> None:
    """Run post-execution intelligence hooks (patterns, recommendations, memory decay)."""
    # Pattern Detection
    try:
        from agentos.intelligence.learning import ConfigRecommender, PatternDetector, WorkflowRecord

        detector = PatternDetector()
        total = budget_mgr.total_usage
        record = WorkflowRecord(
            workflow_id=result.workflow_id,
            workflow_name=wf.name,
            team_composition=list(wf.agents.keys()),
            total_cost_usd=total.cost_usd,
            total_duration_seconds=total.time_elapsed_seconds,
            quality_score=0.8 if result.status == "succeeded" else 0.3,
            success=result.status == "succeeded",
            token_usage=total.tokens_used,
        )
        detector.add_record(record)
        patterns = detector.detect_patterns()

        if patterns:
            recommender = ConfigRecommender()
            recommendations = recommender.recommend(patterns, [record])
            if recommendations:
                click.echo()
                click.echo(click.style("  Recommendations:", dim=True))
                for rec in recommendations[:3]:
                    click.echo(f"    {rec.category}: {rec.description}")
    except Exception:
        logger.debug("Pattern detection skipped", exc_info=True)

    # Memory decay
    if memory_db and ctx.memory_store is not None:
        try:
            pruned = ctx.memory_store.decay()
            if pruned > 0:
                click.echo(f"  Memory:    pruned {pruned} low-confidence entries")
        except Exception:
            logger.debug("Memory decay skipped", exc_info=True)


def _build_live_executor(
    wf: WorkflowDefinition,
    budget_mgr: BudgetManager,
    gate_mgr: GateManager,
    ws_root: "Path",
    event_log: SQLiteEventLog,
    seq: SeqCounter,
    workflow_id: str,
    *,
    interactive: bool = False,
    execution_context: ExecutionContext | None = None,
):
    """Build a task executor that uses real adapters for live execution.

    Creates Tier1Adapter or ClaudeCodeAdapter per agent based on the
    ``adapter`` field in the workflow YAML.  Returns a callable matching
    the DAGExecutor's ``TaskExecutorFn`` signature.
    """
    ctx = execution_context
    from anthropic import Anthropic

    from agentos.adapters.tier1 import Tier1Adapter
    from agentos.adapters.tier2_claude_code import ClaudeCodeAdapter
    from agentos.schemas.agent import ClaudeCodeConfig

    # Check for required API key if any agents use tier1
    has_tier1 = any(a.adapter == "tier1" for a in wf.agents.values())
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if has_tier1 and not api_key:
        raise click.ClickException(
            "ANTHROPIC_API_KEY environment variable is required for Tier 1 agents. "
            "Set it with: export ANTHROPIC_API_KEY=sk-..."
        )

    # Sandbox Manager
    sandbox_mgr = None
    has_sandbox = any(a.sandbox is not None for a in wf.agents.values())
    if has_sandbox:
        try:
            from agentos.security.sandbox import SandboxManager

            sandbox_mgr = SandboxManager(event_log, seq, workflow_id)
        except Exception:
            logger.debug("Sandbox manager initialization skipped", exc_info=True)

    # Post-Hoc Verifier
    post_hoc_verifier = None
    try:
        from agentos.security.post_hoc_verifier import PostHocVerifier

        post_hoc_verifier = PostHocVerifier(event_log, seq, workflow_id)
    except Exception:
        logger.debug("Post-hoc verifier initialization skipped", exc_info=True)

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

            # Create sandbox handle if configured
            sandbox_handle = None
            if sandbox_mgr is not None and agent_cfg.sandbox is not None:
                workspace_path = ws_root / "shared"
                workspace_path.mkdir(parents=True, exist_ok=True)
                try:
                    sandbox_handle = sandbox_mgr.create(name, agent_cfg.sandbox, workspace_path)
                except Exception:
                    logger.debug("Sandbox creation skipped for agent %s", name, exc_info=True)

            adapters[name] = ClaudeCodeAdapter(
                budget_manager=budget_mgr,
                agent_id=name,
                timeout=timeout,
                log_fn=_make_log_fn(name),
                sandbox_handle=sandbox_handle,
                event_log=event_log,
                seq=seq,
                workflow_id=workflow_id,
                claude_code_config=agent_cfg.claude_code,
            )
        elif agent_cfg.adapter == "tier2_aider":
            from agentos.adapters.tier2_aider import AiderAdapter

            timeout = int(agent_cfg.budget.max_time_seconds
                          or wf.budget.max_time_seconds
                          or 300)

            def _make_aider_log_fn(agent_name: str):
                def log_fn(msg: str) -> None:
                    ts = datetime.now().strftime("%H:%M:%S")
                    click.echo(f"  [{ts}]        {click.style(agent_name, fg='cyan')} | {msg}")
                return log_fn

            adapters[name] = AiderAdapter(
                budget_manager=budget_mgr,
                agent_id=name,
                model=agent_cfg.model,
                timeout=timeout,
                log_fn=_make_aider_log_fn(name),
            )
        elif agent_cfg.adapter == "manager":
            pass  # handled in second pass below
        else:
            raise click.ClickException(
                f"Unknown adapter type: {agent_cfg.adapter!r} for agent {name!r}"
            )

    # Second pass: create manager adapters that reference other adapters
    for name, agent_cfg in wf.agents.items():
        if agent_cfg.adapter != "manager":
            continue
        try:
            from agentos.adapters.manager_adapter import ManagerAgentAdapter

            team_name = agent_cfg.team
            team_cfg = wf.teams.get(team_name) if team_name else None

            if team_cfg is not None:
                # Team-based manager: create a CC instance for the manager itself,
                # scoped member adapters, and wire in team context.
                timeout = int(agent_cfg.budget.max_time_seconds
                              or wf.budget.max_time_seconds
                              or 300)

                def _make_mgr_log_fn(agent_name: str):
                    def log_fn(msg: str) -> None:
                        ts = datetime.now().strftime("%H:%M:%S")
                        click.echo(f"  [{ts}]        {click.style(agent_name, fg='cyan')} | {msg}")
                    return log_fn

                mgr_cc = ClaudeCodeAdapter(
                    budget_manager=budget_mgr,
                    agent_id=f"{name}_cc",
                    timeout=timeout,
                    max_turns=15,
                    log_fn=_make_mgr_log_fn(name),
                    event_log=event_log,
                    seq=seq,
                    workflow_id=workflow_id,
                    claude_code_config=agent_cfg.claude_code,
                )

                member_adapters = {
                    m: adapters[m] for m in team_cfg.members if m in adapters
                }
                member_roles = {
                    m: wf.agents[m].role for m in team_cfg.members if m in wf.agents
                }

                # Compute per-member expanded tool lists so members get
                # their own YAML-defined tools, not the manager's.
                member_tools: dict[str, list[str]] = {}
                for m in team_cfg.members:
                    if m in wf.agents:
                        m_tools = wf.agents[m].tools
                        m_mapped: set[str] = set()
                        for t in m_tools:
                            cc_name = TIER2_TOOL_MAP.get(t, t)
                            for expanded in TIER2_TOOL_EXPANSIONS.get(cc_name, [cc_name]):
                                m_mapped.add(expanded)
                        member_tools[m] = sorted(m_mapped) if m_mapped else []

                adapters[name] = ManagerAgentAdapter(
                    budget_manager=budget_mgr,
                    agent_id=name,
                    manager_adapter=mgr_cc,
                    team_name=team_name,
                    team_description=team_cfg.description,
                    member_adapters=member_adapters,
                    member_roles=member_roles,
                    member_tools=member_tools,
                    channel_router=ctx.channel_router if ctx is not None else None,
                    team_channel=team_cfg.channel or f"team_{team_name}",
                    gate_manager=gate_mgr,
                    human_input_enabled=team_cfg.human_input,
                    interactive=interactive,
                )
            else:
                # Legacy teamless manager — backward compatible
                adapters[name] = ManagerAgentAdapter(
                    budget_manager=budget_mgr,
                    agent_id=name,
                    downstream_adapters=dict(adapters),
                    role=agent_cfg.role,
                )
        except Exception as exc:
            raise click.ClickException(
                f"Failed to create manager adapter for {name!r}: {exc}"
            )

    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _persist_output(task_name: str, config: TaskConfig, output: TaskOutput) -> None:
        """Write a TaskOutput as manifest.json to the task workspace.

        This ensures that on resume (--start-from + --reuse-workspace),
        every completed task — including gates and input gates — has a
        manifest that can be replayed with full context.
        """
        task_ws = ws_root / config.workspace / task_name
        task_ws.mkdir(parents=True, exist_ok=True)
        manifest = {
            "summary": output.summary or "",
            "findings": [
                {"finding": f.finding, "confidence": str(f.confidence), "sources": f.sources}
                for f in output.key_findings
            ],
            "open_questions": output.open_questions or [],
            "files_produced": [f.path for f in output.files_produced],
        }
        (task_ws / "manifest.json").write_text(json.dumps(manifest, indent=2))

    def task_executor(task_name: str, config: TaskConfig, predecessors=None):
        predecessors = predecessors or []

        if config.type == "approval_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
            prompt_text = config.prompt or "Approve this gate?"
            click.echo()
            click.echo(f"  [{_ts()}] {click.style('GATE', fg='yellow', bold=True)}  {task_name}")
            click.echo(f"           {prompt_text}")
            click.echo()

            # Build a gate output that forwards predecessor summaries so
            # downstream tasks receive the full context chain, not just "Approved".
            pred_summaries = "\n".join(
                f"[{p.task_id}] {p.summary}" for p in predecessors if p and p.summary
            )
            gate_summary = f"Gate approved. Predecessor context:\n{pred_summaries}" if pred_summaries else "Gate approved."
            gate_findings = []
            for p in predecessors:
                if p:
                    gate_findings.extend(p.key_findings)

            def _gate_output(summary: str) -> TaskOutput:
                return TaskOutput(
                    task_id=task_name, agent_id="gate",
                    status=TaskStatus.SUCCEEDED,
                    summary=summary,
                    key_findings=gate_findings,
                )

            if not interactive:
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
                click.echo(f"           Auto-approved (use --interactive for manual gates)")
                out = _gate_output(gate_summary)
                _persist_output(task_name, config, out)
                return TaskStatus.SUCCEEDED, out

            # Interactive gate: poll for resolution from dashboard or stdin
            import select
            import sys as _sys

            is_tty = _sys.stdin.isatty()
            if is_tty:
                click.echo(click.style("           [a]pprove / [r]eject / or type feedback to approve with guidance", fg="yellow"))

            while True:
                # Check if gate was resolved via dashboard API
                gate_state = gate_mgr.get_gate(gate_id)
                if gate_state and not gate_state.pending:
                    resolution = gate_state.resolution
                    feedback = gate_state.feedback or ""
                    click.echo(f"           {click.style('Resolved via dashboard', fg='cyan')}: {resolution}")
                    if resolution == GateResolution.APPROVED:
                        out = _gate_output(gate_summary)
                        _persist_output(task_name, config, out)
                        return TaskStatus.SUCCEEDED, out
                    else:
                        return TaskStatus.FAILED, TaskOutput(
                            task_id=task_name, agent_id="gate",
                            status=TaskStatus.FAILED,
                            summary=feedback or "Rejected via dashboard",
                        )

                # Check stdin if available (terminal mode)
                if is_tty:
                    ready, _, _ = select.select([_sys.stdin], [], [], 1.0)
                    if ready:
                        response = _sys.stdin.readline().rstrip("\n").strip()
                        if response == "" or response.lower() in ("a", "approve", "y", "yes"):
                            gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="human")
                            click.echo(f"           {click.style('Approved', fg='green')}")
                            out = _gate_output(gate_summary)
                            _persist_output(task_name, config, out)
                            return TaskStatus.SUCCEEDED, out
                        elif response.lower() in ("r", "reject", "n", "no"):
                            gate_mgr.resolve_gate(
                                gate_id, GateResolution.REJECTED,
                                reviewer="human", feedback="Rejected by user",
                            )
                            click.echo(f"           {click.style('Rejected', fg='red')}")
                            return TaskStatus.FAILED, TaskOutput(
                                task_id=task_name, agent_id="gate",
                                status=TaskStatus.FAILED,
                                summary="Rejected by user.",
                            )
                        else:
                            # Any other text = approve with feedback (guidance for downstream tasks)
                            gate_mgr.resolve_gate(
                                gate_id, GateResolution.APPROVED,
                                reviewer="human", feedback=response,
                            )
                            click.echo(f"           {click.style('Approved with feedback', fg='green')}: {response}")
                            out = TaskOutput(
                                task_id=task_name, agent_id="gate",
                                status=TaskStatus.SUCCEEDED,
                                summary=response,
                            )
                            _persist_output(task_name, config, out)
                            return TaskStatus.SUCCEEDED, out
                else:
                    # No TTY — just poll every second
                    time.sleep(1)

        if config.type == "input_gate":
            gate_id = gate_mgr.create_gate(task_name, GateType.INPUT, config.prompt)
            prompt_text = config.prompt or "Please provide input:"
            click.echo()
            click.echo(f"  [{_ts()}] {click.style('INPUT', fg='cyan', bold=True)} {task_name}")
            click.echo(f"           {prompt_text}")
            click.echo()

            if not interactive:
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
                click.echo(f"           Auto-approved with no input (use --interactive for manual input)")
                out = TaskOutput(
                    task_id=task_name, agent_id="input_gate",
                    status=TaskStatus.SUCCEEDED,
                    summary="No input provided (auto-mode).",
                )
                _persist_output(task_name, config, out)
                return TaskStatus.SUCCEEDED, out

            import select
            import sys as _sys

            is_tty = _sys.stdin.isatty()
            if is_tty:
                click.echo(click.style("           Enter your input (blank line + Enter to finish):", fg="cyan"))

            # Poll for dashboard resolution or TTY input
            lines: list[str] = []
            while True:
                # Check dashboard resolution
                gate_state = gate_mgr.get_gate(gate_id)
                if gate_state and not gate_state.pending:
                    resolution = gate_state.resolution
                    feedback = gate_state.feedback or ""
                    click.echo(f"           {click.style('Resolved via dashboard', fg='cyan')}: {resolution}")
                    if resolution == GateResolution.APPROVED:
                        out = TaskOutput(
                            task_id=task_name, agent_id="input_gate",
                            status=TaskStatus.SUCCEEDED,
                            summary=feedback or "Input provided via dashboard.",
                        )
                        _persist_output(task_name, config, out)
                        return TaskStatus.SUCCEEDED, out
                    else:
                        return TaskStatus.FAILED, TaskOutput(
                            task_id=task_name, agent_id="input_gate",
                            status=TaskStatus.FAILED,
                            summary=feedback or "Rejected via dashboard.",
                        )

                if is_tty:
                    ready, _, _ = select.select([_sys.stdin], [], [], 1.0)
                    if ready:
                        line = _sys.stdin.readline().rstrip("\n")
                        if line.strip() == "":
                            break
                        lines.append(line)
                        continue
                else:
                    time.sleep(1)
                    continue

            user_input = "\n".join(lines)
            if user_input.strip():
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="human")
                click.echo(f"           {click.style('Input received', fg='green')}")
                out = TaskOutput(
                    task_id=task_name, agent_id="input_gate",
                    status=TaskStatus.SUCCEEDED,
                    summary=user_input.strip(),
                )
                _persist_output(task_name, config, out)
                return TaskStatus.SUCCEEDED, out
            else:
                gate_mgr.resolve_gate(gate_id, GateResolution.REJECTED, reviewer="human",
                                      feedback="No input provided")
                click.echo(f"           {click.style('No input provided — skipping', fg='yellow')}")
                return TaskStatus.FAILED, TaskOutput(
                    task_id=task_name, agent_id="input_gate",
                    status=TaskStatus.FAILED,
                    summary="No input provided.",
                )

        # For consultation tasks, use consult_agent instead of agent
        if config.type == "consultation":
            agent_id = config.consult_agent or "unassigned"
        else:
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
        if config.type == "consultation":
            click.echo(f"  [{_ts()}] {click.style('ASK', fg='magenta', bold=True)}  {task_name} → {agent_id}")
            if config.consult_question:
                click.echo(f"           Q: {config.consult_question}")
        else:
            click.echo(f"  [{_ts()}] {click.style('START', fg='blue')} {task_name} ({agent_id} / {tier_label})")

        # Map tool names for Tier 2 and expand to include related CC tools
        allowed_tools = agent_cfg.tools if agent_cfg else []
        if agent_cfg and agent_cfg.adapter in ("tier2_claude_code", "manager"):
            mapped = set()
            for t in allowed_tools:
                cc_name = TIER2_TOOL_MAP.get(t, t)
                for expanded in TIER2_TOOL_EXPANSIONS.get(cc_name, [cc_name]):
                    mapped.add(expanded)
            allowed_tools = sorted(mapped) if mapped else []

        # Each task gets its own subdirectory within the workspace to avoid
        # manifest.json conflicts when parallel tasks share a workspace.
        workspace_path = ws_root / config.workspace / task_name
        workspace_path.mkdir(parents=True, exist_ok=True)

        # Pre-task snapshot for post-hoc verification
        pre_snapshot = None
        if post_hoc_verifier is not None and agent_cfg is not None and agent_cfg.capabilities:
            pre_snapshot = post_hoc_verifier.snapshot_directory(workspace_path)

        # Build task description (consultation tasks use the question)
        task_description = config.description
        if config.type == "consultation" and config.consult_question:
            task_description = (
                f"Consultation question: {config.consult_question}\n\n"
                f"{config.description}" if config.description else config.consult_question
            )

        try:
            output = asyncio.run(adapter.execute_task(
                task_description=task_description,
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

            # Post-hoc verification: file access
            if (
                post_hoc_verifier is not None
                and pre_snapshot is not None
                and agent_cfg is not None
                and agent_cfg.capabilities
            ):
                post_snapshot = post_hoc_verifier.snapshot_directory(workspace_path)
                policy = agent_cfg.to_capability_policy(agent_id)
                verification = post_hoc_verifier.verify(
                    agent_id, policy, workspace_path, pre_snapshot, post_snapshot,
                )
                if not verification.passed:
                    for v in verification.violations:
                        click.echo(f"           {click.style(f'VIOLATION: {v.detail}', fg='red')}")

            # Post-hoc verification: tool usage (streaming mode only)
            if hasattr(adapter, 'last_tools_used') and adapter.last_tools_used and allowed_tools:
                allowed_set = set(allowed_tools)
                # Always-disallowed tools that should never appear
                always_blocked = {"Agent", "TodoWrite", "ToolSearch"}
                unauthorized = (adapter.last_tools_used - allowed_set) - always_blocked
                if unauthorized:
                    click.echo(
                        f"           {click.style(f'TOOL VIOLATION: {agent_id} used unauthorized tools: {sorted(unauthorized)}', fg='red')}"
                    )
                    if post_hoc_verifier is not None:
                        from agentos.schemas.events import Event, EventType
                        post_hoc_verifier._event_log.append(
                            Event(
                                event_type=EventType.POLICY_VIOLATION_DETECTED,
                                workflow_id=post_hoc_verifier._workflow_id,
                                seq=post_hoc_verifier._seq.next(),
                                schema_version="0.2",
                                payload={
                                    "agent_id": agent_id,
                                    "violation_type": "tool",
                                    "detail": f"Used unauthorized tools: {sorted(unauthorized)}",
                                    "severity": "critical",
                                    "allowed_tools": sorted(allowed_set),
                                    "tools_used": sorted(adapter.last_tools_used),
                                },
                            )
                        )

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
@click.option("--memory-db", default=None, help="SQLite path for cross-run memory")
@click.option("--start-from", default=None,
              help="Skip tasks before this one, replaying completed tasks from workspace manifests.")
@click.option("--reuse-workspace", default=None,
              help="Reuse workspace from a previous run ID (e.g., run-a0fa10de).")
@click.option("--workflow-id", default=None,
              help="Use a specific workflow ID instead of generating one.")
@click.option("--param", "params", multiple=True, help="Workflow parameter as key=value")
def run(yaml_file: str, db: str, live: bool, interactive: bool,
        memory_db: str | None, start_from: str | None, reuse_workspace: str | None,
        workflow_id: str | None, params: tuple[str, ...]) -> None:
    """Run a workflow from a YAML file.

    By default uses stub executors for testing. Use --live for real
    adapters (requires ANTHROPIC_API_KEY for Tier 1 agents).
    Use --interactive for manual gate approval prompts.

    Use --start-from TASK --reuse-workspace RUN_ID to resume from a
    specific task, replaying earlier tasks from cached workspace manifests.
    """
    yaml_path = Path(yaml_file)
    raw = yaml.safe_load(yaml_path.read_text())
    wf = WorkflowDefinition.model_validate(raw)

    # Expand teams into channels + agent tags (compile-time resolution)
    if wf.teams:
        from agentos.kernel.team_expander import expand_teams

        wf = expand_teams(wf)

    # Parse --param values and substitute into task descriptions and agent roles
    param_values: dict[str, str] = {}
    for p in params:
        if "=" not in p:
            click.echo(click.style(f"Invalid param format: {p!r}. Use key=value.", fg="red"))
            raise SystemExit(1)
        key, value = p.split("=", 1)
        param_values[key] = value

    # Validate against declared parameters
    for name, param_def in wf.parameters.items():
        if name not in param_values:
            if param_def.required and param_def.default is None:
                click.echo(click.style(f"Missing required parameter: {name}", fg="red"))
                raise SystemExit(1)
            if param_def.default is not None:
                param_values[name] = param_def.default

    # Substitute ${param_name} in task descriptions
    if param_values:
        for task_name, task_config in wf.tasks.items():
            if task_config.description:
                for key, value in param_values.items():
                    task_config.description = task_config.description.replace(f"${{{key}}}", value)
        for agent_name, agent_config in wf.agents.items():
            if agent_config.role:
                for key, value in param_values.items():
                    agent_config.role = agent_config.role.replace(f"${{{key}}}", value)

    event_log = SQLiteEventLog(db)

    # Reuse workspace from a previous run if requested
    if reuse_workspace:
        workflow_id = reuse_workspace
        # Continue sequence numbering after existing events in this workflow
        max_seq = event_log.last_seq(workflow_id)
        seq = SeqCounter(start=max_seq + 1 if max_seq >= 0 else 0)
    else:
        workflow_id = workflow_id or f"run-{uuid.uuid4().hex[:8]}"
        seq = SeqCounter()

    # Compute set of tasks to skip (replay from manifests) when --start-from is used
    skip_tasks: set[str] = set()
    if start_from:
        if start_from not in wf.tasks:
            raise click.ClickException(f"Task {start_from!r} not found in workflow.")
        # BFS backwards: find all ancestors of start_from (everything that must
        # have completed before it). These get replayed, not re-executed.
        def _ancestors(task_name: str) -> set[str]:
            visited: set[str] = set()
            queue = list(wf.tasks[task_name].depends_on)
            while queue:
                t = queue.pop(0)
                if t not in visited and t in wf.tasks:
                    visited.add(t)
                    queue.extend(wf.tasks[t].depends_on)
            return visited
        skip_tasks = _ancestors(start_from)

    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}

    # Build team budget specs and agent→team mappings
    team_specs: dict = {}
    agent_teams: dict = {}
    for team_name, team_cfg in wf.teams.items():
        if team_cfg.budget.max_tokens or team_cfg.budget.max_cost_usd or team_cfg.budget.max_api_calls:
            team_specs[team_name] = team_cfg.budget
        all_team_agents = [team_cfg.manager] + team_cfg.members
        for agent_name in all_team_agents:
            agent_teams[agent_name] = team_name

    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs=agent_specs,
        team_specs=team_specs,
        agent_teams=agent_teams,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    ws_root = Path(f"/tmp/agentos-{workflow_id}")
    workspace = Workspace(
        WorkspaceConfig(root=str(ws_root)),
        event_log, seq, workflow_id=workflow_id,
    )
    workspace.ensure_root()

    # Create team workspace directories
    for team_name, team_cfg in wf.teams.items():
        team_ws_name = team_cfg.workspace or f"team_{team_name}"
        (ws_root / team_ws_name).mkdir(parents=True, exist_ok=True)

    # Build ExecutionContext with V2+ modules
    ctx = _build_execution_context(wf, event_log, seq, workflow_id, db, memory_db)

    if live:
        task_executor = _build_live_executor(
            wf, budget_mgr, gate_mgr, ws_root,
            event_log, seq, workflow_id,
            interactive=interactive,
            execution_context=ctx,
        )
    else:
        def task_executor(task_name: str, config: TaskConfig, predecessors=None) -> TaskStatus:
            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
                click.echo(f"  GATE  {task_name} — auto-approved")
                return TaskStatus.SUCCEEDED

            if config.type == "input_gate":
                gate_id = gate_mgr.create_gate(task_name, GateType.INPUT, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="auto")
                click.echo(f"  INPUT {task_name} — auto-approved (stub)")
                return TaskStatus.SUCCEEDED, TaskOutput(
                    task_id=task_name, agent_id="input_gate",
                    status=TaskStatus.SUCCEEDED,
                    summary="Stub input: no constraints provided.",
                )

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

    # On resume, clear workspace subdirectories for tasks that will re-execute
    # (i.e., tasks NOT in skip_tasks) so agents don't find stale files.
    if skip_tasks:
        import shutil

        for task_name, task_cfg in wf.tasks.items():
            if task_name not in skip_tasks:
                task_ws = ws_root / task_cfg.workspace / task_name
                if task_ws.exists():
                    shutil.rmtree(task_ws)
                    task_ws.mkdir(parents=True, exist_ok=True)

    # Wrap executor to replay skipped tasks from cached workspace manifests
    if skip_tasks:
        _real_executor = task_executor

        def _skip_ts() -> str:
            return datetime.now().strftime("%H:%M:%S")

        def task_executor(task_name: str, config: TaskConfig, predecessors=None):
            if task_name in skip_tasks:
                # Try to load manifest from previous run's workspace
                task_ws = ws_root / config.workspace / task_name
                manifest = None
                manifest_path = task_ws / "manifest.json"
                if manifest_path.exists():
                    try:
                        manifest = json.loads(manifest_path.read_text())
                    except (json.JSONDecodeError, OSError):
                        pass

                if manifest is not None:
                    from agentos.adapters.tier2_shared import manifest_to_task_output
                    output = manifest_to_task_output(
                        manifest, task_id=task_name,
                        agent_id=config.agent or "replayed",
                        metrics=TaskMetrics(execution_time_seconds=0.0),
                    )
                    click.echo(f"  [{_skip_ts()}] {click.style('SKIP', fg='cyan')}  {task_name} (replayed from manifest)")
                    return TaskStatus.SUCCEEDED, output

                # No manifest — synthesize a minimal output from the task config
                click.echo(f"  [{_skip_ts()}] {click.style('SKIP', fg='cyan')}  {task_name} (no manifest, synthetic output)")
                return TaskStatus.SUCCEEDED, TaskOutput(
                    task_id=task_name,
                    agent_id=config.agent or "replayed",
                    status=TaskStatus.SUCCEEDED,
                    summary=f"Replayed (no manifest): {config.description[:200] if config.description else task_name}",
                )

            return _real_executor(task_name, config, predecessors)

    mode = click.style("LIVE", fg="yellow", bold=True) if live else "stub"
    click.echo(f"{'─' * 60}")
    click.echo(f"  Workflow:  {wf.name}")
    click.echo(f"  ID:        {workflow_id}")
    teams_info = f"  |  Teams: {len(wf.teams)}" if wf.teams else ""
    click.echo(f"  Tasks:     {len(wf.tasks)}  |  Agents: {len(wf.agents)}{teams_info}  |  Mode: {mode}")
    if skip_tasks:
        click.echo(f"  Resuming:  from {click.style(start_from, fg='cyan')} (skipping {len(skip_tasks)} tasks)")
    if db != ":memory:":
        click.echo(f"  DB:        {db}")

    # Pre-run analysis
    _run_pre_run_analysis(wf, event_log)

    click.echo(f"{'─' * 60}")
    click.echo()

    run_start = time.monotonic()

    executor = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=task_executor,
        context=ctx,
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

    # Post-run intelligence
    _run_post_run_intelligence(wf, result, budget_mgr, ctx, memory_db)

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


@workflow.command()
@click.argument("yaml_file", type=click.Path(exists=True))
def doctor(yaml_file: str) -> None:
    """Check a workflow YAML for common configuration mistakes."""
    import yaml as _yaml

    raw = Path(yaml_file).read_text()

    # Parse YAML
    try:
        data = _yaml.safe_load(raw)
    except _yaml.YAMLError as e:
        click.echo(click.style(f"YAML parse error: {e}", fg="red"))
        raise SystemExit(1)

    # Validate against schema
    try:
        wf = WorkflowDefinition.model_validate(data)
    except Exception as e:
        click.echo(click.style(f"Schema validation error: {e}", fg="red"))
        raise SystemExit(1)

    # Run verifier
    verifier = WorkflowVerifier()
    report = verifier.verify(wf)

    task_count = len(wf.tasks)
    agent_count = len(wf.agents)
    team_count = len(wf.teams) if wf.teams else 0
    header = f"Workflow: {wf.name} ({task_count} tasks, {agent_count} agents"
    if team_count:
        header += f", {team_count} teams"
    header += ")"
    click.echo(header)
    click.echo()

    if report.errors:
        click.echo(click.style("Errors (must fix):", fg="red", bold=True))
        for i, issue in enumerate(report.errors, 1):
            click.echo(click.style(f"  [E{i:03d}] ", fg="red") + issue.message)
        click.echo()

    if report.warnings:
        click.echo(click.style("Warnings (should fix):", fg="yellow", bold=True))
        for i, issue in enumerate(report.warnings, 1):
            click.echo(click.style(f"  [W{i:03d}] ", fg="yellow") + issue.message)
        click.echo()

    # Summary
    error_count = len(report.errors)
    warning_count = len(report.warnings)

    if error_count == 0 and warning_count == 0:
        click.echo(click.style("Result: No issues found.", fg="green"))
    else:
        parts = []
        if error_count:
            parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")
        if warning_count:
            parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
        click.echo(f"Result: {', '.join(parts)}")

    if error_count > 0:
        raise SystemExit(1)


@workflow.command()
@click.option("--output", "-o", default=None, help="Output file path (default: stdout)")
def schema(output: str | None) -> None:
    """Output the JSON Schema for workflow YAML files."""
    import json as _json

    schema_data = WorkflowDefinition.model_json_schema()
    content = _json.dumps(schema_data, indent=2)

    if output:
        Path(output).write_text(content)
        click.echo(f"Schema written to: {output}")
    else:
        click.echo(content)
