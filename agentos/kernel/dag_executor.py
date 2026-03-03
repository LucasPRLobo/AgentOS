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
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""

    workflow_id: str
    status: str  # "succeeded" | "failed" | "paused"
    completed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    skipped_tasks: list[str] = field(default_factory=list)
    waiting_tasks: list[str] = field(default_factory=list)
    task_outputs: dict[str, TaskOutput] = field(default_factory=dict)


# Type for the callable that actually executes a task.
# Receives task name, config, and predecessor TaskOutputs.
# Tests provide a stub; real adapters plug in later.
TaskExecutorFn = Callable[[str, TaskConfig, list[TaskOutput]], TaskStatus]


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

        if result.waiting_tasks:
            result.status = "paused"
            self._emit_workflow_paused(workflow_id)
        else:
            status = "failed" if result.failed_tasks else "succeeded"
            result.status = status
            self._emit_workflow_completed(workflow_id, status)
        return result

    def resume(self, workflow_id: str) -> WorkflowResult:
        """Resume a paused workflow by re-deriving state from the event log.

        Checks for resolved gates and continues DAG execution from where
        it left off. Task outputs are reconstructed from persisted events.
        """
        self._state_machine = TaskStateMachine(
            self._event_log, self._seq, workflow_id
        )
        tasks = self._workflow.tasks

        # Re-derive task states from event log
        task_states: dict[str, TaskStatus] = {}
        for name in tasks:
            task_states[name] = self._state_machine.get_state(name)

        # Re-derive task outputs from TASK_OUTPUT_PRODUCED events
        task_outputs: dict[str, TaskOutput] = {}
        output_events = self._event_log.query(
            workflow_id=workflow_id,
            event_type=EventType.TASK_OUTPUT_PRODUCED,
        )
        for event in output_events:
            tid = event.payload.get("task_id", "")
            if tid in tasks:
                task_outputs[tid] = TaskOutput.model_validate(
                    event.payload["output"]
                )

        # Check for resolved gates — transition WAITING → RUNNING
        gate_resolved_ids: set[str] = set()
        for event in self._event_log.query(
            workflow_id=workflow_id,
            event_type=EventType.GATE_RESOLVED,
        ):
            gate_resolved_ids.add(event.payload.get("gate_id", ""))

        for name, state in task_states.items():
            if state != TaskStatus.WAITING:
                continue
            # Find the gate for this waiting task
            gate_events = self._event_log.query(
                workflow_id=workflow_id,
                event_type=EventType.GATE_WAITING,
            )
            for ge in gate_events:
                if ge.payload.get("task_id") == name:
                    gid = ge.payload.get("gate_id", "")
                    if gid in gate_resolved_ids:
                        self._state_machine.transition(
                            name, TaskStatus.WAITING, TaskStatus.RUNNING
                        )
                        task_states[name] = TaskStatus.RUNNING
                        # Immediately mark as succeeded (gate is resolved)
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.SUCCEEDED
                        )
                        task_states[name] = TaskStatus.SUCCEEDED
                    break

        # Build result from current state
        result = WorkflowResult(workflow_id=workflow_id, status="")
        for name, state in task_states.items():
            if state == TaskStatus.SUCCEEDED:
                result.completed_tasks.append(name)
            elif state == TaskStatus.FAILED:
                result.failed_tasks.append(name)
            elif state == TaskStatus.WAITING:
                result.waiting_tasks.append(name)

        # Continue executing any newly-ready tasks
        result = self._execute_from_state(
            workflow_id, tasks, task_states, task_outputs, result
        )

        if result.waiting_tasks:
            result.status = "paused"
            self._emit_workflow_paused(workflow_id)
        else:
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
        task_outputs: dict[str, TaskOutput] = {}
        return self._execute_from_state(
            workflow_id, tasks, task_states, task_outputs, result
        )

    def _execute_from_state(
        self,
        workflow_id: str,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        task_outputs: dict[str, TaskOutput],
        result: WorkflowResult,
    ) -> WorkflowResult:
        """Run tasks from a given state, respecting dependencies."""
        max_workers = self._workflow.budget.max_concurrent_tasks

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            active: dict[Future, str] = {}

            self._dispatch_ready(tasks, task_states, task_outputs, pool, active)

            while active:
                done, _ = wait(active.keys(), return_when=FIRST_COMPLETED)

                for future in done:
                    name = active.pop(future)
                    try:
                        status, output = future.result()
                    except Exception:
                        status = TaskStatus.FAILED
                        output = None

                    if status == TaskStatus.SUCCEEDED:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.SUCCEEDED
                        )
                        task_states[name] = TaskStatus.SUCCEEDED
                        result.completed_tasks.append(name)
                        if output is not None:
                            task_outputs[name] = output
                            self._emit_task_output(workflow_id, name, output)
                    elif status == TaskStatus.WAITING:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.WAITING
                        )
                        task_states[name] = TaskStatus.WAITING
                        result.waiting_tasks.append(name)
                    else:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.FAILED
                        )
                        task_states[name] = TaskStatus.FAILED
                        result.failed_tasks.append(name)
                        self._skip_dependents(name, tasks, task_states, result)

                self._dispatch_ready(tasks, task_states, task_outputs, pool, active)

        result.task_outputs = task_outputs
        return result

    def _dispatch_ready(
        self,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        task_outputs: dict[str, TaskOutput],
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

            # Gather predecessor outputs for structured handoffs
            predecessor_context = [
                task_outputs[dep]
                for dep in config.depends_on
                if dep in task_outputs
            ]

            future = pool.submit(self._run_task, name, config, predecessor_context)
            active[future] = name

    def _run_task(
        self,
        name: str,
        config: TaskConfig,
        predecessor_context: list[TaskOutput],
    ) -> tuple[TaskStatus, TaskOutput | None]:
        """Execute a task and return (status, optional TaskOutput)."""
        result = self._task_executor(name, config, predecessor_context)
        if isinstance(result, tuple):
            # Executor returned (TaskStatus, TaskOutput)
            return result
        # Legacy: executor returned just TaskStatus
        return result, None

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

    def _emit_task_output(
        self, workflow_id: str, task_name: str, output: TaskOutput,
    ) -> None:
        """Persist a task's structured output as an event."""
        self._event_log.append(Event(
            event_type=EventType.TASK_OUTPUT_PRODUCED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": task_name,
                "output": output.model_dump(mode="json"),
            },
        ))

    def _emit_workflow_paused(self, workflow_id: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={"status": "paused"},
        ))

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
