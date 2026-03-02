"""DAG workflow — dependency graph with topological scheduling."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

from agentos.core.errors import TaskExecutionError
from agentos.core.identifiers import RunId, generate_run_id
from agentos.runtime.event_log import EventLog
from agentos.runtime.task import TaskNode, TaskState
from agentos.schemas.events import RunFinished, RunStarted, TaskFinished, TaskStarted

logger = logging.getLogger(__name__)


class DAGWorkflow:
    """A directed acyclic graph of tasks with dependency edges."""

    def __init__(self, name: str, tasks: list[TaskNode] | None = None) -> None:
        self.name = name
        self.tasks: list[TaskNode] = tasks or []

    def add_task(self, task: TaskNode) -> None:
        """Add a task to the DAG."""
        self.tasks.append(task)

    def validate(self) -> None:
        """Validate the DAG: check for cycles and missing references.

        Raises TaskExecutionError on invalid graph.
        """
        task_set = set(id(t) for t in self.tasks)
        for task in self.tasks:
            for dep in task.depends_on:
                if id(dep) not in task_set:
                    raise TaskExecutionError(
                        f"Task '{task.name}' depends on '{dep.name}' which is not in the workflow"
                    )

        # Cycle detection via Kahn's algorithm
        in_degree: dict[int, int] = {id(t): 0 for t in self.tasks}
        adjacency: dict[int, list[int]] = {id(t): [] for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                adjacency[id(dep)].append(id(task))
                in_degree[id(task)] += 1

        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.tasks):
            raise TaskExecutionError(f"DAG '{self.name}' contains a cycle")

    def topological_order(self) -> list[TaskNode]:
        """Return tasks in a valid topological order (Kahn's algorithm)."""
        in_degree: dict[int, int] = {id(t): 0 for t in self.tasks}
        adjacency: dict[int, list[int]] = {id(t): [] for t in self.tasks}
        id_to_task: dict[int, TaskNode] = {id(t): t for t in self.tasks}

        for task in self.tasks:
            for dep in task.depends_on:
                adjacency[id(dep)].append(id(task))
                in_degree[id(task)] += 1

        queue = deque(
            tid
            for tid, deg in sorted(in_degree.items(), key=lambda x: x[0])
            if deg == 0
        )
        result: list[TaskNode] = []
        while queue:
            current = queue.popleft()
            result.append(id_to_task[current])
            for neighbor in sorted(adjacency[current]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result


class DAGExecutor:
    """Executes a DAGWorkflow respecting dependencies with controlled parallelism."""

    def __init__(self, event_log: EventLog, *, max_parallel: int = 1) -> None:
        self._event_log = event_log
        self._max_parallel = max_parallel

    def _next_seq(self, seq_counter: list[int], lock: threading.Lock) -> int:
        with lock:
            val = seq_counter[0]
            seq_counter[0] += 1
            return val

    def _execute_task(
        self,
        task: TaskNode,
        run_id: RunId,
        seq_counter: list[int],
        lock: threading.Lock,
    ) -> None:
        """Execute a single task, emitting events."""
        seq = self._next_seq(seq_counter, lock)
        task.state = TaskState.RUNNING
        self._event_log.append(
            TaskStarted(
                run_id=run_id,
                seq=seq,
                payload={"task_id": task.id, "task_name": task.name},
            )
        )

        try:
            task.result = task.callable()
            task.state = TaskState.SUCCEEDED
        except Exception as exc:
            task.state = TaskState.FAILED
            task.error = exc

        seq = self._next_seq(seq_counter, lock)
        payload: dict[str, str] = {
            "task_id": task.id,
            "task_name": task.name,
            "state": task.state.value,
        }
        if task.error is not None:
            payload["error"] = str(task.error)

        self._event_log.append(
            TaskFinished(run_id=run_id, seq=seq, payload=payload)
        )

    def run(self, dag: DAGWorkflow, *, run_id: RunId | None = None) -> RunId:
        """Execute the DAG respecting dependencies.

        Tasks with no unmet dependencies can run in parallel up to max_parallel.
        On any task failure, no new tasks are started; already running tasks
        are allowed to finish. Then TaskExecutionError is raised.
        """
        dag.validate()

        rid = run_id or generate_run_id()
        seq_counter = [0]
        lock = threading.Lock()

        self._event_log.append(
            RunStarted(
                run_id=rid,
                seq=self._next_seq(seq_counter, lock),
                payload={"workflow": dag.name},
            )
        )

        if not dag.tasks:
            self._event_log.append(
                RunFinished(
                    run_id=rid,
                    seq=self._next_seq(seq_counter, lock),
                    payload={"workflow": dag.name, "outcome": "SUCCEEDED"},
                )
            )
            return rid

        pending = set(id(t) for t in dag.tasks)
        id_to_task = {id(t): t for t in dag.tasks}
        failed_tasks: list[TaskNode] = []

        with ThreadPoolExecutor(max_workers=self._max_parallel) as pool:
            futures: dict[Future[None], TaskNode] = {}

            while pending or futures:
                # Submit ready tasks (only if no failures yet)
                if not failed_tasks:
                    ready = [
                        id_to_task[tid]
                        for tid in list(pending)
                        if id_to_task[tid].is_ready
                    ]
                    for task in ready:
                        pending.discard(id(task))
                        fut = pool.submit(
                            self._execute_task, task, rid, seq_counter, lock
                        )
                        futures[fut] = task

                if not futures:
                    break

                # Wait for at least one future to complete
                done_futures = [f for f in list(futures) if f.done()]
                if not done_futures:
                    time.sleep(0.001)
                    continue

                for fut in done_futures:
                    task = futures.pop(fut)
                    if task.state == TaskState.FAILED:
                        failed_tasks.append(task)

        if failed_tasks:
            self._event_log.append(
                RunFinished(
                    run_id=rid,
                    seq=self._next_seq(seq_counter, lock),
                    payload={
                        "workflow": dag.name,
                        "outcome": "FAILED",
                        "failed_tasks": [t.name for t in failed_tasks],
                    },
                )
            )
            first_fail = failed_tasks[0]
            raise TaskExecutionError(
                f"Task '{first_fail.name}' failed: {first_fail.error}"
            )

        self._event_log.append(
            RunFinished(
                run_id=rid,
                seq=self._next_seq(seq_counter, lock),
                payload={"workflow": dag.name, "outcome": "SUCCEEDED"},
            )
        )
        return rid
