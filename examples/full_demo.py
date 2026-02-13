"""AgentOS Full Demo — exercises all 5 phases of the kernel.

Usage:
    python examples/full_demo.py
"""

from __future__ import annotations

from pydantic import BaseModel

from agentos.core.errors import BudgetExceededError, PermissionDeniedError
from agentos.core.identifiers import generate_run_id
from agentos.eval.eval_case import EvalCase, EvalOutcome, EvalResult
from agentos.eval.runner import EvalRunner, EvalSuite
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.concurrency import ConcurrencyLimiter
from agentos.governance.permissions import (
    PermissionPolicy,
    PermissionRule,
    PermissionsEngine,
    PolicyAction,
)
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.integrity.hashing import canonical_json, hash_model
from agentos.memory.context_pack import ContextPackBuilder
from agentos.memory.episodic import EpisodicStore
from agentos.memory.semantic import Fact, Provenance, SemanticStore
from agentos.observability.replay import ReplayEngine, ReplayMode
from agentos.runtime.dag import DAGExecutor, DAGWorkflow
from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.task import TaskNode
from agentos.runtime.workflow import Workflow, WorkflowExecutor
from agentos.schemas.budget import BudgetSpec
from agentos.tools.base import BaseTool, SideEffect
from agentos.tools.registry import ToolRegistry


# ── Shared tool definitions ──────────────────────────────────────────────────

class AddInput(BaseModel):
    a: int
    b: int

class AddOutput(BaseModel):
    result: int

class AddTool(BaseTool):
    @property
    def name(self) -> str:
        return "add"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AddInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return AddOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, AddInput)
        return AddOutput(result=input_data.a + input_data.b)


SEPARATOR = "\n" + "=" * 60 + "\n"


# ── Phase 1: Kernel Foundation ───────────────────────────────────────────────

def demo_phase1(event_log: SQLiteEventLog) -> str:
    print(SEPARATOR + "PHASE 1 — Kernel Foundation" + SEPARATOR)

    # Tool registration
    registry = ToolRegistry()
    add_tool = AddTool()
    registry.register(add_tool)
    print(f"[Tools] Registered: {[t.name for t in registry.list_tools()]}")

    # Tool execution with validation
    inp = add_tool.validate_input({"a": 15, "b": 27})
    out = add_tool.execute(inp)
    print(f"[Tools] add(15, 27) = {out.result}")  # type: ignore[union-attr]

    # Linear workflow
    workflow = Workflow(name="data-pipeline", tasks=[
        TaskNode(name="fetch", callable=lambda: {"rows": 100}),
        TaskNode(name="validate", callable=lambda: {"valid": True}),
        TaskNode(name="compute", callable=lambda: add_tool.execute(AddInput(a=50, b=50))),
    ])

    executor = WorkflowExecutor(event_log)
    run_id = executor.run(workflow)

    print(f"\n[Workflow] Run {run_id[:8]}... completed")
    for task in workflow.tasks:
        print(f"  [{task.state.value:9s}] {task.name} -> {task.result}")

    print(f"\n[Events] {len(event_log.replay(run_id))} events persisted")
    return run_id


# ── Phase 2: Governance & DAG ────────────────────────────────────────────────

