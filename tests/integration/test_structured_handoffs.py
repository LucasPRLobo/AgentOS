"""Integration tests — structured handoffs between tasks via DAG executor.

Verifies that downstream tasks receive predecessor TaskOutput context
through the DAG executor's handoff mechanism.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

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
    TaskConfig,
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)
from agentos.schemas.workflow import WorkflowDefinition


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_output(task_id: str, agent_id: str, summary: str, findings=None) -> TaskOutput:
    return TaskOutput(
        task_id=task_id,
        agent_id=agent_id,
        status=TaskStatus.SUCCEEDED,
        summary=summary,
        key_findings=findings or [],
    )


# ---------------------------------------------------------------------------
# Tests: Linear chain handoffs
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLinearHandoff:
    """A → B → C: each task receives its predecessor's output."""

    def test_linear_chain_passes_context(self, event_log, seq):
        wf = WorkflowDefinition(
            name="linear-handoff",
            tasks={
                "research": TaskConfig(name="research", agent="ag1"),
                "review": TaskConfig(name="review", agent="ag1", depends_on=["research"]),
                "implement": TaskConfig(name="implement", agent="ag1", depends_on=["review"]),
            },
            agents={"ag1": {}},
        )

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h1",
        )

        received_context: dict[str, list[TaskOutput]] = {}

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            received_context[name] = predecessors
            output = _make_output(name, "ag1", f"Done: {name}")
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h1")

        assert result.status == "succeeded"

        # research has no predecessors
        assert received_context["research"] == []

        # review receives research's output
        assert len(received_context["review"]) == 1
        assert received_context["review"][0].task_id == "research"
        assert received_context["review"][0].summary == "Done: research"

        # implement receives review's output
        assert len(received_context["implement"]) == 1
        assert received_context["implement"][0].task_id == "review"

    def test_outputs_stored_in_result(self, event_log, seq):
        wf = WorkflowDefinition(
            name="output-test",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h2",
        )

        def executor(name: str, config: TaskConfig, predecessors=None):
            return TaskStatus.SUCCEEDED, _make_output(name, "ag1", f"Output: {name}")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h2")

        assert "a" in result.task_outputs
        assert "b" in result.task_outputs
        assert result.task_outputs["a"].summary == "Output: a"
        assert result.task_outputs["b"].summary == "Output: b"


