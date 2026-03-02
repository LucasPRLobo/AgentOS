"""Episodic store — derive and persist run summaries from the event log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import EventType


class EpisodeSummary(BaseModel):
    """Summary of a single run derived from the event log."""

    run_id: RunId
    workflow_name: str = ""
    outcome: str = ""  # "SUCCEEDED" | "FAILED" | "UNKNOWN"
    total_events: int = 0
    task_count: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    tool_calls: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failed_task: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodicStore:
    """Derives and caches run summaries from the event log.

    Provides episodic memory — a queryable history of past runs.
    """

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log
        self._cache: dict[RunId, EpisodeSummary] = {}

    def summarize(self, run_id: RunId) -> EpisodeSummary:
        """Derive a summary for a run from its event stream."""
        if run_id in self._cache:
            return self._cache[run_id]

        events = self._event_log.replay(run_id)
        if not events:
            return EpisodeSummary(run_id=run_id, outcome="UNKNOWN")

        summary = EpisodeSummary(
            run_id=run_id,
            total_events=len(events),
        )

        task_ids_succeeded: set[str] = set()
        task_ids_failed: set[str] = set()
        task_ids_started: set[str] = set()

        for event in events:
            if event.event_type == EventType.RUN_STARTED:
                summary.workflow_name = event.payload.get("workflow", "")
                summary.started_at = event.timestamp

            elif event.event_type == EventType.RUN_FINISHED:
                summary.outcome = event.payload.get("outcome", "UNKNOWN")
                summary.finished_at = event.timestamp
                if summary.outcome == "FAILED":
                    summary.failed_task = event.payload.get("failed_task")
                    # DAG executor uses "failed_tasks" (list)
                    if summary.failed_task is None:
                        failed_list = event.payload.get("failed_tasks", [])
                        if failed_list:
                            summary.failed_task = failed_list[0]

            elif event.event_type == EventType.TASK_STARTED:
                tid = event.payload.get("task_id", "")
                task_ids_started.add(tid)

            elif event.event_type == EventType.TASK_FINISHED:
                tid = event.payload.get("task_id", "")
                state = event.payload.get("state", "")
                if state == "SUCCEEDED":
                    task_ids_succeeded.add(tid)
                elif state == "FAILED":
                    task_ids_failed.add(tid)

            elif event.event_type in (
                EventType.TOOL_CALL_STARTED,
                EventType.TOOL_CALL_FINISHED,
            ):
                if event.event_type == EventType.TOOL_CALL_STARTED:
                    summary.tool_calls += 1

        summary.task_count = len(task_ids_started)
        summary.tasks_succeeded = len(task_ids_succeeded)
        summary.tasks_failed = len(task_ids_failed)

        if not summary.outcome:
            summary.outcome = "UNKNOWN"

        self._cache[run_id] = summary
        return summary

    def list_runs(self, run_ids: list[RunId]) -> list[EpisodeSummary]:
        """Summarize multiple runs."""
        return [self.summarize(rid) for rid in run_ids]

    def invalidate(self, run_id: RunId) -> None:
        """Remove a cached summary (e.g., if new events were appended)."""
        self._cache.pop(run_id, None)