def demo_phase2(event_log: SQLiteEventLog) -> str:
    print(SEPARATOR + "PHASE 2 — Governance & DAG" + SEPARATOR)

    # DAG workflow (diamond pattern)
    a = TaskNode(name="ingest", callable=lambda: {"data": [1, 2, 3]})
    b = TaskNode(name="branch-A", callable=lambda: {"sum": 6}, depends_on=[a])
    c = TaskNode(name="branch-B", callable=lambda: {"mean": 2.0}, depends_on=[a])
    d = TaskNode(name="merge", callable=lambda: {"final": "done"}, depends_on=[b, c])

    dag = DAGWorkflow(name="diamond-pipeline", tasks=[a, b, c, d])
    dag.validate()
    print(f"[DAG] Validated: {dag.name} ({len(dag.tasks)} tasks)")
    print(f"[DAG] Topological order: {[t.name for t in dag.topological_order()]}")

    dag_executor = DAGExecutor(event_log, max_parallel=2)
    run_id = dag_executor.run(dag)

    print(f"\n[DAG] Run {run_id[:8]}... completed")
    for task in dag.tasks:
        print(f"  [{task.state.value:9s}] {task.name} -> {task.result}")

    # Budget manager
    print("\n[Budget] Testing budget enforcement...")
    budget_run = generate_run_id()
    spec = BudgetSpec(max_tokens=100, max_tool_calls=3, max_time_seconds=60.0, max_recursion_depth=5)
    budget_mgr = BudgetManager(spec, event_log, budget_run)
    budget_mgr.record_tool_call()
    budget_mgr.record_tool_call()
    budget_mgr.record_tokens(50)
    budget_mgr.check()  # still OK
    print(f"  Usage: {budget_mgr.usage.tool_calls_used} tool calls, {budget_mgr.usage.tokens_used} tokens")
    budget_mgr.record_tool_call()
    try:
        budget_mgr.check()
    except BudgetExceededError as e:
        print(f"  Budget exceeded: {e}")

    # Concurrency limiter
    print("\n[Concurrency] Testing limiter...")
    limiter = ConcurrencyLimiter(max_parallel=2, per_tool_limits={"slow_tool": 1})
    limiter.acquire()
    limiter.acquire()
    blocked = limiter.try_acquire()
    print(f"  Active: {limiter.active_count}, try_acquire at limit: {blocked}")
    limiter.release()
    limiter.release()

    # Stop conditions
    print("\n[StopConditions] Testing repeat detection...")
    stop_run = generate_run_id()
    checker = StopConditionChecker(event_log, stop_run, max_repeated_tool_calls=3)
    for _ in range(3):
        checker.record_tool_call("search", "same_query_hash")
    reason = checker.check(seq=0)
    print(f"  Stop triggered: {reason}")

    # Permissions
    print("\n[Permissions] Testing policy enforcement...")
    perm_run = generate_run_id()
    policy = PermissionPolicy(rules=[
        PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW),
        PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
        PermissionRule(side_effect=SideEffect.DESTRUCTIVE, action=PolicyAction.DENY, reason="no destructive ops"),
    ], default_action=PolicyAction.DENY)
    engine = PermissionsEngine(policy, event_log, perm_run)
    engine.check("calculator", SideEffect.PURE, seq=0)
    print("  PURE tool: ALLOWED")
    try:
        engine.check("file_deleter", SideEffect.DESTRUCTIVE, seq=1)
    except PermissionDeniedError as e:
        print(f"  DESTRUCTIVE tool: DENIED ({e})")

    return run_id


# ── Phase 3: Observability & Replay ──────────────────────────────────────────

def demo_phase3(event_log: SQLiteEventLog, run_id: str) -> None:
    print(SEPARATOR + "PHASE 3 — Observability & Replay" + SEPARATOR)

    # Deterministic hashing
    inp1 = AddInput(a=10, b=20)
    inp2 = AddInput(a=10, b=20)
    h1 = hash_model(inp1)
    h2 = hash_model(inp2)
    print(f"[Hashing] Same input -> same hash: {h1 == h2}")
    print(f"  Canonical JSON: {canonical_json(inp1)}")
    print(f"  SHA-256: {h1[:16]}...")

    inp3 = AddInput(a=99, b=1)
    h3 = hash_model(inp3)
    print(f"  Different input -> different hash: {h1 != h3}")

    # Replay
    print(f"\n[Replay] Replaying run {run_id[:8]}...")
    replay_engine = ReplayEngine(event_log)
    result = replay_engine.replay(run_id, mode=ReplayMode.STRICT)
    print(f"  Events: {len(result.events)}, Success: {result.success}")
    print(f"  Task events: {len(result.task_events)}")
    print(f"  Tool call events: {len(result.tool_call_events)}")


