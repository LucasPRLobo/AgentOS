"""E2E test — public demo scenario, 10 consecutive runs.

Sprint 8 demo checklist (from DEVELOPMENT_PLAN.md):
- Agent A produces structured manifest conforming to schema
- Gate pauses execution and presents output
- User approves via CLI
- Agent B receives structured context
- Event log captures every action
- Budget tracking accurate
"""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import (
    Confidence,
    Finding,
    RetryPolicy,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition


# ---------------------------------------------------------------------------
# Demo workflow: two agents + approval gate + structured handoffs
# ---------------------------------------------------------------------------

def _demo_workflow() -> WorkflowDefinition:
    """Standard demo workflow: researcher → gate → implementer."""
    return WorkflowDefinition(
        name="public-demo",
        budget=BudgetSpec(max_tokens=50000, max_cost_usd=5.00),
        tasks={
            "research": TaskConfig(
                name="research",
                agent="researcher",
                description="Analyze the codebase and identify key issues.",
            ),
            "review_gate": TaskConfig(
                name="review_gate",
                type="approval_gate",
                depends_on=["research"],
                prompt="Review research findings before implementation.",
            ),
            "implement": TaskConfig(
                name="implement",
                agent="implementer",
                description="Implement fixes based on research findings.",
                depends_on=["review_gate"],
            ),
        },
        agents={
            "researcher": {
                "adapter": "tier1",
                "role": "Analyze and identify issues",
                "budget": {"max_tokens": 20000},
            },
            "implementer": {
                "adapter": "tier2_claude_code",
                "role": "Implement fixes",
                "budget": {"max_tokens": 30000},
            },
        },
    )


def _run_demo(run_id: int) -> dict:
    """Execute one full demo run: run → pause → resolve → resume.

    Returns a dict with all verification data.
    """
    wf = _demo_workflow()
    workflow_id = f"demo-run-{run_id}"

    event_log = SQLiteEventLog()
    seq = SeqCounter()
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs={
            name: agent.budget for name, agent in wf.agents.items()
        },
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)
    gate_ids: dict[str, str] = {}
    received_context: dict[str, list[TaskOutput]] = {}

    def executor(name, config, predecessors=None):
        predecessors = predecessors or []
        received_context[name] = predecessors

        if config.type == "approval_gate":
            gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
            gate_ids[name] = gid
            return TaskStatus.WAITING, None

        agent_id = config.agent or "unknown"

        # Simulate agent work
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500, api_calls=1, time_seconds=1.0, cost_usd=0.01,
        ))

        output = TaskOutput(
            task_id=name,
            agent_id=agent_id,
            status=TaskStatus.SUCCEEDED,
            summary=f"Agent {agent_id} completed {name}",
            key_findings=[
                Finding(
                    finding=f"Finding from {name}",
                    confidence=Confidence.HIGH,
                    sources=[f"{name}/analysis.md"],
                ),
            ],
            open_questions=[f"Should we refactor {name}?"],
        )
        return TaskStatus.SUCCEEDED, output

    dag = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=executor,
    )

    # Phase 1: Run → should pause at gate
    r1 = dag.run(workflow_id)
    assert r1.status == "paused", f"Run {run_id}: expected paused, got {r1.status}"

    # Phase 2: Resolve gate (simulates user CLI approve)
    gate_mgr.resolve_gate(
        gate_ids["review_gate"],
        GateResolution.APPROVED,
        reviewer="demo-user",
        feedback="Approved for run " + str(run_id),
    )

    # Phase 3: Resume → should complete
    r2 = dag.resume(workflow_id)
    assert r2.status == "succeeded", f"Run {run_id}: expected succeeded, got {r2.status}"

    # Collect verification data
    all_events = event_log.replay(workflow_id)
    return {
        "run_id": run_id,
        "result": r2,
        "events": all_events,
        "budget_mgr": budget_mgr,
        "gate_ids": gate_ids,
        "received_context": received_context,
        "event_log": event_log,
        "workflow_id": workflow_id,
    }


