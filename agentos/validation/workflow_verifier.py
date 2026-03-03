"""Workflow verifier — static analysis of workflow DAGs before execution."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, Field

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