# ── Phase 4: Memory & Integrity ──────────────────────────────────────────────

def demo_phase4(event_log: SQLiteEventLog, run_id: str) -> None:
    print(SEPARATOR + "PHASE 4 — Memory & Integrity" + SEPARATOR)

    # Episodic store
    print("[Episodic] Summarizing run...")
    episodic = EpisodicStore(event_log)
    summary = episodic.summarize(run_id)
    print(f"  Workflow: {summary.workflow_name}")
    print(f"  Outcome: {summary.outcome}")
    print(f"  Tasks: {summary.task_count} ({summary.tasks_succeeded} ok, {summary.tasks_failed} failed)")
    print(f"  Events: {summary.total_events}")

    # Semantic store
    print("\n[Semantic] Storing facts with provenance...")
    store = SemanticStore()
    rid = generate_run_id()

    store.add(Fact(key="model.accuracy", value=0.89,
                   provenance=Provenance(run_id=rid, task_name="train_v1")))
    store.add(Fact(key="model.accuracy", value=0.93,
                   provenance=Provenance(run_id=rid, task_name="train_v2")))
    store.add(Fact(key="model.loss", value=0.07,
                   provenance=Provenance(run_id=rid, task_name="train_v2")))
    store.add(Fact(key="data.rows", value=10000,
                   provenance=Provenance(run_id=rid, task_name="ingest")))

    print(f"  Facts stored: {len(store)} keys")
    print(f"  model.accuracy (latest): {store.get('model.accuracy').value}")  # type: ignore[union-attr]
    print(f"  model.accuracy history: {[f.value for f in store.get_history('model.accuracy')]}")

    conflicts = store.get_conflicts()
    print(f"  Conflicts: {len(conflicts)}")
    for c in conflicts:
        print(f"    {c.key}: {c.fact_a.value} vs {c.fact_b.value} (resolved={c.resolved})")

    # Context pack
    print("\n[ContextPack] Building evidence pack...")
    builder = ContextPackBuilder(store)
    pack = builder.build_for_prefix("model.")

    print(f"  Claims: {len(pack.claims)}")
    for claim in pack.claims:
        print(f"    {claim.key} = {claim.value}")
        print(f"      Evidence items: {len(claim.evidence)}, Freshness: {claim.freshness_score:.2f}")
        print(f"      Conflicts: {len(claim.conflicts)}, Confidence: {claim.confidence:.2f}")


# ── Phase 5: Evaluation Harness ──────────────────────────────────────────────