# ---------------------------------------------------------------------------
# Test class: 10 consecutive runs
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestPublicDemo10Runs:
    """Phase 2 exit criterion: public demo works 10/10 times."""

    @pytest.mark.parametrize("run_id", range(10))
    def test_demo_run(self, run_id):
        data = _run_demo(run_id)

        # --- Checklist item: Agent A produces structured manifest ---
        assert "research" in data["result"].task_outputs
        research_output = data["result"].task_outputs["research"]
        assert research_output.task_id == "research"
        assert research_output.agent_id == "researcher"
        assert len(research_output.key_findings) >= 1
        assert research_output.key_findings[0].confidence == Confidence.HIGH
        assert len(research_output.open_questions) >= 1

        # --- Checklist item: Gate paused execution ---
        gate_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.GATE_WAITING,
        )
        assert len(gate_events) == 1
        assert gate_events[0].payload["prompt"] == "Review research findings before implementation."

        # --- Checklist item: User approved via CLI (simulated) ---
        resolve_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.GATE_RESOLVED,
        )
        assert len(resolve_events) == 1
        assert resolve_events[0].payload["resolution"] == "approved"
        assert resolve_events[0].payload["reviewer"] == "demo-user"

        # --- Checklist item: Agent B receives structured context ---
        # implement's predecessors come from the task_outputs dict
        # which was reconstructed on resume
        assert "implement" in data["result"].task_outputs
        implement_output = data["result"].task_outputs["implement"]
        assert implement_output.agent_id == "implementer"

        # --- Checklist item: Event log captures every action ---
        event_types = [e.event_type for e in data["events"]]
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.TASK_STATE_CHANGED in event_types
        assert EventType.GATE_WAITING in event_types
        assert EventType.GATE_RESOLVED in event_types
        assert EventType.BUDGET_CONSUMED in event_types
        assert EventType.TASK_OUTPUT_PRODUCED in event_types
        assert EventType.WORKFLOW_COMPLETED in event_types

        # --- Checklist item: Budget tracking accurate ---
        total = data["budget_mgr"].total_usage
        assert total.tokens_used == 1000  # 500 per agent × 2
        assert total.api_calls_made == 2
        assert total.cost_usd == pytest.approx(0.02)

        # Per-agent breakdown
        researcher_usage = data["budget_mgr"].usage_for("researcher")
        implementer_usage = data["budget_mgr"].usage_for("implementer")
        assert researcher_usage.tokens_used == 500
        assert implementer_usage.tokens_used == 500

        # All tasks completed
        assert set(data["result"].completed_tasks) == {
            "research", "review_gate", "implement",
        }


# ---------------------------------------------------------------------------
# Test: Full event log completeness
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestEventLogCompleteness:
    """Verify the event log tells the full story of a demo run."""

    def test_event_sequence_is_monotonic(self):
        data = _run_demo(100)
        seqs = [e.seq for e in data["events"]]
        assert seqs == sorted(seqs), "Events not in seq order"
        assert len(seqs) == len(set(seqs)), "Duplicate seq values"

    def test_all_task_transitions_recorded(self):
        data = _run_demo(101)
        state_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.TASK_STATE_CHANGED,
        )
        transitions = {
            (e.payload["task_id"], e.payload["to_state"])
            for e in state_events
        }

        # research: pending → running → succeeded
        assert ("research", "running") in transitions
        assert ("research", "succeeded") in transitions

        # review_gate: pending → running → waiting (during run)
        assert ("review_gate", "running") in transitions
        assert ("review_gate", "waiting") in transitions
        # Then on resume: waiting → running → succeeded
        assert ("review_gate", "succeeded") in transitions

        # implement: pending → running → succeeded (during resume)
        assert ("implement", "running") in transitions
        assert ("implement", "succeeded") in transitions

    def test_output_events_for_agent_tasks(self):
        data = _run_demo(102)
        output_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.TASK_OUTPUT_PRODUCED,
        )
        output_task_ids = {e.payload["task_id"] for e in output_events}
        # Agent tasks produce outputs, gate does not
        assert "research" in output_task_ids
        assert "implement" in output_task_ids


# ---------------------------------------------------------------------------
# V1.5 collaborative demo: revision loops with gate rejection
# ---------------------------------------------------------------------------

