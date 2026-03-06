"""End-to-end tests — Aider adapter in full demo workflows with mocked subprocess."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
import yaml

from agentos.adapters.tier2_aider import AiderAdapter
from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.gate_manager import GateManager
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetDelta
from agentos.schemas.gate import GateResolution, GateType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition

pytestmark = pytest.mark.e2e


def _make_aider_mock(manifest_data: dict | None = None):
    """Create a mock subprocess.run that simulates Aider."""
    def mock_run(cmd, *, cwd=None, capture_output=True, text=True, timeout=None):
        if cwd and manifest_data is not None:
            (Path(cwd) / "manifest.json").write_text(json.dumps(manifest_data))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    return mock_run


class TestAiderE2EDemo:
    """E2E demo: Aider implement → gate → Tier 1 stub review."""

    def test_aider_code_review_workflow(self, tmp_path):
        """Full workflow matching examples/aider_code_review.yaml pattern."""
        wf_yaml = {
            "name": "e2e-aider-code-review",
            "version": "1.0",
            "budget": {"max_tokens": 100000, "max_cost_usd": 5.0},
            "agents": {
                "implementer": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Implementer"},
                "reviewer": {"adapter": "tier1", "model": "claude-sonnet-4-6", "role": "Reviewer"},
            },
            "tasks": {
                "implement": {
                    "name": "implement",
                    "agent": "implementer",
                    "description": "Implement the email validator module.",
                },
                "review_gate": {
                    "name": "review_gate",
                    "type": "approval_gate",
                    "depends_on": ["implement"],
                    "prompt": "Review implementation before code review.",
                },
                "review": {
                    "name": "review",
                    "agent": "reviewer",
                    "description": "Review the implementation for correctness.",
                    "depends_on": ["review_gate"],
                },
            },
        }

        wf = WorkflowDefinition.model_validate(wf_yaml)
        event_log = SQLiteEventLog(str(tmp_path / "e2e.db"))
        seq = SeqCounter()
        workflow_id = f"e2e-aider-{uuid.uuid4().hex[:8]}"

        agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id, agent_specs=agent_specs,
        )
        gate_mgr = GateManager(event_log, seq, workflow_id)

        mock_sub = _make_aider_mock({
            "summary": "Implemented email validator with regex.",
            "findings": [{"finding": "Uses RFC 5322 regex", "confidence": "high"}],
            "open_questions": ["Should we validate MX records?"],
        })
        aider = AiderAdapter(budget_mgr, "implementer", run_subprocess=mock_sub)

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []

            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(task_name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="e2e")
                output = TaskOutput(
                    task_id=task_name, agent_id="gate",
                    status=TaskStatus.SUCCEEDED, summary="Approved.",
                )
                return TaskStatus.SUCCEEDED, output

            agent_id = config.agent or "unassigned"

            if agent_id == "implementer":
                ws = tmp_path / task_name
                ws.mkdir(exist_ok=True)
                output = asyncio.run(aider.execute_task(
                    task_description=config.description,
                    role="Implementer",
                    workspace=ws,
                    predecessor_context=predecessors,
                    allowed_tools=[],
                ))
                output.task_id = task_name
                return output.status, output

            # Tier 1 stub
            output = TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.SUCCEEDED,
                summary="Code review complete. No critical issues found.",
            )
            return TaskStatus.SUCCEEDED, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"implement", "review_gate", "review"}

        # Verify structured output from Aider task was captured
        impl_output = result.task_outputs.get("implement")
        assert impl_output is not None
        assert impl_output.status == TaskStatus.SUCCEEDED
        assert len(impl_output.key_findings) == 1
        assert impl_output.open_questions == ["Should we validate MX records?"]


class TestAiderMixedE2E:
    """E2E: mixed Aider + stub in parallel."""

    def test_parallel_mixed_adapters(self, tmp_path):
        """Three parallel tasks: two Aider, one stub."""
        wf_yaml = {
            "name": "e2e-mixed-parallel",
            "version": "1.0",
            "budget": {"max_tokens": 200000, "max_cost_usd": 10.0},
            "agents": {
                "coder_a": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Coder A"},
                "coder_b": {"adapter": "tier2_aider", "model": "gpt-4o", "role": "Coder B"},
                "analyst": {"adapter": "tier1", "role": "Analyst"},
            },
            "tasks": {
                "plan": {
                    "name": "plan",
                    "agent": "analyst",
                    "description": "Create implementation plan.",
                },
                "impl_a": {
                    "name": "impl_a",
                    "agent": "coder_a",
                    "description": "Implement module A.",
                    "depends_on": ["plan"],
                },
                "impl_b": {
                    "name": "impl_b",
                    "agent": "coder_b",
                    "description": "Implement module B.",
                    "depends_on": ["plan"],
                },
                "merge": {
                    "name": "merge",
                    "agent": "analyst",
                    "description": "Merge and verify.",
                    "depends_on": ["impl_a", "impl_b"],
                },
            },
        }

        wf = WorkflowDefinition.model_validate(wf_yaml)
        event_log = SQLiteEventLog(str(tmp_path / "mixed.db"))
        seq = SeqCounter()
        workflow_id = f"e2e-mixed-{uuid.uuid4().hex[:8]}"

        agent_specs = {name: agent.budget for name, agent in wf.agents.items()}
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log,
            seq=seq, workflow_id=workflow_id, agent_specs=agent_specs,
        )

        mock_sub = _make_aider_mock({
            "summary": "Module implemented.", "findings": [], "open_questions": [],
        })
        adapters = {
            "coder_a": AiderAdapter(budget_mgr, "coder_a", run_subprocess=mock_sub),
            "coder_b": AiderAdapter(budget_mgr, "coder_b", run_subprocess=mock_sub),
        }

        def task_executor(task_name, config, predecessors=None):
            predecessors = predecessors or []
            agent_id = config.agent or "unassigned"

            if agent_id in adapters:
                ws = tmp_path / task_name
                ws.mkdir(exist_ok=True)
                output = asyncio.run(adapters[agent_id].execute_task(
                    task_description=config.description,
                    role=wf.agents[agent_id].role,
                    workspace=ws,
                    predecessor_context=predecessors,
                    allowed_tools=[],
                ))
                output.task_id = task_name
                return output.status, output

            output = TaskOutput(
                task_id=task_name, agent_id=agent_id,
                status=TaskStatus.SUCCEEDED, summary=f"Stub: {task_name}",
            )
            return TaskStatus.SUCCEEDED, output

        executor = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=task_executor,
        )
        result = executor.run(workflow_id)

        assert result.status == "succeeded"
        assert set(result.completed_tasks) == {"plan", "impl_a", "impl_b", "merge"}


class TestAiderWorkflowVerification:
    """Verify the aider_code_review.yaml example passes verification."""

    def test_example_verifies(self):
        """examples/aider_code_review.yaml passes workflow verification."""
        from agentos.validation.workflow_verifier import WorkflowVerifier

        yaml_path = Path(__file__).parent.parent.parent / "examples" / "aider_code_review.yaml"
        raw = yaml.safe_load(yaml_path.read_text())
        wf = WorkflowDefinition.model_validate(raw)

        verifier = WorkflowVerifier()
        report = verifier.verify(wf)
        assert not report.errors, f"Verification errors: {report.errors}"