def demo_phase5() -> None:
    print(SEPARATOR + "PHASE 5 — Evaluation Harness" + SEPARATOR)

    add_tool = AddTool()

    class ToolAccuracyEval(EvalCase):
        @property
        def name(self) -> str:
            return "tool-accuracy"

        @property
        def tags(self) -> list[str]:
            return ["core"]

        def run(self) -> EvalResult:
            result = add_tool.execute(AddInput(a=17, b=25))
            assert isinstance(result, AddOutput)
            passed = result.result == 42
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if passed else EvalOutcome.FAILED,
                duration_seconds=0.0,
                metrics={"expected": 42, "actual": float(result.result)},
            )

    class WorkflowEval(EvalCase):
        @property
        def name(self) -> str:
            return "workflow-execution"

        @property
        def tags(self) -> list[str]:
            return ["core"]

        def run(self) -> EvalResult:
            log = SQLiteEventLog()
            wf = Workflow(name="eval-wf", tasks=[
                TaskNode(name="step1", callable=lambda: "ok"),
                TaskNode(name="step2", callable=lambda: "done"),
            ])
            executor = WorkflowExecutor(log)
            rid = executor.run(wf)
            events = log.replay(rid)
            passed = len(events) == 6  # RunStarted + 2*(TaskStarted+TaskFinished) + RunFinished
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if passed else EvalOutcome.FAILED,
                duration_seconds=0.0,
                metrics={"event_count": float(len(events))},
            )

    class BudgetEnforcementEval(EvalCase):
        @property
        def name(self) -> str:
            return "budget-enforcement"

        @property
        def tags(self) -> list[str]:
            return ["governance"]

        def run(self) -> EvalResult:
            log = SQLiteEventLog()
            rid = generate_run_id()
            spec = BudgetSpec(max_tokens=10, max_tool_calls=2, max_time_seconds=60.0, max_recursion_depth=5)
            mgr = BudgetManager(spec, log, rid)
            mgr.record_tool_call()
            mgr.record_tool_call()
            try:
                mgr.check()
                return EvalResult(case_name=self.name, outcome=EvalOutcome.FAILED,
                                  duration_seconds=0.0, error_message="Should have raised")
            except BudgetExceededError:
                return EvalResult(case_name=self.name, outcome=EvalOutcome.PASSED,
                                  duration_seconds=0.0)

    class ReplayEval(EvalCase):
        @property
        def name(self) -> str:
            return "replay-integrity"

        @property
        def tags(self) -> list[str]:
            return ["observability"]

        def run(self) -> EvalResult:
            log = SQLiteEventLog()
            wf = Workflow(name="replay-test", tasks=[
                TaskNode(name="x", callable=lambda: "ok"),
            ])
            executor = WorkflowExecutor(log)
            rid = executor.run(wf)

            engine = ReplayEngine(log)
            replay = engine.replay(rid)
            passed = replay.success and len(replay.events) == len(log.replay(rid))
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if passed else EvalOutcome.FAILED,
                duration_seconds=0.0,
                metrics={"replayed_events": float(len(replay.events))},
            )

    class HashDeterminismEval(EvalCase):
        @property
        def name(self) -> str:
            return "hash-determinism"

        @property
        def tags(self) -> list[str]:
            return ["integrity"]

        def run(self) -> EvalResult:
            m1 = AddInput(a=1, b=2)
            m2 = AddInput(a=1, b=2)
            m3 = AddInput(a=2, b=1)
            same = hash_model(m1) == hash_model(m2)
            diff = hash_model(m1) != hash_model(m3)
            passed = same and diff
            return EvalResult(
                case_name=self.name,
                outcome=EvalOutcome.PASSED if passed else EvalOutcome.FAILED,
                duration_seconds=0.0,
            )

    # Build and run suite
    suite = EvalSuite(name="AgentOS Kernel Eval", cases=[
        ToolAccuracyEval(),
        WorkflowEval(),
        BudgetEnforcementEval(),
        ReplayEval(),
        HashDeterminismEval(),
    ])

    runner = EvalRunner()
    results = runner.run_suite(suite)

    print(f"[EvalSuite] {suite.name}")
    print(f"{'─' * 50}")
    for r in results:
        icon = "PASS" if r.outcome == EvalOutcome.PASSED else "FAIL"
        print(f"  [{icon}] {r.case_name} ({r.duration_seconds:.3f}s)")
        if r.metrics:
            for k, v in r.metrics.items():
                print(f"         {k}: {v}")

    metrics = runner.compute_metrics()
    print(f"\n{'─' * 50}")
    print(f"  Total: {metrics.total_cases}  Passed: {metrics.passed}  Failed: {metrics.failed}  Errors: {metrics.errors}")
    print(f"  Success rate: {metrics.success_rate:.0%}")
    print(f"  Total duration: {metrics.total_duration_seconds:.3f}s")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n  AgentOS Kernel — Full Integration Demo\n")

    event_log = SQLiteEventLog()

    run_id_p1 = demo_phase1(event_log)
    run_id_p2 = demo_phase2(event_log)
    demo_phase3(event_log, run_id_p2)
    demo_phase4(event_log, run_id_p1)
    demo_phase5()

    event_log.close()
    print(SEPARATOR + "All phases demonstrated successfully." + SEPARATOR)


if __name__ == "__main__":
    main()