def _collaborative_workflow() -> WorkflowDefinition:
    """Workflow with revision loop: implement → review_gate → deploy."""
    return WorkflowDefinition(
        name="collaborative-demo",
        budget=BudgetSpec(max_tokens=100000, max_cost_usd=10.00),
        tasks={
            "implement": TaskConfig(
                name="implement",
                agent="developer",
                description="Implement the feature. Address revision feedback if provided.",
                retry_policy=RetryPolicy(max_retries=2, on="gate_rejected"),
            ),
            "review_gate": TaskConfig(
                name="review_gate",
                type="approval_gate",
                depends_on=["implement"],
                prompt="Review the implementation. Approve or reject with feedback.",
            ),
            "deploy": TaskConfig(
                name="deploy",
                agent="deployer",
                description="Deploy the approved feature.",
                depends_on=["review_gate"],
            ),
        },
        agents={
            "developer": {
                "adapter": "tier1",
                "role": "Implement features",
                "budget": {"max_tokens": 40000},
            },
            "deployer": {
                "adapter": "tier1",
                "role": "Deploy releases",
                "budget": {"max_tokens": 20000},
            },
        },
    )


def _run_collaborative_demo(run_id: int) -> dict:
    """Execute one collaborative demo: gate rejects once, implement retries, gate approves."""
    wf = _collaborative_workflow()
    workflow_id = f"collab-run-{run_id}"

    event_log = SQLiteEventLog()
    seq = SeqCounter()
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget,
        event_log=event_log,
        seq=seq,
        workflow_id=workflow_id,
        agent_specs={name: agent.budget for name, agent in wf.agents.items()},
    )

    gate_call_count: dict[str, int] = {}

    def executor(name, config, predecessors=None):
        predecessors = predecessors or []

        if config.type == "approval_gate":
            gate_call_count[name] = gate_call_count.get(name, 0) + 1
            if gate_call_count[name] == 1:
                # First call: reject
                output = TaskOutput(
                    task_id=name, agent_id="gate",
                    status=TaskStatus.FAILED,
                    summary="Rejected: needs error handling improvements.",
                )
                return TaskStatus.FAILED, output
            # Subsequent calls: approve
            output = TaskOutput(
                task_id=name, agent_id="gate",
                status=TaskStatus.SUCCEEDED,
                summary="Approved: implementation looks good.",
            )
            return TaskStatus.SUCCEEDED, output

        agent_id = config.agent or "unknown"
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=500, api_calls=1, time_seconds=1.0, cost_usd=0.01,
        ))

        output = TaskOutput(
            task_id=name, agent_id=agent_id,
            status=TaskStatus.SUCCEEDED,
            summary=f"Agent {agent_id} completed {name}",
            key_findings=[
                Finding(
                    finding=f"Finding from {name}",
                    confidence=Confidence.HIGH,
                ),
            ],
        )
        return TaskStatus.SUCCEEDED, output

    dag = DAGExecutor(
        workflow=wf, event_log=event_log, seq=seq,
        budget_manager=budget_mgr, task_executor=executor,
    )
    result = dag.run(workflow_id)

    all_events = event_log.replay(workflow_id)
    return {
        "run_id": run_id,
        "result": result,
        "events": all_events,
        "budget_mgr": budget_mgr,
        "event_log": event_log,
        "workflow_id": workflow_id,
    }


# ---------------------------------------------------------------------------
# Test class: V1.5 collaborative demo — 10 consecutive runs
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestCollaborativeDemo10Runs:
    """V1.5 exit criterion: revision loops work 10/10 times."""

    @pytest.mark.parametrize("run_id", range(10))
    def test_collaborative_run(self, run_id):
        data = _run_collaborative_demo(run_id)

        # Workflow succeeds after retry
        assert data["result"].status == "succeeded"
        assert set(data["result"].completed_tasks) == {
            "implement", "review_gate", "deploy",
        }
        assert len(data["result"].failed_tasks) == 0

        # Verify TASK_RETRIED event
        event_types = [e.event_type for e in data["events"]]
        assert EventType.TASK_RETRIED in event_types

        retry_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.TASK_RETRIED,
        )
        assert len(retry_events) == 1
        assert retry_events[0].payload["task_id"] == "implement"
        assert retry_events[0].payload["iteration"] == 2

        # Verify REVISION_FEEDBACK event
        assert EventType.REVISION_FEEDBACK in event_types

        feedback_events = data["event_log"].query(
            workflow_id=data["workflow_id"],
            event_type=EventType.REVISION_FEEDBACK,
        )
        assert len(feedback_events) == 1
        assert feedback_events[0].payload["task_id"] == "implement"
        assert "Rejected" in feedback_events[0].payload["feedback"]

        # Budget: implement ran twice (500×2) + deploy (500) = 1500
        total = data["budget_mgr"].total_usage
        assert total.tokens_used == 1500
        assert total.api_calls_made == 3
        assert total.cost_usd == pytest.approx(0.03)
