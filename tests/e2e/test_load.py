"""Load tests — concurrent task execution at scale.

Exercises the DAG executor with 5, 10, and 20 parallel tasks to verify:
- All tasks complete successfully
- Events are ordered (monotonic seq)
- No seq collisions
- Budget tracked correctly across all agents
- Thread pool handles concurrent dispatch
"""

from __future__ import annotations

import uuid

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.replayer import WorkflowReplayer
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_parallel_workflow(n_tasks: int, max_concurrent: int = 10) -> WorkflowDefinition:
    """Build a workflow with n_tasks independent parallel tasks."""
    tasks = {}
    agents = {}
    for i in range(n_tasks):
        task_name = f"task_{i:03d}"
        agent_name = f"agent_{i:03d}"
        tasks[task_name] = TaskConfig(name=task_name, agent=agent_name)
        agents[agent_name] = {}

    return WorkflowDefinition(
        name=f"load-{n_tasks}",
        tasks=tasks,
        agents=agents,
        budget=BudgetSpec(
            max_tokens=n_tasks * 1000,
            max_cost_usd=n_tasks * 0.10,
            max_concurrent_tasks=max_concurrent,
        ),
    )


def _build_diamond_workflow(fan_width: int) -> WorkflowDefinition:
    """Build a diamond: root → N parallel → merge."""
    tasks = {"root": TaskConfig(name="root", agent="coordinator")}
    agents = {"coordinator": {}, "merger": {}}

    for i in range(fan_width):
        name = f"worker_{i:03d}"
        agent = f"agent_{i:03d}"
        tasks[name] = TaskConfig(name=name, agent=agent, depends_on=["root"])
        agents[agent] = {}

    tasks["merge"] = TaskConfig(
        name="merge", agent="merger",
        depends_on=[f"worker_{i:03d}" for i in range(fan_width)],
    )

    return WorkflowDefinition(
        name=f"diamond-{fan_width}",
        tasks=tasks,
        agents=agents,
        budget=BudgetSpec(
            max_tokens=(fan_width + 2) * 1000,
            max_cost_usd=(fan_width + 2) * 0.10,
            max_concurrent_tasks=min(fan_width, 10),
        ),
    )


def _run_load_test(wf: WorkflowDefinition) -> dict:
    """Execute a workflow and return comprehensive results."""
    event_log = SQLiteEventLog()
    seq = SeqCounter()
    workflow_id = f"load-{uuid.uuid4().hex[:8]}"

    budget_mgr = BudgetManager(
        workflow_spec=wf.budget, event_log=event_log, seq=seq,
        workflow_id=workflow_id,
    )

    def executor(name, config, predecessors=None):
        agent_id = config.agent or "unknown"
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=100, api_calls=1, time_seconds=0.01, cost_usd=0.005,
        ))
        output = TaskOutput(
            task_id=name, agent_id=agent_id,
            status=TaskStatus.SUCCEEDED,
            summary=f"Completed {name}",
            key_findings=[Finding(
                finding=f"Result from {name}",
                confidence=Confidence.HIGH,
            )],
        )
        return TaskStatus.SUCCEEDED, output

    dag = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=executor,
    )
    result = dag.run(workflow_id)

    events = event_log.replay(workflow_id)
    seqs = [e.seq for e in events]

    # Verify replay
    replayer = WorkflowReplayer(event_log)
    snap = replayer.replay(workflow_id)

    return {
        "status": result.status,
        "completed": len(result.completed_tasks),
        "failed": len(result.failed_tasks),
        "event_count": len(events),
        "seqs": seqs,
        "seqs_unique": len(set(seqs)) == len(seqs),
        "seqs_monotonic": seqs == sorted(seqs),
        "total_tokens": budget_mgr.total_usage.tokens_used,
        "total_tasks": len(wf.tasks),
        "snapshot_status": snap.status,
        "snapshot_succeeded": len(snap.succeeded_tasks),
        "snapshot_event_count": snap.event_count,
        "task_outputs": len(result.task_outputs),
    }


# ---------------------------------------------------------------------------
# Tests: Parallel load
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestParallelLoad:
    """Fan-out N independent tasks running concurrently."""

    def test_5_parallel_tasks(self):
        wf = _build_parallel_workflow(5, max_concurrent=5)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 5
        assert r["failed"] == 0
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]
        assert r["total_tokens"] == 500
        assert r["task_outputs"] == 5

    def test_10_parallel_tasks(self):
        wf = _build_parallel_workflow(10, max_concurrent=10)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 10
        assert r["failed"] == 0
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]
        assert r["total_tokens"] == 1000

    def test_20_parallel_tasks(self):
        wf = _build_parallel_workflow(20, max_concurrent=10)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 20
        assert r["failed"] == 0
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]
        assert r["total_tokens"] == 2000

    def test_20_tasks_limited_concurrency(self):
        """20 tasks but only 3 concurrent slots — still completes."""
        wf = _build_parallel_workflow(20, max_concurrent=3)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 20


# ---------------------------------------------------------------------------
# Tests: Diamond load
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestDiamondLoad:
    """Root → N parallel workers → merge."""

    def test_diamond_5(self):
        wf = _build_diamond_workflow(5)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 7  # root + 5 workers + merge
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]

    def test_diamond_10(self):
        wf = _build_diamond_workflow(10)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 12  # root + 10 workers + merge

    def test_diamond_20(self):
        wf = _build_diamond_workflow(20)
        r = _run_load_test(wf)
        assert r["status"] == "succeeded"
        assert r["completed"] == 22  # root + 20 workers + merge
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]
        assert r["total_tokens"] == 2200  # 22 tasks × 100


# ---------------------------------------------------------------------------
# Tests: Replay consistency at scale
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestReplayConsistency:
    """Verify replay reconstructs correct state at scale."""

    def test_replay_matches_result_20_parallel(self):
        wf = _build_parallel_workflow(20, max_concurrent=10)
        r = _run_load_test(wf)
        assert r["snapshot_status"] == "succeeded"
        assert r["snapshot_succeeded"] == 20
        assert r["snapshot_event_count"] == r["event_count"]

    def test_replay_matches_result_diamond_10(self):
        wf = _build_diamond_workflow(10)
        r = _run_load_test(wf)
        assert r["snapshot_status"] == "succeeded"
        assert r["snapshot_succeeded"] == 12

    def test_event_types_present_at_scale(self):
        """All expected event types present in a 20-task run."""
        wf = _build_parallel_workflow(20, max_concurrent=10)
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        workflow_id = "types-check"

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id=workflow_id,
        )

        def executor(name, config, predecessors=None):
            budget_mgr.apply(config.agent, BudgetDelta(tokens=100, api_calls=1))
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        dag.run(workflow_id)

        events = event_log.replay(workflow_id)
        types = {e.event_type for e in events}
        assert EventType.WORKFLOW_STARTED in types
        assert EventType.WORKFLOW_COMPLETED in types
        assert EventType.TASK_STATE_CHANGED in types
        assert EventType.BUDGET_CONSUMED in types
