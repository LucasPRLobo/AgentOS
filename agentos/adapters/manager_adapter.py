"""Manager Agent adapter — team-based orchestration via Claude Code instances.

The manager is a real Claude Code (or other Tier 2) instance, not an API loop.
This adapter orchestrates multi-round interaction:

  Round 1 (Plan):   Manager CC receives task + team info → produces assignment plan
  Round 2 (Execute): Each assigned member's adapter runs with manager's instructions
  Round 3 (Review):  Manager CC sees all member results → produces consolidated output
  Round 3+ (Revise): If manager requests reassignments, members re-run, then review again

The manager has visibility into member work through workspace files and
structured result summaries fed back into its prompt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agentos.adapters.base import AgentAdapter
from agentos.adapters.manager_agent import (
    MAX_SUPERVISION_ROUNDS,
    build_manager_system_prompt,
    build_planning_task,
    build_review_task,
    parse_assignment_plan,
    parse_reassignments,
    write_member_results,
)
from agentos.adapters.tier2_shared import (
    manifest_to_task_output,
    parse_manifest,
)
from agentos.kernel.budget_manager import BudgetManager
from agentos.schemas.task import TaskMetrics, TaskOutput, TaskStatus


class ManagerAgentAdapter(AgentAdapter):
    """Tier 2 adapter that wraps a Claude Code instance as a team manager.

    The manager adapter holds references to its team member adapters and
    orchestrates the plan → execute → review loop.
    """

    @property
    def tier(self) -> int:
        return 2

    def __init__(
        self,
        budget_manager: BudgetManager,
        agent_id: str,
        *,
        manager_adapter: AgentAdapter | None = None,
        team_name: str = "",
        team_description: str = "",
        member_adapters: dict[str, AgentAdapter] | None = None,
        member_roles: dict[str, str] | None = None,
        member_tools: dict[str, list[str]] | None = None,
        channel_router: Any | None = None,
        team_channel: str = "",
        gate_manager: Any | None = None,
        human_input_enabled: bool = False,
        interactive: bool = False,
        # Legacy compat: downstream_adapters for teamless managers
        downstream_adapters: dict[str, AgentAdapter] | None = None,
        role: str = "",
    ) -> None:
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._manager_adapter = manager_adapter
        self._team_name = team_name
        self._team_description = team_description
        self._member_adapters = member_adapters or {}
        self._member_roles = member_roles or {}
        self._member_tools: dict[str, list[str]] = member_tools or {}
        self._channel_router = channel_router
        self._team_channel = team_channel
        self._gate_manager = gate_manager
        self._human_input_enabled = human_input_enabled
        self._interactive = interactive
        self._terminated = False

        # Legacy fallback for teamless managers
        self._downstream = downstream_adapters or {}
        self._legacy_role = role

    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Run the manager's multi-round team orchestration loop."""
        if self._terminated:
            return TaskOutput(
                task_id="",
                agent_id=self._agent_id,
                status=TaskStatus.FAILED,
                summary="Manager adapter was terminated.",
            )

        start_time = time.monotonic()

        # If no team is configured, fall back to legacy single-delegation mode
        if not self._member_adapters and self._downstream:
            return await self._legacy_route(
                task_description, role, workspace,
                predecessor_context, allowed_tools,
            )

        # If no manager_adapter is set, nothing to do
        if self._manager_adapter is None:
            return TaskOutput(
                task_id="",
                agent_id=self._agent_id,
                status=TaskStatus.FAILED,
                summary="Manager adapter not configured (no underlying CC instance).",
            )

        # Build manager's enriched role prompt with team context
        manager_role = build_manager_system_prompt(
            team_name=self._team_name,
            team_description=self._team_description,
            member_roles=self._member_roles,
            human_input_enabled=self._human_input_enabled,
        )

        # Combine with any explicit role from the workflow YAML
        if role:
            manager_role = f"{role}\n\n{manager_role}"

        predecessor_summaries = [
            f"[{ctx.task_id}] {ctx.summary}"
            for ctx in predecessor_context
            if ctx.summary
        ]

        # Track aggregate metrics across all rounds and member executions
        total_tokens = 0
        total_cost = 0.0

        # Build a workspace file index so the manager doesn't waste turns exploring
        workspace_files: list[str] = []
        ws_root = workspace.parent  # workspace is ws_root/config.workspace/task_name
        if ws_root.exists():
            for p in sorted(ws_root.rglob("*")):
                if p.is_file() and ".agentos_context" not in str(p):
                    workspace_files.append(str(p))

        # === Round 1: Planning ===
        # Manager needs Write (to create assignment_plan.json + manifest.json),
        # Read (to read predecessor context), and Glob (to discover files from
        # predecessor workspaces). No web search, no bash.
        planning_tools = ["Read", "Write", "Glob"]
        planning_prompt = build_planning_task(
            task_description, predecessor_summaries, workspace_files,
        )

        plan_output = await self._manager_adapter.execute_task(
            task_description=planning_prompt,
            role=manager_role,
            workspace=workspace,
            predecessor_context=predecessor_context,
            allowed_tools=planning_tools,
        )

        if plan_output.metrics:
            total_tokens += plan_output.metrics.tokens_consumed
            total_cost += plan_output.metrics.estimated_cost_usd

        if plan_output.status == TaskStatus.FAILED:
            return self._make_output(
                "Manager planning round failed: " + plan_output.summary,
                TaskStatus.FAILED, start_time,
                tokens=total_tokens, cost=total_cost,
            )

        # Parse the assignment plan — try assignment_plan.json first, then summary
        plan_file = workspace / "assignment_plan.json"
        if plan_file.exists():
            try:
                import json as _json
                plan_data = _json.loads(plan_file.read_text())
                plan = parse_assignment_plan(_json.dumps(plan_data))
            except Exception:
                plan = parse_assignment_plan(plan_output.summary)
        else:
            plan = parse_assignment_plan(plan_output.summary)

        if not plan.assignments:
            # Manager didn't assign any work — treat its output as the final result
            return self._make_output(
                plan_output.summary, TaskStatus.SUCCEEDED, start_time,
                findings=plan_output.key_findings,
                tokens=total_tokens, cost=total_cost,
            )

        # === Rounds 2+: Execute → Review → (optional Revise) ===
        member_results: dict[str, dict[str, Any]] = {}
        total_rounds = 0

        assignments = plan.assignments

        for round_num in range(MAX_SUPERVISION_ROUNDS):
            total_rounds += 1

            # Execute assignments
            for assignment in assignments:
                if assignment.member not in self._member_adapters:
                    member_results[assignment.member] = {
                        "summary": f"Member {assignment.member!r} not found in team",
                        "findings": [],
                    }
                    continue

                member_adapter = self._member_adapters[assignment.member]
                member_role = self._member_roles.get(assignment.member, "")

                # Create member workspace subdirectory
                member_ws = workspace / f"member_{assignment.member}"
                member_ws.mkdir(parents=True, exist_ok=True)

                # Use the member's own tool list, not the manager's.
                # Falls back to the task-level tools if member has none defined.
                member_tools = self._member_tools.get(
                    assignment.member, allowed_tools,
                )

                member_output = await member_adapter.execute_task(
                    task_description=assignment.instruction,
                    role=member_role,
                    workspace=member_ws,
                    predecessor_context=predecessor_context,
                    allowed_tools=member_tools,
                )

                # Aggregate member metrics
                if member_output.metrics:
                    total_tokens += member_output.metrics.tokens_consumed
                    total_cost += member_output.metrics.estimated_cost_usd

                # Store result as dict for the manager to review
                member_results[assignment.member] = {
                    "summary": member_output.summary,
                    "status": str(member_output.status),
                    "findings": [
                        {
                            "finding": f.finding,
                            "confidence": str(f.confidence),
                            "sources": f.sources,
                        }
                        for f in member_output.key_findings
                    ],
                    "open_questions": member_output.open_questions,
                }

                # Broadcast to team channel if available
                if self._channel_router and self._team_channel:
                    try:
                        self._channel_router.publish(
                            self._team_channel,
                            task_id=f"{self._agent_id}_member_{assignment.member}",
                            agent_id=assignment.member,
                            content=member_results[assignment.member],
                        )
                    except Exception:
                        pass

            # Write member results to workspace so manager can see files
            write_member_results(workspace, member_results)

            # === Review round: Manager evaluates member work ===
            # Manager needs Read (to see member outputs), Write (manifest),
            # and Glob (to discover files across member workspaces).
            review_tools = ["Read", "Write", "Glob"]
            review_prompt = build_review_task(task_description, member_results)

            review_output = await self._manager_adapter.execute_task(
                task_description=review_prompt,
                role=manager_role,
                workspace=workspace,
                predecessor_context=predecessor_context,
                allowed_tools=review_tools,
            )

            # Aggregate review round metrics
            if review_output.metrics:
                total_tokens += review_output.metrics.tokens_consumed
                total_cost += review_output.metrics.estimated_cost_usd

            # Check for manifest with potential reassignments
            manifest = parse_manifest(workspace)
            if manifest is not None:
                reassignments = parse_reassignments(manifest)
                if reassignments and round_num < MAX_SUPERVISION_ROUNDS - 1:
                    # Manager wants revisions — loop again with new assignments
                    assignments = reassignments
                    # Clean manifest for next round
                    manifest_path = workspace / "manifest.json"
                    if manifest_path.exists():
                        manifest_path.unlink()
                    continue

                # No reassignments or last round — produce final output
                elapsed = time.monotonic() - start_time
                metrics = TaskMetrics(
                    execution_time_seconds=round(elapsed, 2),
                    tokens_consumed=total_tokens,
                    estimated_cost_usd=round(total_cost, 6),
                )
                return manifest_to_task_output(
                    manifest, task_id="", agent_id=self._agent_id, metrics=metrics,
                )

            # No manifest — use review output directly
            return self._make_output(
                review_output.summary, TaskStatus.SUCCEEDED, start_time,
                findings=review_output.key_findings,
                tokens=total_tokens, cost=total_cost,
            )

        # Exhausted all rounds
        return self._make_output(
            f"Manager completed {total_rounds} supervision rounds. "
            f"Last results: {json.dumps({k: v.get('summary', '') for k, v in member_results.items()})}",
            TaskStatus.SUCCEEDED, start_time,
            tokens=total_tokens, cost=total_cost,
        )

    async def terminate(self) -> None:
        """Terminate the manager and all member adapters."""
        self._terminated = True
        if self._manager_adapter is not None:
            await self._manager_adapter.terminate()
        for adapter in self._member_adapters.values():
            await adapter.terminate()
        for adapter in self._downstream.values():
            await adapter.terminate()

    def _make_output(
        self,
        summary: str,
        status: TaskStatus,
        start_time: float,
        findings: list | None = None,
        tokens: int = 0,
        cost: float = 0.0,
    ) -> TaskOutput:
        elapsed = time.monotonic() - start_time
        return TaskOutput(
            task_id="",
            agent_id=self._agent_id,
            status=status,
            summary=summary,
            key_findings=findings or [],
            metrics=TaskMetrics(
                execution_time_seconds=round(elapsed, 2),
                tokens_consumed=tokens,
                estimated_cost_usd=round(cost, 6),
            ),
        )

    async def _legacy_route(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Fallback for teamless managers — delegate to first downstream adapter.

        This preserves backward compatibility with workflows that use
        ``adapter: manager`` without defining teams.
        """
        if not self._downstream:
            return TaskOutput(
                task_id="",
                agent_id=self._agent_id,
                status=TaskStatus.FAILED,
                summary="Manager has no downstream adapters configured.",
            )

        # Pick the first downstream adapter
        target_name = next(iter(self._downstream))
        target = self._downstream[target_name]

        return await target.execute_task(
            task_description=task_description,
            role=role,
            workspace=workspace,
            predecessor_context=predecessor_context,
            allowed_tools=allowed_tools,
        )
