"""Workflow verifier — static analysis of workflow DAGs before execution."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, Field

from agentos.schemas.tool_mapping import TIER2_TOOL_MAP, VALID_TOOLS
from agentos.schemas.workflow import WorkflowDefinition


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class VerificationIssue(BaseModel):
    """A single verification finding."""

    severity: Severity
    code: str = Field(description="Machine-readable issue code")
    message: str = Field(description="Human-readable description")
    task: str | None = Field(default=None, description="Task name if applicable")
    agent: str | None = Field(default=None, description="Agent name if applicable")


class VerificationReport(BaseModel):
    """Result of workflow verification."""

    valid: bool = True
    errors: list[VerificationIssue] = Field(default_factory=list)
    warnings: list[VerificationIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.errors) + len(self.warnings)


class WorkflowVerifier:
    """Static analysis of workflow DAGs before execution.

    Checks:
    1. No circular dependencies (cycle detection)
    2. All depends_on references exist (orphan dependencies)
    3. All task.agent references exist in agents section
    4. No unreachable tasks (tasks with no path from any root)
    5. Budget allocations: per-agent totals don't exceed workflow total
    6. Gates have no agent assigned (warning)
    7. Tasks have required fields for their type
    """

    def verify(self, workflow: WorkflowDefinition) -> VerificationReport:
        """Run all verification checks and return a report."""
        errors: list[VerificationIssue] = []
        warnings: list[VerificationIssue] = []

        task_names = set(workflow.tasks.keys())
        agent_names = set(workflow.agents.keys())

        self._check_missing_dependencies(workflow, task_names, errors)
        self._check_undefined_agents(workflow, agent_names, errors)
        self._check_cycles(workflow, task_names, errors)
        self._check_unreachable_tasks(workflow, task_names, errors)
        self._check_budget_allocations(workflow, warnings)
        self._check_gate_agents(workflow, warnings)
        self._check_agent_tasks_have_agents(workflow, errors)
        self._check_empty_workflow(workflow, warnings)
        self._check_conditions(workflow, task_names, errors)
        self._check_consultation_tasks(workflow, agent_names, errors)
        self._check_retry_policies(workflow, warnings)
        self._check_teams(workflow, agent_names, errors, warnings)
        self._check_tool_names(workflow, warnings)
        self._check_write_capability(workflow, warnings)
        self._check_workspace_conflicts(workflow, warnings)
        self._check_manager_tool_restrictions(workflow, errors)

        report = VerificationReport(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
        return report

    def _check_missing_dependencies(
        self,
        workflow: WorkflowDefinition,
        task_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            for dep in config.depends_on:
                if dep not in task_names:
                    errors.append(VerificationIssue(
                        severity=Severity.ERROR,
                        code="missing_dependency",
                        message=f"Task {name!r} depends on {dep!r}, which does not exist",
                        task=name,
                    ))

    def _check_undefined_agents(
        self,
        workflow: WorkflowDefinition,
        agent_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            if config.agent and config.agent not in agent_names:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="undefined_agent",
                    message=f"Task {name!r} references agent {config.agent!r}, "
                            f"which is not defined in agents section",
                    task=name,
                    agent=config.agent,
                ))

    def _check_cycles(
        self,
        workflow: WorkflowDefinition,
        task_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        adj: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {name: 0 for name in task_names}
        for name, config in workflow.tasks.items():
            for dep in config.depends_on:
                if dep in task_names:
                    adj[dep].append(name)
                    in_deg[name] += 1

        queue = [n for n, d in in_deg.items() if d == 0]
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for dependent in adj[node]:
                in_deg[dependent] -= 1
                if in_deg[dependent] == 0:
                    queue.append(dependent)

        if visited != len(task_names):
            errors.append(VerificationIssue(
                severity=Severity.ERROR,
                code="cycle_detected",
                message="Workflow contains a circular dependency",
            ))

    def _check_unreachable_tasks(
        self,
        workflow: WorkflowDefinition,
        task_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        if not task_names:
            return

        roots = {name for name, config in workflow.tasks.items() if not config.depends_on}
        if not roots:
            errors.append(VerificationIssue(
                severity=Severity.ERROR,
                code="no_root_tasks",
                message="No root tasks found (all tasks have dependencies)",
            ))
            return

        # BFS from roots to find all reachable tasks
        adj: dict[str, list[str]] = defaultdict(list)
        for name, config in workflow.tasks.items():
            for dep in config.depends_on:
                if dep in task_names:
                    adj[dep].append(name)

        reachable: set[str] = set()
        queue = list(roots)
        while queue:
            node = queue.pop(0)
            if node in reachable:
                continue
            reachable.add(node)
            for dependent in adj[node]:
                if dependent not in reachable:
                    queue.append(dependent)

        unreachable = task_names - reachable
        for name in sorted(unreachable):
            errors.append(VerificationIssue(
                severity=Severity.ERROR,
                code="unreachable_task",
                message=f"Task {name!r} is not reachable from any root task",
                task=name,
            ))

    def _check_budget_allocations(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        wf_budget = workflow.budget

        for agent_name, agent_cfg in workflow.agents.items():
            ab = agent_cfg.budget

            if wf_budget.max_tokens and ab.max_tokens and ab.max_tokens > wf_budget.max_tokens:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="budget_exceeds_workflow",
                    message=f"Agent {agent_name!r} token budget ({ab.max_tokens:,}) "
                            f"exceeds workflow total ({wf_budget.max_tokens:,})",
                    agent=agent_name,
                ))

            if wf_budget.max_cost_usd and ab.max_cost_usd and ab.max_cost_usd > wf_budget.max_cost_usd:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="budget_exceeds_workflow",
                    message=f"Agent {agent_name!r} cost budget (${ab.max_cost_usd:.2f}) "
                            f"exceeds workflow total (${wf_budget.max_cost_usd:.2f})",
                    agent=agent_name,
                ))

            if (wf_budget.max_api_calls and ab.max_api_calls
                    and ab.max_api_calls > wf_budget.max_api_calls):
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="budget_exceeds_workflow",
                    message=f"Agent {agent_name!r} API call budget ({ab.max_api_calls}) "
                            f"exceeds workflow total ({wf_budget.max_api_calls})",
                    agent=agent_name,
                ))

    def _check_gate_agents(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            if config.type in ("approval_gate", "input_gate") and config.agent:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="gate_has_agent",
                    message=f"Gate {name!r} has an agent assigned (will be ignored)",
                    task=name,
                ))

    def _check_agent_tasks_have_agents(
        self,
        workflow: WorkflowDefinition,
        errors: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            if config.type == "agent_task" and not config.agent:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="agent_task_no_agent",
                    message=f"Agent task {name!r} has no agent assigned",
                    task=name,
                ))

    def _check_empty_workflow(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        if not workflow.tasks:
            warnings.append(VerificationIssue(
                severity=Severity.WARNING,
                code="empty_workflow",
                message="Workflow has no tasks defined",
            ))

    def _check_conditions(
        self,
        workflow: WorkflowDefinition,
        task_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            for cond in config.conditions:
                if cond.target not in task_names:
                    errors.append(VerificationIssue(
                        severity=Severity.ERROR,
                        code="condition_target_missing",
                        message=(
                            f"Task {name!r} has condition targeting {cond.target!r}, "
                            f"which does not exist"
                        ),
                        task=name,
                    ))
                if not cond.expression.strip():
                    errors.append(VerificationIssue(
                        severity=Severity.ERROR,
                        code="condition_empty_expression",
                        message=f"Task {name!r} has condition with empty expression",
                        task=name,
                    ))

    def _check_consultation_tasks(
        self,
        workflow: WorkflowDefinition,
        agent_names: set[str],
        errors: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            if config.type != "consultation":
                continue
            if not config.consult_agent:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="consultation_no_agent",
                    message=f"Consultation task {name!r} has no consult_agent specified",
                    task=name,
                ))
            elif config.consult_agent not in agent_names:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="consultation_undefined_agent",
                    message=(
                        f"Consultation task {name!r} references agent "
                        f"{config.consult_agent!r}, which is not defined"
                    ),
                    task=name,
                ))
            if not config.consult_question:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="consultation_no_question",
                    message=f"Consultation task {name!r} has no consult_question specified",
                    task=name,
                ))

    def _check_retry_policies(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        for name, config in workflow.tasks.items():
            if config.retry_policy is None:
                continue
            if config.retry_policy.on not in ("gate_rejected", "validation_failed"):
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="retry_unknown_trigger",
                    message=(
                        f"Task {name!r} has retry_policy with unknown trigger "
                        f"{config.retry_policy.on!r}"
                    ),
                    task=name,
                ))

    def _check_teams(
        self,
        workflow: WorkflowDefinition,
        agent_names: set[str],
        errors: list[VerificationIssue],
        warnings: list[VerificationIssue],
    ) -> None:
        """Validate team configurations."""
        if not workflow.teams:
            return

        seen_agents: dict[str, str] = {}  # agent_name → team_name

        for team_name, team_cfg in workflow.teams.items():
            # Manager must exist in agents section
            if team_cfg.manager not in agent_names:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="team_manager_undefined",
                    message=(
                        f"Team {team_name!r}: manager {team_cfg.manager!r} "
                        f"is not defined in agents section"
                    ),
                    agent=team_cfg.manager,
                ))

            # All members must exist in agents section
            for member in team_cfg.members:
                if member not in agent_names:
                    errors.append(VerificationIssue(
                        severity=Severity.ERROR,
                        code="team_member_undefined",
                        message=(
                            f"Team {team_name!r}: member {member!r} "
                            f"is not defined in agents section"
                        ),
                        agent=member,
                    ))

            # Manager should not also be a member
            if team_cfg.manager in team_cfg.members:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="team_manager_is_member",
                    message=(
                        f"Team {team_name!r}: manager {team_cfg.manager!r} "
                        f"should not also be listed as a member"
                    ),
                    agent=team_cfg.manager,
                ))

            # No agent in multiple teams
            all_team_agents = [team_cfg.manager] + team_cfg.members
            for agent_name in all_team_agents:
                if agent_name in seen_agents:
                    errors.append(VerificationIssue(
                        severity=Severity.ERROR,
                        code="agent_in_multiple_teams",
                        message=(
                            f"Agent {agent_name!r} is in team {team_name!r} "
                            f"but already belongs to team {seen_agents[agent_name]!r}"
                        ),
                        agent=agent_name,
                    ))
                else:
                    seen_agents[agent_name] = team_name

            # Warn if human_input is true but no input_gate task depends on manager tasks
            if team_cfg.human_input:
                manager_tasks = {
                    t_name for t_name, t_cfg in workflow.tasks.items()
                    if t_cfg.agent == team_cfg.manager
                }
                has_input_gate = any(
                    t_cfg.type == "input_gate"
                    and any(dep in manager_tasks for dep in t_cfg.depends_on)
                    for t_cfg in workflow.tasks.values()
                )
                if not has_input_gate and manager_tasks:
                    warnings.append(VerificationIssue(
                        severity=Severity.WARNING,
                        code="team_human_input_no_gate",
                        message=(
                            f"Team {team_name!r} has human_input=true but no "
                            f"input_gate task depends on manager tasks"
                        ),
                    ))

            # Warn if team budget exceeds workflow budget
            wf_budget = workflow.budget
            tb = team_cfg.budget
            if wf_budget.max_cost_usd and tb.max_cost_usd and tb.max_cost_usd > wf_budget.max_cost_usd:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="team_budget_exceeds_workflow",
                    message=(
                        f"Team {team_name!r} cost budget (${tb.max_cost_usd:.2f}) "
                        f"exceeds workflow total (${wf_budget.max_cost_usd:.2f})"
                    ),
                ))
            if wf_budget.max_tokens and tb.max_tokens and tb.max_tokens > wf_budget.max_tokens:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="team_budget_exceeds_workflow",
                    message=(
                        f"Team {team_name!r} token budget ({tb.max_tokens:,}) "
                        f"exceeds workflow total ({wf_budget.max_tokens:,})"
                    ),
                ))

    def _check_tool_names(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        """Check that YAML tool names are recognized."""
        from difflib import get_close_matches

        for agent_name, agent_cfg in workflow.agents.items():
            for tool in agent_cfg.tools:
                if tool not in VALID_TOOLS:
                    suggestions = get_close_matches(tool, VALID_TOOLS, n=1, cutoff=0.5)
                    hint = f" Did you mean: {suggestions[0]}?" if suggestions else ""
                    warnings.append(VerificationIssue(
                        severity=Severity.WARNING,
                        code="unknown_tool",
                        message=(
                            f"Agent {agent_name!r} has unrecognized tool {tool!r}.{hint}"
                        ),
                        agent=agent_name,
                    ))

    def _check_write_capability(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        """Warn if non-gate tasks lack file_write (needed for manifest.json)."""
        for name, config in workflow.tasks.items():
            if config.type in ("approval_gate", "input_gate"):
                continue
            if not config.agent:
                continue
            agent_cfg = workflow.agents.get(config.agent)
            if agent_cfg and agent_cfg.tools and "file_write" not in agent_cfg.tools:
                warnings.append(VerificationIssue(
                    severity=Severity.WARNING,
                    code="missing_write_tool",
                    message=(
                        f"Agent {config.agent!r} (task {name!r}) has no file_write tool "
                        f"but must produce manifest.json"
                    ),
                    task=name,
                    agent=config.agent,
                ))

    def _check_workspace_conflicts(
        self,
        workflow: WorkflowDefinition,
        warnings: list[VerificationIssue],
    ) -> None:
        """Warn about parallel tasks sharing workspace and agent."""
        # Build transitive ancestor sets for each task
        ancestors: dict[str, set[str]] = {name: set() for name in workflow.tasks}
        # Topological BFS to compute ancestors
        adj: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {name: 0 for name in workflow.tasks}
        for name, config in workflow.tasks.items():
            for dep in config.depends_on:
                if dep in workflow.tasks:
                    adj[dep].append(name)
                    in_deg[name] += 1
        queue = [n for n, d in in_deg.items() if d == 0]
        while queue:
            node = queue.pop(0)
            for child in adj[node]:
                ancestors[child].add(node)
                ancestors[child] |= ancestors[node]
                in_deg[child] -= 1
                if in_deg[child] == 0:
                    queue.append(child)

        # Group tasks by agent
        tasks_by_agent: dict[str, list[str]] = {}
        for name, config in workflow.tasks.items():
            if config.agent:
                tasks_by_agent.setdefault(config.agent, []).append(name)

        for agent_name, task_names in tasks_by_agent.items():
            if len(task_names) < 2:
                continue
            # Check for tasks that could run in parallel (neither is ancestor of the other)
            for i, t1 in enumerate(task_names):
                for t2 in task_names[i + 1:]:
                    if t1 in ancestors[t2] or t2 in ancestors[t1]:
                        continue  # Sequential — no conflict
                    ws1 = workflow.tasks[t1].workspace
                    ws2 = workflow.tasks[t2].workspace
                    if ws1 and ws2 and ws1 == ws2:
                        warnings.append(VerificationIssue(
                            severity=Severity.WARNING,
                            code="workspace_conflict",
                            message=(
                                f"Tasks {t1!r} and {t2!r} may run in parallel "
                                f"sharing agent {agent_name!r} and workspace {ws1!r}"
                            ),
                            task=t1,
                            agent=agent_name,
                        ))

    def _check_manager_tool_restrictions(
        self,
        workflow: WorkflowDefinition,
        errors: list[VerificationIssue],
    ) -> None:
        """Error if manager agents have dangerous tools like Bash or WebSearch."""
        if not workflow.teams:
            return
        dangerous_tools = {"shell_exec", "web_search"}
        for team_name, team_cfg in workflow.teams.items():
            manager_cfg = workflow.agents.get(team_cfg.manager)
            if not manager_cfg:
                continue
            bad_tools = set(manager_cfg.tools) & dangerous_tools
            if bad_tools:
                errors.append(VerificationIssue(
                    severity=Severity.ERROR,
                    code="manager_dangerous_tools",
                    message=(
                        f"Team {team_name!r} manager {team_cfg.manager!r} has "
                        f"dangerous tools: {', '.join(sorted(bad_tools))}. "
                        f"Managers should only have file_read, file_write."
                    ),
                    agent=team_cfg.manager,
                ))