# ---------------------------------------------------------------------------
# Tests: Fan-in handoffs
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFanInHandoff:
    """A + B → C: merge task receives outputs from both predecessors."""

    def test_fanin_receives_both_predecessors(self, event_log, seq):
        wf = WorkflowDefinition(
            name="fanin-handoff",
            tasks={
                "analysis_a": TaskConfig(name="analysis_a", agent="ag1"),
                "analysis_b": TaskConfig(name="analysis_b", agent="ag2"),
                "synthesis": TaskConfig(
                    name="synthesis", agent="ag1",
                    depends_on=["analysis_a", "analysis_b"],
                ),
            },
            agents={"ag1": {}, "ag2": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h3",
        )

        received_context: dict[str, list[TaskOutput]] = {}
        lock = threading.Lock()

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            with lock:
                received_context[name] = predecessors
            finding = Finding(finding=f"Result from {name}", confidence=Confidence.HIGH)
            output = _make_output(name, config.agent or "ag1", f"Done: {name}", [finding])
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h3")

        assert result.status == "succeeded"

        # Synthesis receives both predecessors
        synth_ctx = received_context["synthesis"]
        assert len(synth_ctx) == 2
        ctx_ids = {c.task_id for c in synth_ctx}
        assert ctx_ids == {"analysis_a", "analysis_b"}

        # Both predecessors have findings
        for ctx in synth_ctx:
            assert len(ctx.key_findings) == 1
            assert ctx.key_findings[0].confidence == Confidence.HIGH

    def test_fanin_findings_accessible(self, event_log, seq):
        """Downstream task can read specific findings from predecessors."""
        wf = WorkflowDefinition(
            name="findings-test",
            tasks={
                "tech": TaskConfig(name="tech", agent="ag1"),
                "market": TaskConfig(name="market", agent="ag2"),
                "report": TaskConfig(
                    name="report", agent="ag1",
                    depends_on=["tech", "market"],
                ),
            },
            agents={"ag1": {}, "ag2": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h4",
        )

        captured_findings: list[Finding] = []
        lock = threading.Lock()

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            if name == "report":
                with lock:
                    for ctx in predecessors:
                        captured_findings.extend(ctx.key_findings)

            findings = []
            if name == "tech":
                findings = [Finding(finding="Python is trending", confidence=Confidence.HIGH)]
            elif name == "market":
                findings = [Finding(finding="TAM is $10B", confidence=Confidence.MEDIUM)]

            output = _make_output(name, config.agent or "ag1", f"Done: {name}", findings)
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h4")

        assert result.status == "succeeded"
        assert len(captured_findings) == 2
        finding_texts = {f.finding for f in captured_findings}
        assert "Python is trending" in finding_texts
        assert "TAM is $10B" in finding_texts


# ---------------------------------------------------------------------------
# Tests: Gate tasks in handoff chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestGateHandoff:
    """Gates don't produce TaskOutput but shouldn't break the chain."""

    def test_gate_doesnt_break_handoff(self, event_log, seq):
        """A → gate → B: B receives A's output (gate has no output)."""
        wf = WorkflowDefinition(
            name="gate-handoff",
            tasks={
                "research": TaskConfig(name="research", agent="ag1"),
                "review": TaskConfig(
                    name="review", type="approval_gate",
                    depends_on=["research"], prompt="Approve?",
                ),
                "implement": TaskConfig(
                    name="implement", agent="ag1",
                    depends_on=["review"],
                ),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h5",
        )
        gate_mgr = GateManager(event_log, seq, "h5")

        received_context: dict[str, list[TaskOutput]] = {}

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            received_context[name] = predecessors

            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="test")
                return TaskStatus.SUCCEEDED, None

            output = _make_output(name, "ag1", f"Done: {name}")
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h5")

        assert result.status == "succeeded"

        # implement depends on review (gate), which depends on research
        # Gate has no output, so implement gets empty predecessors from the gate
        # But research output IS in task_outputs
        assert "research" in result.task_outputs
        assert "review" not in result.task_outputs  # gate returned None

    def test_gate_with_output_forwarded(self, event_log, seq):
        """Gate that produces output → downstream receives it."""
        wf = WorkflowDefinition(
            name="gate-output-handoff",
            tasks={
                "work": TaskConfig(name="work", agent="ag1"),
                "gate": TaskConfig(
                    name="gate", type="approval_gate",
                    depends_on=["work"], prompt="OK?",
                ),
                "final": TaskConfig(name="final", agent="ag1", depends_on=["gate"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h6",
        )

        received_context: dict[str, list[TaskOutput]] = {}

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            received_context[name] = predecessors

            if config.type == "approval_gate":
                output = _make_output(name, "system", "Gate approved with feedback")
                return TaskStatus.SUCCEEDED, output

            return TaskStatus.SUCCEEDED, _make_output(name, "ag1", f"Done: {name}")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h6")

        assert result.status == "succeeded"
        assert len(received_context["final"]) == 1
        assert received_context["final"][0].summary == "Gate approved with feedback"


# ---------------------------------------------------------------------------
# Tests: Fan-out + fan-in (diamond)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDiamondHandoff:
    """A → (B, C) → D: D receives both B and C outputs."""

    def test_diamond_handoff(self, event_log, seq):
        wf = WorkflowDefinition(
            name="diamond",
            tasks={
                "root": TaskConfig(name="root", agent="ag1"),
                "left": TaskConfig(name="left", agent="ag1", depends_on=["root"]),
                "right": TaskConfig(name="right", agent="ag2", depends_on=["root"]),
                "merge": TaskConfig(
                    name="merge", agent="ag1",
                    depends_on=["left", "right"],
                ),
            },
            agents={"ag1": {}, "ag2": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h7",
        )

        received_context: dict[str, list[TaskOutput]] = {}
        lock = threading.Lock()

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            with lock:
                received_context[name] = predecessors
            return TaskStatus.SUCCEEDED, _make_output(name, config.agent or "ag1", f"Done: {name}")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h7")

        assert result.status == "succeeded"

        # root has no predecessors
        assert received_context["root"] == []

        # left and right each receive root's output
        assert len(received_context["left"]) == 1
        assert received_context["left"][0].task_id == "root"
        assert len(received_context["right"]) == 1
        assert received_context["right"][0].task_id == "root"

        # merge receives both left and right
        merge_ctx = received_context["merge"]
        assert len(merge_ctx) == 2
        ctx_ids = {c.task_id for c in merge_ctx}
        assert ctx_ids == {"left", "right"}


# ---------------------------------------------------------------------------
# Tests: Open questions forwarding
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestOpenQuestionsHandoff:
    """Downstream tasks can see open questions from predecessors."""

    def test_open_questions_forwarded(self, event_log, seq):
        wf = WorkflowDefinition(
            name="questions",
            tasks={
                "research": TaskConfig(name="research", agent="ag1"),
                "followup": TaskConfig(name="followup", agent="ag1", depends_on=["research"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h8",
        )

        captured_questions: list[str] = []

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            if name == "followup":
                for ctx in predecessors:
                    captured_questions.extend(ctx.open_questions)

            output = TaskOutput(
                task_id=name, agent_id="ag1",
                status=TaskStatus.SUCCEEDED,
                summary=f"Done: {name}",
                open_questions=["What about edge cases?"] if name == "research" else [],
            )
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h8")

        assert result.status == "succeeded"
        assert captured_questions == ["What about edge cases?"]


# ---------------------------------------------------------------------------
# Tests: Legacy executor compatibility
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLegacyExecutor:
    """Executors that return just TaskStatus still work."""

    def test_legacy_status_only_return(self, event_log, seq):
        wf = WorkflowDefinition(
            name="legacy",
            tasks={
                "a": TaskConfig(name="a", agent="ag1"),
                "b": TaskConfig(name="b", agent="ag1", depends_on=["a"]),
            },
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="h9",
        )

        def executor(name: str, config: TaskConfig, predecessors=None):
            return TaskStatus.SUCCEEDED  # No tuple, no TaskOutput

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("h9")

        assert result.status == "succeeded"
        assert result.task_outputs == {}  # No outputs collected


# ---------------------------------------------------------------------------
# Tests: Real workflow YAML handoffs
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRealWorkflowHandoffs:
    """Structured handoffs with real example YAML files."""

    def test_linear_research_handoff(self, event_log, seq):
        raw = yaml.safe_load(open("examples/linear_research.yaml").read())
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="real1",
        )
        gate_mgr = GateManager(event_log, seq, "real1")

        received_context: dict[str, list[TaskOutput]] = {}

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            received_context[name] = predecessors

            if config.type == "approval_gate":
                gate_id = gate_mgr.create_gate(name, GateType.APPROVAL, config.prompt)
                gate_mgr.resolve_gate(gate_id, GateResolution.APPROVED, reviewer="test")
                return TaskStatus.SUCCEEDED, None

            output = _make_output(name, config.agent or "ag1", f"Completed: {name}")
            return TaskStatus.SUCCEEDED, output

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("real1")

        assert result.status == "succeeded"
        # implement depends on review_gate, which depends on research
        # review_gate returns None, so implement gets no predecessor outputs from it
        assert received_context["research"] == []
        assert len(received_context["review_gate"]) == 1  # receives research
        assert received_context["review_gate"][0].task_id == "research"

    def test_parallel_analysis_handoff(self, event_log, seq):
        raw = yaml.safe_load(open("examples/parallel_analysis.yaml").read())
        wf = WorkflowDefinition.model_validate(raw)

        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq, workflow_id="real2",
        )

        received_context: dict[str, list[TaskOutput]] = {}
        lock = threading.Lock()

        def executor(name: str, config: TaskConfig, predecessors=None):
            predecessors = predecessors or []
            with lock:
                received_context[name] = predecessors
            return TaskStatus.SUCCEEDED, _make_output(name, config.agent or "ag1", f"Done: {name}")

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("real2")

        assert result.status == "succeeded"
        # synthesis depends on tech_analysis + market_analysis
        synth_ctx = received_context["synthesis"]
        assert len(synth_ctx) == 2
        ctx_ids = {c.task_id for c in synth_ctx}
        assert ctx_ids == {"tech_analysis", "market_analysis"}
