"""V1 Launch Criteria Verification — Phase 3 exit criteria.

Verifies:
1. Demo: 10/10 consecutive successful runs (DevOps pipeline)
2. Event log: complete, verified by replay
3. Budget: hard enforcement, verified by adversarial test
4. Security: Tier 1 capabilities enforced, adversarial tests pass
5. Workflows: all 4 example workflows pass
6. Replay: deterministic state reconstruction matches execution
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import yaml

from agentos.kernel.budget_manager import BudgetExceededError, BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.replayer import WorkflowReplayer
from agentos.kernel.seq import SeqCounter
from agentos.kernel.workspace import Workspace
from agentos.schemas.budget import BudgetDelta, BudgetSpec
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import (
    Confidence,
    Finding,
    TaskConfig,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition
from agentos.schemas.workspace import WorkspaceConfig
from agentos.security.enforcer import CapabilityDeniedError, CapabilityEnforcer
from agentos.validation.adversarial import (
    AdversarialValidator,
    AdversarialValidatorConfig,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXAMPLE_DIR = Path("examples")

ALL_EXAMPLES = [
    "linear_research.yaml",
    "parallel_analysis.yaml",
    "fanout_with_gate.yaml",
    "devops_pipeline.yaml",
]


def _run_example(yaml_file: str, tmp_path) -> dict:
    """Run an example workflow end-to-end, return result + replay snapshot."""
    raw = yaml.safe_load((EXAMPLE_DIR / yaml_file).read_text())
    wf = WorkflowDefinition.model_validate(raw)

    event_log = SQLiteEventLog()
    seq = SeqCounter()
    workflow_id = f"launch-{uuid.uuid4().hex[:8]}"

    agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
    budget_mgr = BudgetManager(
        workflow_spec=wf.budget, event_log=event_log, seq=seq,
        workflow_id=workflow_id, agent_specs=agent_specs,
    )
    gate_mgr = GateManager(event_log, seq, workflow_id)

    ws_root = tmp_path / workflow_id
    workspace = Workspace(
        WorkspaceConfig(root=str(ws_root)),
        event_log, seq, workflow_id=workflow_id,
    )
    workspace.ensure_root()

    def executor(name, config, predecessors=None):
        if config.type == "approval_gate":
            gid = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
            gate_mgr.resolve_gate(gid, GateResolution.APPROVED, reviewer="launch-test")
            return TaskStatus.SUCCEEDED

        agent_id = config.agent or "unassigned"
        budget_mgr.apply(agent_id, BudgetDelta(
            tokens=200, api_calls=1, time_seconds=0.02, cost_usd=0.005,
        ))
        workspace.write_file(
            f"{name}/output.md", f"# {name}\nStatus: succeeded\n",
            agent_id=agent_id, task_id=name,
        )
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

    # Replay for verification
    replayer = WorkflowReplayer(event_log)
    snap = replayer.replay(workflow_id)

    events = event_log.replay(workflow_id)
    event_types = {e.event_type for e in events}
    seqs = [e.seq for e in events]

    return {
        "status": result.status,
        "completed": len(result.completed_tasks),
        "failed": len(result.failed_tasks),
        "total_tasks": len(wf.tasks),
        "event_count": len(events),
        "event_types": event_types,
        "seqs_unique": len(set(seqs)) == len(seqs),
        "seqs_monotonic": seqs == sorted(seqs),
        "total_tokens": budget_mgr.total_usage.tokens_used,
        "files_produced": len(workspace.manifest),
        "snapshot_status": snap.status,
        "snapshot_succeeded": len(snap.succeeded_tasks),
        "snapshot_event_count": snap.event_count,
    }


# ---------------------------------------------------------------------------
# Criterion 1: 10/10 consecutive demo runs (DevOps pipeline)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestDemoConsistency:
    """10/10 consecutive successful runs of the DevOps pipeline."""

    @pytest.mark.parametrize("run_id", range(10))
    def test_devops_pipeline_run(self, run_id, tmp_path):
        r = _run_example("devops_pipeline.yaml", tmp_path)
        assert r["status"] == "succeeded"
        assert r["completed"] == r["total_tasks"]
        assert r["failed"] == 0
        assert r["seqs_unique"]
        assert r["seqs_monotonic"]


# ---------------------------------------------------------------------------
# Criterion 2: Event log complete, verified by replay
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestEventLogCompleteness:
    """Event log has all required event types and replay matches execution."""

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_all_event_types_present(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert EventType.WORKFLOW_STARTED in r["event_types"]
        assert EventType.WORKFLOW_COMPLETED in r["event_types"]
        assert EventType.TASK_STATE_CHANGED in r["event_types"]
        assert EventType.BUDGET_CONSUMED in r["event_types"]

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_replay_matches_execution(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert r["snapshot_status"] == "succeeded"
        assert r["snapshot_succeeded"] == r["completed"]
        assert r["snapshot_event_count"] == r["event_count"]

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_event_ordering(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert r["seqs_unique"], "Duplicate sequence numbers"
        assert r["seqs_monotonic"], "Events not in sequence order"


# ---------------------------------------------------------------------------
# Criterion 3: Budget hard enforcement
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestBudgetEnforcement:

    def test_token_budget_exceeded_halts(self):
        """Exceeding token budget raises BudgetExceededError."""
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=100),
            event_log=event_log, seq=seq, workflow_id="budget-halt",
        )
        budget_mgr.apply("ag1", BudgetDelta(tokens=50))
        with pytest.raises(BudgetExceededError, match="tokens"):
            budget_mgr.apply("ag1", BudgetDelta(tokens=60))

    def test_cost_budget_exceeded_halts(self):
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_cost_usd=1.00),
            event_log=event_log, seq=seq, workflow_id="cost-halt",
        )
        budget_mgr.apply("ag1", BudgetDelta(cost_usd=0.60))
        with pytest.raises(BudgetExceededError, match="cost_usd"):
            budget_mgr.apply("ag1", BudgetDelta(cost_usd=0.50))

    def test_budget_exceeded_emits_event(self):
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=100),
            event_log=event_log, seq=seq, workflow_id="budget-event",
        )
        with pytest.raises(BudgetExceededError):
            budget_mgr.apply("ag1", BudgetDelta(tokens=200))

        exceeded = event_log.query(event_type=EventType.BUDGET_EXCEEDED)
        assert len(exceeded) == 1
        assert exceeded[0].payload["resource"] == "tokens"

    def test_budget_exceeded_fails_dag_task(self):
        """Task that exceeds budget → workflow fails cleanly."""
        wf = WorkflowDefinition(
            name="budget-fail",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        budget_mgr = BudgetManager(
            workflow_spec=BudgetSpec(max_tokens=50),
            event_log=event_log, seq=seq, workflow_id="bf1",
        )

        def executor(name, config, predecessors=None):
            budget_mgr.apply("ag1", BudgetDelta(tokens=100))
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("bf1")
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# Criterion 4: Security — capability enforcement
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestSecurityEnforcement:

    def test_tool_allowlist_enforced(self):
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "sec1")

        enforcer.check_tool_call("ag1", "file_read", {"path": "test.py"})
        with pytest.raises(CapabilityDeniedError, match="tool not in allowlist"):
            enforcer.check_tool_call("ag1", "shell_exec", {"command": "rm -rf /"})

    def test_path_traversal_blocked(self):
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "sec2")

        with pytest.raises(CapabilityDeniedError, match="path traversal"):
            enforcer.check_tool_call("ag1", "file_read", {"path": "../../etc/passwd"})

    def test_domain_whitelist_enforced(self):
        event_log = SQLiteEventLog()
        seq = SeqCounter()
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:docs.python.org"),
            ],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "sec3")

        enforcer.check_tool_call("ag1", "web_search", {
            "query": "test", "domain": "docs.python.org",
        })
        with pytest.raises(CapabilityDeniedError, match="domain"):
            enforcer.check_tool_call("ag1", "web_search", {
                "query": "test", "url": "https://evil.com/steal",
            })

    def test_adversarial_validation_catches_bad_output(self):
        config = AdversarialValidatorConfig(
            validator_agent="v1", target_task="t1",
        )
        validator = AdversarialValidator(config)

        bad_output = TaskOutput(
            task_id="t1", agent_id="ag1",
            status=TaskStatus.FAILED, summary="", key_findings=[],
        )
        report = validator.validate(bad_output)
        assert report.result == ValidationResult.FAILED

    def test_model_separation_warning(self):
        warning = AdversarialValidator.check_model_separation(
            "claude-sonnet-4-6", "claude-sonnet-4-6",
        )
        assert warning is not None
        assert "same" in warning.lower() or "both" in warning.lower()


# ---------------------------------------------------------------------------
# Criterion 5: All example workflows pass
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestAllExamples:
    """All 4 example workflow YAMLs complete successfully."""

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_example_succeeds(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert r["status"] == "succeeded"
        assert r["failed"] == 0
        assert r["completed"] == r["total_tasks"]

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_example_produces_files(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert r["files_produced"] > 0

    @pytest.mark.parametrize("yaml_file", ALL_EXAMPLES)
    def test_example_tracks_budget(self, yaml_file, tmp_path):
        r = _run_example(yaml_file, tmp_path)
        assert r["total_tokens"] > 0
