"""Context summary manager — anchored iterative summaries per agent.

Uses Factory AI's 4-field pattern: intent, changes_made, decisions, next_steps.
Summaries are incrementally merged, never regenerated from scratch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agentos.workspace.schemas import AgentContextSummary, WorkspaceContextSummary

logger = logging.getLogger(__name__)

# Maximum items per list field to keep summaries under ~2K tokens.
_MAX_LIST_ITEMS = 10


class ContextSummaryManager:
    """Maintains per-agent and workspace-level structured summaries."""

    def __init__(self, workspace_dir: Path | None = None) -> None:
        self._summaries: dict[str, AgentContextSummary] = {}
        self._workspace_summary = WorkspaceContextSummary()
        self._dir = workspace_dir

    # ------------------------------------------------------------------
    # Agent summaries
    # ------------------------------------------------------------------

    def get_agent_summary(self, agent_id: str) -> AgentContextSummary | None:
        return self._summaries.get(agent_id)

    def update_agent_summary(
        self,
        agent_id: str,
        task_output: dict,
        task_title: str = "",
    ) -> AgentContextSummary:
        """Incrementally merge task output into the agent's summary."""
        existing = self._summaries.get(agent_id)
        if existing is None:
            existing = AgentContextSummary(agent_id=agent_id)

        # Merge — append new info, trim to max
        summary_text = task_output.get("summary", "")
        if summary_text and summary_text not in existing.changes_made:
            existing.changes_made = (existing.changes_made + [summary_text])[-_MAX_LIST_ITEMS:]

        for finding in task_output.get("findings", task_output.get("key_findings", [])):
            text = finding if isinstance(finding, str) else finding.get("finding", "")
            if text and text not in existing.decisions:
                existing.decisions = (existing.decisions + [text])[-_MAX_LIST_ITEMS:]

        for q in task_output.get("open_questions", []):
            if q not in existing.next_steps:
                existing.next_steps = (existing.next_steps + [q])[-_MAX_LIST_ITEMS:]

        for f in task_output.get("files_produced", []):
            if f not in existing.entity_references:
                existing.entity_references = (existing.entity_references + [f])[-_MAX_LIST_ITEMS:]

        if task_title:
            existing.tasks_completed = (existing.tasks_completed + [task_title])[-_MAX_LIST_ITEMS:]

        existing.summary_version += 1
        from agentos.workspace.schemas import _utc_now_iso
        existing.last_active = _utc_now_iso()

        self._summaries[agent_id] = existing
        self._persist_agent(agent_id)
        return existing

    # ------------------------------------------------------------------
    # Workspace summary
    # ------------------------------------------------------------------

    def get_workspace_summary(self) -> WorkspaceContextSummary:
        return self._workspace_summary

    def update_workspace_summary(
        self,
        tasks_completed: int = 0,
        tasks_remaining: int = 0,
        budget_consumed_pct: float = 0.0,
        new_decisions: list[str] | None = None,
        new_artifacts: list[str] | None = None,
        status: str = "",
    ) -> WorkspaceContextSummary:
        """Incrementally update the workspace-level summary."""
        ws = self._workspace_summary
        ws.tasks_completed = tasks_completed
        ws.tasks_remaining = tasks_remaining
        ws.budget_consumed_pct = budget_consumed_pct

        if status:
            ws.current_status = status

        if new_decisions:
            ws.key_decisions = (ws.key_decisions + new_decisions)[-_MAX_LIST_ITEMS:]
        if new_artifacts:
            ws.key_artifacts = (ws.key_artifacts + new_artifacts)[-_MAX_LIST_ITEMS:]

        self._persist_workspace()
        return ws

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_agent(self, agent_id: str) -> None:
        if self._dir is None:
            return
        summaries_dir = self._dir / ".agentos" / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        path = summaries_dir / f"{agent_id}.json"
        path.write_text(self._summaries[agent_id].model_dump_json(indent=2))

    def _persist_workspace(self) -> None:
        if self._dir is None:
            return
        summaries_dir = self._dir / ".agentos" / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        path = summaries_dir / "workspace.json"
        path.write_text(self._workspace_summary.model_dump_json(indent=2))

    def load_from_disk(self) -> None:
        """Load summaries from disk (for workspace resume)."""
        if self._dir is None:
            return
        summaries_dir = self._dir / ".agentos" / "summaries"
        if not summaries_dir.exists():
            return

        for path in summaries_dir.glob("*.json"):
            if path.stem == "workspace":
                self._workspace_summary = WorkspaceContextSummary(
                    **json.loads(path.read_text())
                )
            else:
                self._summaries[path.stem] = AgentContextSummary(
                    **json.loads(path.read_text())
                )
