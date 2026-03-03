"""DAG executor — topological scheduling with thread-pool dispatch."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.state_machine import TaskStateMachine
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskConfig, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""

    workflow_id: str
    status: str  # "succeeded" | "failed"
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    skipped_tasks: list[str] = field(default_factory=list)


# Type for the callable that actually executes a task.
# Tests provide a stub; real adapters plug in later.
TaskExecutorFn = Callable[[str, TaskConfig], TaskStatus]


class DAGExecutor:
    """Executes a workflow DAG with topological scheduling.

    Validates the DAG (cycle detection, missing dependencies), then
    dispatches ready tasks to a thread pool respecting concurrency limits.
    All state transitions go through TaskStateMachine.
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        event_log: EventLog,
        seq: SeqCounter,
        budget_manager: BudgetManager,
        task_executor: TaskExecutorFn,
    ) -> None:
        self._workflow = workflow
        self._event_log = event_log
        self._seq = seq
        self._budget_manager = budget_manager
        self._task_executor = task_executor
        self._state_machine = TaskStateMachine(event_log, seq, workflow_id="")

    def run(self, workflow_id: str) -> WorkflowResult:
        """Execute the workflow DAG."""
        self._state_machine = TaskStateMachine(
            self._event_log, self._seq, workflow_id
        )
        tasks = self._workflow.tasks

        if not tasks:
            self._emit_workflow_started(workflow_id)
            self._emit_workflow_completed(workflow_id, "succeeded")
            return WorkflowResult(workflow_id=workflow_id, status="succeeded")

        self._validate_dag()
        self._emit_workflow_started(workflow_id)

        result = self._execute(workflow_id, tasks)

        status = "failed" if result.failed_tasks else "succeeded"
        result.status = status
        self._emit_workflow_completed(workflow_id, status)
        return result

    def _validate_dag(self) -> None:
        """Check for cycles and missing dependencies."""
        tasks = self._workflow.tasks
        task_names = set(tasks.keys())

        # Check missing dependencies
        for name, config in tasks.items():
            for dep in config.depends_on:
                if dep not in task_names:
                    raise ValueError(
                        f"Task {name!r} depends on {dep!r}, which does not exist"
                    )

        # Cycle detection via Kahn's algorithm
        adj: dict[str, list[str]] = defaultdict(list)
        in_deg: dict[str, int] = {name: 0 for name in task_names}
        for name, config in tasks.items():
            for dep in config.depends_on:
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
            raise ValueError("Workflow contains a cycle")

    def _execute(
        self,
        workflow_id: str,
        tasks: dict[str, TaskConfig],
    ) -> WorkflowResult:
        """Run tasks respecting dependencies and concurrency limits."""
        result = WorkflowResult(workflow_id=workflow_id, status="")
        task_states: dict[str, TaskStatus] = {
            name: TaskStatus.PENDING for name in tasks
        }
        max_workers = self._workflow.budget.max_concurrent_tasks

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # Map future -> task name
            active: dict[Future, str] = {}

            self._dispatch_ready(tasks, task_states, pool, active)

            while active:
                done, _ = wait(active.keys(), return_when=FIRST_COMPLETED)

                for future in done:
                    name = active.pop(future)
                    try:
                        status = future.result()
                    except Exception:
                        status = TaskStatus.FAILED

                    if status == TaskStatus.SUCCEEDED:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.SUCCEEDED
                        )
                        task_states[name] = TaskStatus.SUCCEEDED
                        result.completed_tasks.append(name)
                    else:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.FAILED
                        )
                        task_states[name] = TaskStatus.FAILED
                        result.failed_tasks.append(name)
                        self._skip_dependents(name, tasks, task_states, result)

                self._dispatch_ready(tasks, task_states, pool, active)

        return result

    def _dispatch_ready(
        self,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        pool: ThreadPoolExecutor,
        active: dict[Future, str],
    ) -> None:
        """Dispatch all tasks whose dependencies are satisfied."""
        active_names = set(active.values())
        for name, config in tasks.items():
            if task_states[name] != TaskStatus.PENDING:
                continue
            if name in active_names:
                continue
            deps_met = all(
                task_states.get(dep) == TaskStatus.SUCCEEDED
                for dep in config.depends_on
            )
            if not deps_met:
                continue

            self._state_machine.transition(
                name, TaskStatus.PENDING, TaskStatus.RUNNING
            )
            task_states[name] = TaskStatus.RUNNING

            future = pool.submit(self._task_executor, name, config)
            active[future] = name

    def _skip_dependents(
        self,
        failed_task: str,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        result: WorkflowResult,
    ) -> None:
        """Recursively skip tasks that depend on a failed task."""
        for name, config in tasks.items():
            if task_states[name] != TaskStatus.PENDING:
                continue
            if failed_task in config.depends_on:
                task_states[name] = TaskStatus.FAILED
                result.skipped_tasks.append(name)
                self._skip_dependents(name, tasks, task_states, result)

    def _emit_workflow_started(self, workflow_id: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={
                "workflow_name": self._workflow.name,
                "task_count": len(self._workflow.tasks),
            },
        ))

    def _emit_workflow_completed(self, workflow_id: str, status: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={"status": status},
        ))
