"""DAG executor — topological scheduling with thread-pool dispatch."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.condition_evaluator import ConditionEvaluationError, evaluate_condition
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.kernel.state_machine import TaskStateMachine
from agentos.schemas.events import Event, EventType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition

if TYPE_CHECKING:
    from agentos.intelligence.finetune import FineTuneExporter
    from agentos.intelligence.knowledge_graph import KnowledgeGraph
    from agentos.intelligence.specialization import SpecializationTracker
    from agentos.kernel.channel_router import ChannelRouter
    from agentos.kernel.memory_store import MemoryStore
    from agentos.kernel.team_composer import TeamComposer

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Optional V2+ modules bundled for DAGExecutor.

    All fields default to None — fully backward-compatible with V1 code.
    """

    channel_router: ChannelRouter | None = None
    memory_store: MemoryStore | None = None
    knowledge_graph: KnowledgeGraph | None = None
    specialization_tracker: SpecializationTracker | None = None
    finetune_exporter: FineTuneExporter | None = None
    team_composer: TeamComposer | None = None


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
        context: ExecutionContext | None = None,
    ) -> None:
        self._workflow = workflow
        self._event_log = event_log
        self._seq = seq
        self._budget_manager = budget_manager
        self._task_executor = task_executor
        self._state_machine = TaskStateMachine(event_log, seq, workflow_id="")
        self._iteration_counts: dict[str, int] = {}  # task_name → current iteration
        self._ctx = context or ExecutionContext()

        # MutableDAG for runtime task insertion (populated in run/resume)
        self._dag: Any = None  # lazy import to avoid circular deps

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
        self._init_mutable_dag(tasks)
        self._init_channel_subscriptions(tasks)
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
        self._init_mutable_dag(tasks)
        self._init_channel_subscriptions(tasks)

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

    # -- MutableDAG + Channel initialization --------------------------------

    def _init_mutable_dag(self, tasks: dict[str, TaskConfig]) -> None:
        """Populate a MutableDAG from workflow tasks for runtime modifications."""
        from agentos.kernel.mutable_dag import MutableDAG

        self._dag = MutableDAG()
        for name in tasks:
            self._dag.add_node(name, {"config": tasks[name]})
        for name, config in tasks.items():
            for dep in config.depends_on:
                self._dag.add_edge(dep, name)

    def _init_channel_subscriptions(self, tasks: dict[str, TaskConfig]) -> None:
        """Register channel subscribers from task configs."""
        if self._ctx.channel_router is None:
            return
        for name, config in tasks.items():
            for channel in config.subscribes_to:
                try:
                    self._ctx.channel_router.register_subscriber(channel, name)
                except ValueError:
                    logger.warning("Task %s subscribes to unknown channel %s", name, channel)

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
                        # Evaluate conditional branches
                        config = tasks[name]
                        if config.conditions and output is not None:
                            self._evaluate_conditions(
                                workflow_id, name, config, output,
                                tasks, task_states, result,
                            )
                        # Post-task intelligence hooks
                        self._post_task_hooks(
                            workflow_id, name, config, output, tasks,
                            task_states, task_outputs, result,
                        )
                        # Channel publish
                        self._publish_to_channels(workflow_id, name, config, output)
                        # Spawn handling
                        self._handle_spawn_signal(
                            workflow_id, name, output, tasks, task_states,
                        )
                    elif status == TaskStatus.WAITING:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.WAITING
                        )
                        task_states[name] = TaskStatus.WAITING
                        result.waiting_tasks.append(name)
                    elif status == TaskStatus.FAILED:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.FAILED
                        )
                        task_states[name] = TaskStatus.FAILED
                        config = tasks[name]

                        # If this is a gate, try to retry predecessors
                        retried = False
                        if config.type in ("approval_gate", "input_gate"):
                            retried = self._handle_gate_rejection(
                                workflow_id, name, config, output,
                                tasks, task_states, task_outputs, result,
                            )
                        else:
                            # Check if this task itself has retry policy
                            retried = self._handle_retry(
                                workflow_id, name, config, output,
                                tasks, task_states, task_outputs, result,
                                trigger="validation_failed",
                            )

                        if not retried:
                            result.failed_tasks.append(name)
                            self._skip_dependents(
                                name, tasks, task_states, result, workflow_id,
                            )
                    else:
                        self._state_machine.transition(
                            name, TaskStatus.RUNNING, TaskStatus.FAILED
                        )
                        task_states[name] = TaskStatus.FAILED
                        result.failed_tasks.append(name)
                        self._skip_dependents(
                            name, tasks, task_states, result, workflow_id,
                        )

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

            # Inject channel messages as synthetic predecessor context
            predecessor_context = self._inject_channel_messages(
                name, config, predecessor_context,
            )

            # Inject cross-run memories as synthetic predecessor context
            predecessor_context = self._inject_memories(
                name, config, predecessor_context,
            )

            if config.type == "consultation":
                future = pool.submit(
                    self._run_consultation, name, config, predecessor_context,
                )
            else:
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
        skipped_task: str,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        result: WorkflowResult,
        workflow_id: str = "",
    ) -> None:
        """Recursively skip tasks that depend on a failed/skipped task."""
        for name, config in tasks.items():
            if task_states[name] != TaskStatus.PENDING:
                continue
            if skipped_task in config.depends_on:
                self._state_machine.transition(
                    name, TaskStatus.PENDING, TaskStatus.SKIPPED
                )
                task_states[name] = TaskStatus.SKIPPED
                result.skipped_tasks.append(name)
                self._skip_dependents(
                    name, tasks, task_states, result, workflow_id,
                )

    # -- Channel integration -----------------------------------------------

    def _inject_channel_messages(
        self,
        task_name: str,
        config: TaskConfig,
        predecessor_context: list[TaskOutput],
    ) -> list[TaskOutput]:
        """Inject received channel messages as synthetic TaskOutput entries."""
        if self._ctx.channel_router is None or not config.subscribes_to:
            return predecessor_context

        for channel in config.subscribes_to:
            try:
                messages = self._ctx.channel_router.receive(channel, task_name)
            except ValueError:
                continue
            for msg in messages:
                synthetic = TaskOutput(
                    task_id=f"channel:{channel}:{msg.sender_task_id}",
                    agent_id=msg.sender_agent_id,
                    status=TaskStatus.SUCCEEDED,
                    summary=f"Channel message from {msg.sender_task_id}: {str(msg.content)[:200]}",
                )
                predecessor_context = [synthetic] + predecessor_context

        return predecessor_context

    def _publish_to_channels(
        self,
        workflow_id: str,
        task_name: str,
        config: TaskConfig,
        output: TaskOutput | None,
    ) -> None:
        """Publish task output to configured channels."""
        if self._ctx.channel_router is None or not config.publishes_to or output is None:
            return

        from agentos.schemas.channel import ChannelMessage

        agent_id = config.agent or "unknown"
        for channel in config.publishes_to:
            try:
                self._ctx.channel_router.publish(ChannelMessage(
                    channel=channel,
                    sender_task_id=task_name,
                    sender_agent_id=agent_id,
                    content={
                        "summary": output.summary,
                        "findings": [f.finding for f in output.key_findings],
                    },
                ))
            except (ValueError, BufferError):
                logger.warning("Failed to publish to channel %s from task %s", channel, task_name)

    # -- Memory integration ------------------------------------------------

    def _inject_memories(
        self,
        task_name: str,
        config: TaskConfig,
        predecessor_context: list[TaskOutput],
    ) -> list[TaskOutput]:
        """Inject cross-run memories as a synthetic TaskOutput at front of context."""
        if self._ctx.memory_store is None:
            return predecessor_context

        from agentos.schemas.memory import MemoryQuery

        try:
            memories = self._ctx.memory_store.query(MemoryQuery(limit=5))
        except Exception:
            return predecessor_context

        if not memories:
            return predecessor_context

        memory_text = "; ".join(m.content[:100] for m in memories)
        synthetic = TaskOutput(
            task_id="cross-run-memory",
            agent_id="memory-store",
            status=TaskStatus.SUCCEEDED,
            summary=f"Cross-run memories: {memory_text}",
        )
        return [synthetic] + predecessor_context

    def _extract_and_store_memories(
        self,
        workflow_id: str,
        task_name: str,
        output: TaskOutput,
    ) -> None:
        """Extract memories from task output and store them."""
        if self._ctx.memory_store is None or output is None:
            return

        from agentos.kernel.memory_store import extract_memories_from_output

        findings = [
            {"content": f.finding, "confidence": 0.8, "tags": [task_name]}
            for f in output.key_findings
        ]
        memories = extract_memories_from_output(workflow_id, task_name, findings)
        for mem in memories:
            try:
                self._ctx.memory_store.store(mem)
            except Exception:
                logger.warning("Failed to store memory from task %s", task_name)

    # -- Post-task intelligence hooks --------------------------------------

    def _post_task_hooks(
        self,
        workflow_id: str,
        task_name: str,
        config: TaskConfig,
        output: TaskOutput | None,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        task_outputs: dict[str, TaskOutput],
        result: WorkflowResult,
    ) -> None:
        """Run post-task intelligence hooks (knowledge graph, specialization, fine-tune, memory)."""
        if output is None:
            return

        agent_id = config.agent or "unknown"

        # Knowledge Graph: record entities and observations
        if self._ctx.knowledge_graph is not None:
            try:
                for finding in output.key_findings:
                    entity = self._ctx.knowledge_graph.add_entity(
                        entity_type="finding",
                        name=finding.finding[:100],
                        properties={"task": task_name, "confidence": finding.confidence.value},
                        source_workflow=workflow_id,
                    )
                    self._ctx.knowledge_graph.add_observation(
                        entity_id=entity.entity_id,
                        content=finding.finding,
                        confidence={"high": 0.9, "medium": 0.7, "low": 0.4}.get(finding.confidence.value, 0.5),
                        source_workflow=workflow_id,
                    )
            except Exception:
                logger.warning("Knowledge graph hook failed for task %s", task_name)

        # Specialization: record performance
        if self._ctx.specialization_tracker is not None:
            try:
                from agentos.intelligence.specialization import PerformanceRecord

                cost = output.metrics.estimated_cost_usd if output.metrics else 0.0
                duration = output.metrics.execution_time_seconds if output.metrics else 0.0
                quality = len(output.key_findings) / 5.0 if output.key_findings else 0.5
                quality = min(1.0, quality)

                self._ctx.specialization_tracker.record_performance(PerformanceRecord(
                    agent_id=agent_id,
                    role=config.description[:50] if config.description else "default",
                    workflow_id=workflow_id,
                    quality_score=quality,
                    cost_usd=cost,
                    duration_seconds=duration,
                    success=output.status == TaskStatus.SUCCEEDED,
                ))
            except Exception:
                logger.warning("Specialization hook failed for task %s", task_name)

        # Fine-tuning: record task data
        if self._ctx.finetune_exporter is not None:
            try:
                from agentos.intelligence.finetune import TaskRecord

                self._ctx.finetune_exporter.add_record(TaskRecord(
                    task_id=task_name,
                    workflow_id=workflow_id,
                    system_prompt=config.description or "",
                    user_input=config.description or task_name,
                    assistant_output=output.summary or "",
                    quality_score=0.8 if output.status == TaskStatus.SUCCEEDED else 0.3,
                    approved=output.status == TaskStatus.SUCCEEDED,
                ))
            except Exception:
                logger.warning("Fine-tune hook failed for task %s", task_name)

        # Memory extraction
        self._extract_and_store_memories(workflow_id, task_name, output)

    # -- Team Composer spawn handling --------------------------------------

    def _handle_spawn_signal(
        self,
        workflow_id: str,
        task_name: str,
        output: TaskOutput | None,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
    ) -> None:
        """Check for spawn signals in output and handle via TeamComposer."""
        if self._ctx.team_composer is None or output is None:
            return

        for question in output.open_questions:
            if not question.startswith("SPAWN:"):
                continue

            parts = question.split(":", 2)
            if len(parts) < 3:
                continue

            archetype = parts[1]
            reason = parts[2]

            try:
                request = self._ctx.team_composer.request_spawn(
                    requesting_agent=output.agent_id,
                    archetype=archetype,
                    reason=reason,
                    task_description=reason,
                )

                if request.status.value == "approved":
                    provisioned = self._ctx.team_composer.provision(request.request_id)
                    spawned_id = provisioned["agent_id"]
                    spawned_task = f"spawned-{spawned_id}-{task_name}"

                    # Add to MutableDAG
                    if self._dag is not None:
                        self._dag.add_node(spawned_task, {"spawned": True})
                        self._dag.add_edge(task_name, spawned_task)

                    # Create a TaskConfig for the spawned task
                    new_config = TaskConfig(
                        name=spawned_task,
                        agent=spawned_id,
                        type="agent_task",
                        description=reason,
                        depends_on=[task_name],
                    )
                    tasks[spawned_task] = new_config
                    task_states[spawned_task] = TaskStatus.PENDING

                    # Emit events
                    self._event_log.append(Event(
                        event_type=EventType("agent.spawn.approved"),
                        workflow_id=workflow_id,
                        seq=self._seq.next(),
                        payload={
                            "request_id": request.request_id,
                            "archetype": archetype,
                            "spawned_agent": spawned_id,
                            "spawned_task": spawned_task,
                            "requested_by": output.agent_id,
                        },
                    ))

                    logger.info(
                        "Spawned agent %s (task %s) requested by %s",
                        spawned_id, spawned_task, output.agent_id,
                    )
            except (ValueError, KeyError) as exc:
                logger.warning("Spawn request failed for task %s: %s", task_name, exc)

    # -- Conditional branching ------------------------------------------------

    def _evaluate_conditions(
        self,
        workflow_id: str,
        task_name: str,
        config: TaskConfig,
        output: TaskOutput,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        result: WorkflowResult,
    ) -> None:
        """Evaluate conditional edges and skip/activate targets."""
        for cond in config.conditions:
            target = cond.target
            if target not in tasks:
                continue
            try:
                met = evaluate_condition(cond.expression, output)
            except ConditionEvaluationError:
                met = False

            self._event_log.append(Event(
                event_type=EventType.BRANCH_EVALUATED,
                workflow_id=workflow_id,
                seq=self._seq.next(),
                payload={
                    "task_id": task_name,
                    "target": target,
                    "expression": cond.expression,
                    "result": met,
                },
            ))

            if not met and task_states.get(target) == TaskStatus.PENDING:
                self._state_machine.transition(
                    target, TaskStatus.PENDING, TaskStatus.SKIPPED,
                )
                task_states[target] = TaskStatus.SKIPPED
                result.skipped_tasks.append(target)
                self._skip_dependents(
                    target, tasks, task_states, result, workflow_id,
                )

    # -- Revision loops -----------------------------------------------------

    def _handle_retry(
        self,
        workflow_id: str,
        task_name: str,
        config: TaskConfig,
        output: TaskOutput | None,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        task_outputs: dict[str, TaskOutput],
        result: WorkflowResult,
        *,
        trigger: str = "gate_rejected",
        feedback: str = "",
    ) -> bool:
        """Attempt to retry a task per its retry_policy.

        Returns True if the task was re-queued, False otherwise.
        """
        retry_policy = config.retry_policy
        if retry_policy is None or retry_policy.on != trigger:
            return False

        current_iter = self._iteration_counts.get(task_name, 1)
        if current_iter >= retry_policy.max_retries + 1:
            return False

        # Transition back to PENDING
        current_state = task_states[task_name]
        self._state_machine.transition(
            task_name, current_state, TaskStatus.PENDING,
        )
        task_states[task_name] = TaskStatus.PENDING
        self._iteration_counts[task_name] = current_iter + 1

        # Emit retry events
        self._event_log.append(Event(
            event_type=EventType.TASK_RETRIED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": task_name,
                "iteration": current_iter + 1,
                "trigger": trigger,
            },
        ))

        if feedback:
            self._event_log.append(Event(
                event_type=EventType.REVISION_FEEDBACK,
                workflow_id=workflow_id,
                seq=self._seq.next(),
                payload={
                    "task_id": task_name,
                    "feedback": feedback,
                    "iteration": current_iter + 1,
                },
            ))

        # Remove from failed_tasks if it was added
        if task_name in result.failed_tasks:
            result.failed_tasks.remove(task_name)
        # Remove from completed_tasks if retrying a succeeded task
        if task_name in result.completed_tasks:
            result.completed_tasks.remove(task_name)

        return True

    def _handle_gate_rejection(
        self,
        workflow_id: str,
        gate_name: str,
        gate_config: TaskConfig,
        gate_output: TaskOutput | None,
        tasks: dict[str, TaskConfig],
        task_states: dict[str, TaskStatus],
        task_outputs: dict[str, TaskOutput],
        result: WorkflowResult,
    ) -> bool:
        """Handle a gate rejection by retrying predecessor tasks.

        When a gate rejects, find predecessors with retry_policy on
        gate_rejected and retry them. Also re-queue the gate itself
        so it runs again after the retried predecessor.

        Returns True if at least one predecessor was retried.
        """
        retried_any = False
        feedback = ""
        if gate_output and gate_output.summary:
            feedback = gate_output.summary

        for dep_name in gate_config.depends_on:
            dep_config = tasks.get(dep_name)
            if dep_config is None:
                continue
            retried = self._handle_retry(
                workflow_id, dep_name, dep_config, task_outputs.get(dep_name),
                tasks, task_states, task_outputs, result,
                trigger="gate_rejected",
                feedback=feedback,
            )
            if retried:
                retried_any = True

        if retried_any:
            # Re-queue the gate itself so it runs again after predecessors
            self._state_machine.transition(
                gate_name, TaskStatus.FAILED, TaskStatus.PENDING,
            )
            task_states[gate_name] = TaskStatus.PENDING
            # Remove gate from failed_tasks if it was added
            if gate_name in result.failed_tasks:
                result.failed_tasks.remove(gate_name)

        return retried_any

    # -- Consultation tasks -------------------------------------------------

    def _run_consultation(
        self,
        name: str,
        config: TaskConfig,
        predecessor_context: list[TaskOutput],
    ) -> tuple[TaskStatus, TaskOutput | None]:
        """Run a consultation task: emit MESSAGE_SENT, execute, emit MESSAGE_RECEIVED."""
        workflow_id = self._state_machine._workflow_id

        self._event_log.append(Event(
            event_type=EventType.MESSAGE_SENT,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": name,
                "consult_agent": config.consult_agent or "",
                "question": config.consult_question or "",
            },
        ))

        status, output = self._run_task(name, config, predecessor_context)

        self._event_log.append(Event(
            event_type=EventType.MESSAGE_RECEIVED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={
                "task_id": name,
                "consult_agent": config.consult_agent or "",
                "has_response": output is not None,
            },
        ))

        return status, output

    # -- Event emission -----------------------------------------------------

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
                "tasks": {
                    name: {
                        "depends_on": list(config.depends_on),
                        "type": config.type,
                        "agent": config.agent or "",
                        "conditions": [
                            {"target": c.target, "expression": c.expression}
                            for c in (config.conditions or [])
                        ],
                    }
                    for name, config in self._workflow.tasks.items()
                },
            },
        ))

    def _emit_workflow_completed(self, workflow_id: str, status: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            seq=self._seq.next(),
            payload={"status": status},
        ))
