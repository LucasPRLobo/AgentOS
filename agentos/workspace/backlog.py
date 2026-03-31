"""BacklogManager — task backlog for the workspace runtime.

Manages the lifecycle of tasks: create, claim, execute, review, complete.
Handles dependencies, chaining, dynamic priority, and stall detection.
All mutations are event-logged.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.workspace.schemas import BacklogTask, BacklogTaskStatus, _uuid, _utc_now_iso


_TERMINAL = {BacklogTaskStatus.DONE, BacklogTaskStatus.CANCELLED}


class BacklogManager:
    """Manages the task backlog for a workspace."""

    def __init__(self, event_log: EventLog, seq: SeqCounter, workflow_id: str) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._tasks: dict[str, BacklogTask] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_task(self, task: BacklogTask) -> str:
        with self._lock:
            self._tasks[task.task_id] = task
            # Auto-block if dependencies exist and are not yet done
            if task.depends_on:
                all_met = all(
                    self._tasks.get(dep) and self._tasks[dep].status == BacklogTaskStatus.DONE
                    for dep in task.depends_on
                )
                if not all_met:
                    task.status = BacklogTaskStatus.BLOCKED
            # Register this task in the blocks list of its dependencies
            for dep_id in task.depends_on:
                dep = self._tasks.get(dep_id)
                if dep and task.task_id not in dep.blocks:
                    dep.blocks.append(task.task_id)

        self._emit(EventType.BACKLOG_TASK_CREATED, {
            "task_id": task.task_id, "title": task.title,
            "created_by": task.created_by, "status": task.status,
            "priority": task.priority,
        })
        return task.task_id

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    def claim_task(self, task_id: str, participant_id: str) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status != BacklogTaskStatus.OPEN:
                raise ValueError(
                    f"Cannot claim task {task_id}: status is {task.status}"
                )
            task.status = BacklogTaskStatus.CLAIMED
            task.assigned_to = participant_id
            task.claimed_at = _utc_now_iso()

        self._emit(EventType.BACKLOG_TASK_CLAIMED, {
            "task_id": task_id, "participant_id": participant_id,
        })

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def start_task(self, task_id: str) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status not in (BacklogTaskStatus.CLAIMED, BacklogTaskStatus.REVISION_NEEDED):
                raise ValueError(f"Cannot start task {task_id}: status is {task.status}")
            task.status = BacklogTaskStatus.IN_PROGRESS

        self._emit(EventType.BACKLOG_TASK_STARTED, {"task_id": task_id})

    # ------------------------------------------------------------------
    # Submit for review
    # ------------------------------------------------------------------

    def submit_for_review(self, task_id: str, output: dict) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status != BacklogTaskStatus.IN_PROGRESS:
                raise ValueError(f"Cannot submit task {task_id}: status is {task.status}")
            task.status = BacklogTaskStatus.IN_REVIEW
            task.output = output
            task.review_count += 1

        self._emit(EventType.BACKLOG_TASK_SUBMITTED, {
            "task_id": task_id, "review_count": task.review_count,
        })

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def approve_task(self, task_id: str, reviewer_id: str) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status != BacklogTaskStatus.IN_REVIEW:
                raise ValueError(f"Cannot approve task {task_id}: status is {task.status}")
            task.status = BacklogTaskStatus.DONE
            task.completed_at = _utc_now_iso()

        self._emit(EventType.BACKLOG_TASK_APPROVED, {
            "task_id": task_id, "reviewer_id": reviewer_id,
        })

        # Unblock dependents and chain
        self.unblock_dependents(task_id)
        self.chain_next(task_id)

    # ------------------------------------------------------------------
    # Direct completion (skip review)
    # ------------------------------------------------------------------

    def complete_task(self, task_id: str, output: dict | None = None) -> None:
        """Mark a task as done directly, skipping the review step."""
        with self._lock:
            task = self._get(task_id)
            if task.status in _TERMINAL:
                raise ValueError(f"Task {task_id} is already {task.status}")
            task.status = BacklogTaskStatus.DONE
            task.completed_at = _utc_now_iso()
            if output is not None:
                task.output = output

        self._emit(EventType.BACKLOG_TASK_APPROVED, {
            "task_id": task_id, "reviewer_id": "direct",
        })
        self.unblock_dependents(task_id)
        self.chain_next(task_id)

    # ------------------------------------------------------------------
    # Revision
    # ------------------------------------------------------------------

    def request_revision(self, task_id: str, feedback: str) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status != BacklogTaskStatus.IN_REVIEW:
                raise ValueError(f"Cannot request revision for {task_id}: status is {task.status}")
            task.status = BacklogTaskStatus.REVISION_NEEDED

        self._emit(EventType.BACKLOG_TASK_REVISION, {
            "task_id": task_id, "feedback": feedback[:200],
        })

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel_task(self, task_id: str, reason: str) -> None:
        with self._lock:
            task = self._get(task_id)
            if task.status in _TERMINAL:
                raise ValueError(f"Task {task_id} is already {task.status}")
            task.status = BacklogTaskStatus.CANCELLED

        self._emit(EventType.BACKLOG_TASK_CANCELLED, {
            "task_id": task_id, "reason": reason[:200],
        })

    # ------------------------------------------------------------------
    # Dependencies
    # ------------------------------------------------------------------

    def check_dependencies(self, task_id: str) -> bool:
        """True if all dependencies are DONE."""
        with self._lock:
            task = self._get(task_id)
            return all(
                self._tasks.get(dep) and self._tasks[dep].status == BacklogTaskStatus.DONE
                for dep in task.depends_on
            )

    def unblock_dependents(self, task_id: str) -> list[str]:
        """Unblock tasks that were waiting on task_id. Returns unblocked IDs."""
        unblocked: list[str] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return []
            for blocked_id in task.blocks:
                blocked = self._tasks.get(blocked_id)
                if blocked is None or blocked.status != BacklogTaskStatus.BLOCKED:
                    continue
                # Check if ALL dependencies are now met
                all_met = all(
                    self._tasks.get(d) and self._tasks[d].status == BacklogTaskStatus.DONE
                    for d in blocked.depends_on
                )
                if all_met:
                    blocked.status = BacklogTaskStatus.OPEN
                    unblocked.append(blocked_id)

        for uid in unblocked:
            self._emit(EventType.BACKLOG_TASK_UNBLOCKED, {"task_id": uid})
        return unblocked

    # ------------------------------------------------------------------
    # Chaining
    # ------------------------------------------------------------------

    def chain_next(self, task_id: str) -> str | None:
        """Auto-create the next_task if defined. Returns new task ID or None."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.next_task is None:
                return None
            next_data = dict(task.next_task)

        next_task = BacklogTask(
            title=next_data.get("title", "Follow-up"),
            description=next_data.get("description", ""),
            created_by="chain:" + task_id,
            suggested_for=next_data.get("suggested_for"),
            required_role=next_data.get("required_role"),
            depends_on=[task_id],
            priority=next_data.get("priority", "normal"),
        )
        return self.create_task(next_task)

    # ------------------------------------------------------------------
    # Priority
    # ------------------------------------------------------------------

    def recompute_priorities(self) -> None:
        """Compute dynamic priority from dependency structure."""
        with self._lock:
            for task in self._tasks.values():
                if task.status in _TERMINAL:
                    continue
                downstream_count = self._count_downstream(task.task_id, set())
                manual_weight = {"low": 1, "normal": 2, "high": 3, "critical": 4}.get(
                    task.priority, 2
                )
                task.computed_priority = manual_weight + downstream_count * 0.5

    def _count_downstream(self, task_id: str, visited: set) -> int:
        """Count tasks downstream of task_id (recursive, caller holds lock)."""
        if task_id in visited:
            return 0
        visited.add(task_id)
        task = self._tasks.get(task_id)
        if task is None:
            return 0
        count = len(task.blocks)
        for bid in task.blocks:
            count += self._count_downstream(bid, visited)
        return count

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> BacklogTask:
        with self._lock:
            return self._get(task_id)

    def get_all_tasks(self) -> list[BacklogTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_open_tasks(self, role: str | None = None) -> list[BacklogTask]:
        with self._lock:
            tasks = [t for t in self._tasks.values() if t.status == BacklogTaskStatus.OPEN]
            if role:
                tasks = [t for t in tasks if t.required_role == role or t.required_role is None]
            return sorted(tasks, key=lambda t: t.computed_priority or 0, reverse=True)

    def get_ready_tasks(self) -> list[BacklogTask]:
        """Open tasks with all dependencies met."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status == BacklogTaskStatus.OPEN
            ]

    def get_tasks_for(self, participant_id: str) -> list[BacklogTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.assigned_to == participant_id]

    def get_blocked_tasks(self) -> list[BacklogTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.status == BacklogTaskStatus.BLOCKED]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def flag_long_tasks(self) -> list[str]:
        with self._lock:
            return [
                t.task_id for t in self._tasks.values()
                if t.estimated_minutes and t.estimated_minutes > 35
                and t.status not in _TERMINAL
            ]

    def flag_stalled_tasks(self, max_stall_cycles: int = 2) -> list[str]:
        with self._lock:
            return [
                t.task_id for t in self._tasks.values()
                if t.stall_count >= max_stall_cycles
                and t.status not in _TERMINAL
            ]

    def increment_stall(self, task_id: str) -> None:
        with self._lock:
            task = self._get(task_id)
            task.stall_count += 1

    def reset_stall(self, task_id: str) -> None:
        with self._lock:
            task = self._get(task_id)
            task.stall_count = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, task_id: str) -> BacklogTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")
        return task

    def _emit(self, event_type: EventType, payload: dict) -> None:
        self._event_log.append(Event(
            event_type=event_type,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload=payload,
        ))
