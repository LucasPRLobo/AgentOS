"""Project artifacts — shared thinking surfaces for the workspace.

Structured documents that both humans and agents read and update.
These persist across sessions and serve as the collaboration record.

Inspired by GSD's PROJECT.md / REQUIREMENTS.md / STATE.md pattern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectArtifacts:
    """Manages shared project documents in the workspace."""

    def __init__(self, workspace_dir: Path) -> None:
        self._dir = workspace_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._tasks_dir = self._dir / "tasks"
        self._tasks_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # PROJECT.md
    # ------------------------------------------------------------------

    def write_project(
        self, goal: str, description: str = "",
        constraints: list[str] | None = None,
        criteria: list[str] | None = None,
    ) -> None:
        """Write/update PROJECT.md from kickoff discussion."""
        lines = [
            "# Project",
            "",
            f"## Goal",
            goal.strip(),
        ]
        if description:
            lines += ["", "## Description", description.strip()]
        if constraints:
            lines += ["", "## Constraints"]
            lines += [f"- {c}" for c in constraints]
        if criteria:
            lines += ["", "## Success Criteria"]
            lines += [f"- {c}" for c in criteria]
        lines += ["", f"_Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_"]

        (self._dir / "PROJECT.md").write_text("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # PLAN.md
    # ------------------------------------------------------------------

    def write_plan(self, plan_summary: str, tasks: list[dict]) -> None:
        """Write/update PLAN.md from agreed plan."""
        lines = [
            "# Plan",
            "",
            plan_summary.strip(),
            "",
            "## Tasks",
        ]
        for i, t in enumerate(tasks, 1):
            title = t.get("title", "Untitled")
            assigned = t.get("suggested_for") or t.get("assigned_to") or "unassigned"
            status = t.get("status", "proposed")
            lines.append(f"{i}. **{title}** → {assigned} [{status}]")
            if t.get("spec"):
                lines.append(f"   Spec: {t['spec'][:100]}")

        lines += ["", f"_Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_"]
        (self._dir / "PLAN.md").write_text("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # DECISIONS.md
    # ------------------------------------------------------------------

    def add_decision(
        self, decision: str, rationale: str = "",
        discussion_id: str = "",
    ) -> None:
        """Append a decision to DECISIONS.md."""
        path = self._dir / "DECISIONS.md"
        existing = path.read_text() if path.exists() else "# Decisions\n"

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"\n## {timestamp}\n**Decision:** {decision}\n"
        if rationale:
            entry += f"**Rationale:** {rationale}\n"

        path.write_text(existing + entry)

    # ------------------------------------------------------------------
    # STATE.md
    # ------------------------------------------------------------------

    def update_state(
        self, tasks: list[dict],
        team_status: list[dict] | None = None,
        budget_info: str = "",
    ) -> None:
        """Rewrite STATE.md with current progress."""
        lines = ["# Current State", ""]

        # Task summary
        total = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "done")
        active = sum(1 for t in tasks if t.get("status") in ("claimed", "in_progress", "completed", "in_review"))
        lines.append(f"**Progress:** {done}/{total} tasks done, {active} active")
        lines.append("")

        # Task details
        lines.append("## Tasks")
        for t in tasks:
            status = t.get("status", "?")
            title = t.get("title", "Untitled")
            assigned = t.get("assigned_to") or "unassigned"
            lines.append(f"- [{status:12s}] {title} → {assigned}")
        lines.append("")

        # Team
        if team_status:
            lines.append("## Team")
            for agent in team_status:
                name = agent.get("agent_name") or agent.get("agent_id", "?")
                state = agent.get("state", "?")
                lines.append(f"- {name}: {state}")
            lines.append("")

        if budget_info:
            lines.append(f"## Budget\n{budget_info}\n")

        lines.append(f"_Last updated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}_")
        (self._dir / "STATE.md").write_text("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # Task specs and outputs
    # ------------------------------------------------------------------

    def write_task_spec(
        self, task_id: str, title: str,
        spec: str, approach: str = "", expected_output: str = "",
    ) -> None:
        """Write a task specification file."""
        lines = [
            f"# Task: {title}",
            "",
            "## Specification",
            spec.strip(),
        ]
        if approach:
            lines += ["", "## Approach", approach.strip()]
        if expected_output:
            lines += ["", "## Expected Output", expected_output.strip()]

        safe_id = task_id[:8]
        (self._tasks_dir / f"{safe_id}-spec.md").write_text("\n".join(lines) + "\n")

    def write_task_output(
        self, task_id: str, title: str,
        summary: str, findings: list[str] | None = None,
    ) -> None:
        """Write a task output summary file."""
        lines = [
            f"# Output: {title}",
            "",
            "## Summary",
            summary.strip(),
        ]
        if findings:
            lines += ["", "## Findings"]
            for f in findings:
                lines.append(f"- {f}")

        safe_id = task_id[:8]
        (self._tasks_dir / f"{safe_id}-output.md").write_text("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_project_brief(self) -> str:
        """Read PROJECT.md and return it (or empty if not written yet)."""
        path = self._dir / "PROJECT.md"
        return path.read_text() if path.exists() else ""

    def get_decisions(self) -> str:
        """Read DECISIONS.md."""
        path = self._dir / "DECISIONS.md"
        return path.read_text() if path.exists() else ""

    def get_state(self) -> str:
        """Read STATE.md."""
        path = self._dir / "STATE.md"
        return path.read_text() if path.exists() else ""

    def get_plan(self) -> str:
        """Read PLAN.md."""
        path = self._dir / "PLAN.md"
        return path.read_text() if path.exists() else ""
