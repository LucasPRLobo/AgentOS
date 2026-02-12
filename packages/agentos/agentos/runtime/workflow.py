"""Linear workflow engine — sequential task execution with event emission."""

from __future__ import annotations

import logging

from agentos.core.errors import TaskExecutionError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.runtime.event_log import EventLog
from agentos.runtime.task import TaskNode, TaskState
from agentos.schemas.events import RunFinished, RunStarted, TaskFinished, TaskStarted

logger = logging.getLogger(__name__)


class Workflow:
    """An ordered sequence of tasks to execute linearly."""

    def __init__(self, name: str, tasks: list[TaskNode] | None = None) -> None:
        self.name = name
        self.tasks: list[TaskNode] = tasks or []

    def add_task(self, task: TaskNode) -> None:
        """Append a task to the workflow."""
        self.tasks.append(task)


class WorkflowExecutor:
    """Executes a Workflow linearly, emitting events for all state transitions."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log

    def run(self, workflow: Workflow, *, run_id: RunId | None = None) -> RunId:
        """Execute all tasks in order. Returns the run_id.

        On task failure, marks the task as FAILED, emits events, and raises
        TaskExecutionError. Remaining tasks stay PENDING.
        """
        rid = run_id or generate_run_id()
        seq = 0

        self._event_log.append(
            RunStarted(run_id=rid, seq=seq, payload={"workflow": workflow.name})
        )
        seq += 1

        for task in workflow.tasks:
            # Emit TaskStarted
            task.state = TaskState.RUNNING
            self._event_log.append(
                TaskStarted(
                    run_id=rid,
                    seq=seq,
                    payload={"task_id": task.id, "task_name": task.name},
                )
            )
            seq += 1

            try:
                task.result = task.callable()
                task.state = TaskState.SUCCEEDED
            except Exception as exc:
                task.state = TaskState.FAILED
                task.error = exc

                self._event_log.append(
                    TaskFinished(
                        run_id=rid,
                        seq=seq,
                        payload={
                            "task_id": task.id,
                            "task_name": task.name,
                            "state": task.state.value,
                            "error": str(exc),
                        },
                    )
                )
                seq += 1

                # Emit RunFinished with failure
                self._event_log.append(
                    RunFinished(
                        run_id=rid,
                        seq=seq,
                        payload={
                            "workflow": workflow.name,
                            "outcome": "FAILED",
                            "failed_task": task.name,
                        },
                    )
                )
                raise TaskExecutionError(
                    f"Task '{task.name}' failed: {exc}"
                ) from exc

            # Emit TaskFinished (success)
            self._event_log.append(
                TaskFinished(
                    run_id=rid,
                    seq=seq,
                    payload={
                        "task_id": task.id,
                        "task_name": task.name,
                        "state": task.state.value,
                    },
                )
            )
            seq += 1

        # Emit RunFinished (success)
        self._event_log.append(
            RunFinished(
                run_id=rid,
                seq=seq,
                payload={"workflow": workflow.name, "outcome": "SUCCEEDED"},
            )
        )

        return rid
