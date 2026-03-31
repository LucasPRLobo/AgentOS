"""Context curation — purpose-built context packages per task.

Instead of dumping the full board + all predecessors, assemble only
what this specific task needs. Prevents context rot.

Inspired by GSD's context isolation pattern.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.workspace.schemas import BacklogTask, BacklogTaskStatus


class TaskContext(BaseModel):
    """Curated context for a specific task execution."""

    # From specification discussion
    task_spec: str = ""
    approach: str = ""
    expected_output: str = ""

    # Curated predecessors (only relevant)
    relevant_findings: list[str] = Field(default_factory=list)
    relevant_decisions: list[str] = Field(default_factory=list)

    # Compact workspace awareness
    project_brief: str = ""
    team_context: str = ""


class ContextCurator:
    """Assembles curated context packages per task."""

    def __init__(self, workspace_config, backlog, discussions=None, artifacts=None):
        self._config = workspace_config
        self._backlog = backlog
        self._discussions = discussions
        self._artifacts = artifacts

    def curate(self, task: BacklogTask) -> TaskContext:
        """Build a focused context package for a specific task."""
        return TaskContext(
            task_spec=task.spec or task.description,
            approach=task.spec_approach or "",
            expected_output=task.spec_expected_output or "",
            relevant_findings=self._find_relevant_findings(task),
            relevant_decisions=self._find_relevant_decisions(task),
            project_brief=self._build_project_brief(),
            team_context=self._build_team_context(),
        )

    def _find_relevant_findings(self, task: BacklogTask) -> list[str]:
        """Only findings from tasks this task depends on."""
        findings = []
        for dep_id in task.depends_on:
            dep = self._backlog.get_task(dep_id)
            if dep.output and dep.output.get("summary"):
                findings.append(f"[{dep.title}] {dep.output['summary']}")
            if dep.output and dep.output.get("findings"):
                for f in dep.output["findings"][:3]:
                    text = f if isinstance(f, str) else f.get("finding", "")
                    if text:
                        findings.append(f"  - {text}")
        return findings[:10]

    def _find_relevant_decisions(self, task: BacklogTask) -> list[str]:
        """Decisions from resolved discussions affecting this task."""
        decisions = []
        if self._discussions is None:
            return decisions

        # Decisions from this task's own spec discussion
        task_discussions = self._discussions.get_for_task(task.task_id)
        for d in task_discussions:
            if d.decision:
                decisions.append(d.decision)

        # Global decisions (kickoff, replan) affect all tasks
        for d in self._discussions.get_resolved_decisions():
            if d["type"] in ("kickoff", "replan"):
                decisions.append(d["decision"])

        return decisions[:5]

    def _build_project_brief(self) -> str:
        """Compact project summary."""
        goal = self._config.goal.strip()
        if len(goal) > 200:
            goal = goal[:200] + "..."

        criteria = ", ".join(self._config.acceptance_criteria[:3])
        brief = f"Goal: {goal}"
        if criteria:
            brief += f"\nSuccess criteria: {criteria}"
        return brief

    def _build_team_context(self) -> str:
        """One line per agent."""
        lines = []
        for p in self._config.team:
            if p.type == "agent":
                lines.append(f"- {p.name}: {p.specialization or 'general'}")
        return "\n".join(lines)

    def render_prompt_section(self, ctx: TaskContext) -> str:
        """Render a curated context as a prompt section."""
        parts = []

        if ctx.task_spec:
            parts.append(f"## Task Specification\n{ctx.task_spec}")
        if ctx.approach:
            parts.append(f"## Approach\n{ctx.approach}")
        if ctx.expected_output:
            parts.append(f"## Expected Output\n{ctx.expected_output}")

        if ctx.relevant_findings:
            parts.append("## Relevant Findings from Prior Work")
            parts.extend(ctx.relevant_findings)

        if ctx.relevant_decisions:
            parts.append("## Key Decisions")
            for d in ctx.relevant_decisions:
                parts.append(f"- {d}")

        if ctx.project_brief:
            parts.append(f"## Project Context\n{ctx.project_brief}")

        if ctx.team_context:
            parts.append(f"## Team\n{ctx.team_context}")

        return "\n\n".join(parts)
