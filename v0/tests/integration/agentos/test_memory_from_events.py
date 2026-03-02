"""Integration tests for memory subsystem derived from real event streams."""

from __future__ import annotations

import pytest

from agentos.core.identifiers import RunId, generate_run_id
from agentos.memory.context_pack import ContextPackBuilder
from agentos.memory.episodic import EpisodicStore
from agentos.memory.semantic import Fact, Provenance, SemanticStore
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import (
    EventType,
    RunFinished,
    RunStarted,
    TaskFinished,
    TaskStarted,
    ToolCallFinished,
    ToolCallStarted,
)

pytestmark = pytest.mark.integration


def _build_3_task_workflow(event_log: SQLiteEventLog, run_id: RunId) -> None:
    """Emit events for a simple 3-task workflow that succeeds."""
    event_log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "test_wf"}))

    for i, name in enumerate(["TaskA", "TaskB", "TaskC"]):
        seq_start = 1 + i * 4
        tid = f"task-{i}"
        event_log.append(
            TaskStarted(
                run_id=run_id, seq=seq_start,
                payload={"task_id": tid, "task_name": name},
            )
        )
        event_log.append(
            ToolCallStarted(
                run_id=run_id, seq=seq_start + 1,
                payload={"tool_name": f"tool_{name}", "side_effect": "PURE"},
            )
        )
        event_log.append(
            ToolCallFinished(
                run_id=run_id, seq=seq_start + 2,
                payload={"tool_name": f"tool_{name}", "success": True},
            )
        )
        event_log.append(
            TaskFinished(
                run_id=run_id, seq=seq_start + 3,
                payload={"task_id": tid, "task_name": name, "state": "SUCCEEDED"},
            )
        )

    event_log.append(
        RunFinished(run_id=run_id, seq=13, payload={"workflow": "test_wf", "outcome": "SUCCEEDED"})
    )


def _build_failed_workflow(event_log: SQLiteEventLog, run_id: RunId) -> None:
    """Emit events for a workflow where one task fails."""
    event_log.append(RunStarted(run_id=run_id, seq=0, payload={"workflow": "fail_wf"}))

    event_log.append(
        TaskStarted(run_id=run_id, seq=1, payload={"task_id": "t0", "task_name": "GoodTask"})
    )
    event_log.append(
        TaskFinished(
            run_id=run_id, seq=2,
            payload={"task_id": "t0", "task_name": "GoodTask", "state": "SUCCEEDED"},
        )
    )

    event_log.append(
        TaskStarted(run_id=run_id, seq=3, payload={"task_id": "t1", "task_name": "BadTask"})
    )
    event_log.append(
        TaskFinished(
            run_id=run_id, seq=4,
            payload={"task_id": "t1", "task_name": "BadTask", "state": "FAILED"},
        )
    )

    event_log.append(
        RunFinished(
            run_id=run_id, seq=5,
            payload={"workflow": "fail_wf", "outcome": "FAILED", "failed_task": "BadTask"},
        )
    )


class TestEpisodicSummary:
    """Verify episodic summaries derived from real event streams."""

    def test_3_task_workflow_summary(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        _build_3_task_workflow(log, rid)

        store = EpisodicStore(log)
        summary = store.summarize(rid)

        assert summary.workflow_name == "test_wf"
        assert summary.outcome == "SUCCEEDED"
        assert summary.task_count == 3
        assert summary.tasks_succeeded == 3
        assert summary.tasks_failed == 0
        assert summary.tool_calls == 3
        assert summary.total_events == 14  # 1 + 3*(4) + 1
        log.close()

    def test_failed_workflow_summary(self):
        log = SQLiteEventLog(":memory:")
        rid = generate_run_id()
        _build_failed_workflow(log, rid)

        store = EpisodicStore(log)
        summary = store.summarize(rid)

        assert summary.outcome == "FAILED"
        assert summary.failed_task == "BadTask"
        assert summary.tasks_succeeded == 1
        assert summary.tasks_failed == 1
        log.close()


class TestSemanticFacts:
    """Verify semantic facts are queryable by run_id."""

    def test_facts_queryable_by_run(self):
        rid = generate_run_id()
        store = SemanticStore()

        store.add(Fact(
            key="model.accuracy",
            value=0.95,
            provenance=Provenance(run_id=rid, task_name="train"),
        ))
        store.add(Fact(
            key="model.loss",
            value=0.12,
            provenance=Provenance(run_id=rid, task_name="train"),
        ))

        facts = store.query_by_run(rid)
        assert len(facts) == 2
        keys = {f.key for f in facts}
        assert keys == {"model.accuracy", "model.loss"}

    def test_conflict_detected_on_value_change(self):
        rid = generate_run_id()
        store = SemanticStore()

        store.add(Fact(
            key="model.accuracy",
            value=0.90,
            provenance=Provenance(run_id=rid, task_name="run1"),
        ))
        conflict = store.add(Fact(
            key="model.accuracy",
            value=0.95,
            provenance=Provenance(run_id=rid, task_name="run2"),
        ))

        assert conflict is not None
        assert conflict.key == "model.accuracy"
        assert conflict.fact_a.value == 0.90
        assert conflict.fact_b.value == 0.95


class TestContextPack:
    """Verify context pack building with evidence and conflicts."""

    def test_build_claims_with_evidence(self):
        rid = generate_run_id()
        store = SemanticStore()

        store.add(Fact(
            key="metric.f1",
            value=0.88,
            provenance=Provenance(run_id=rid, task_name="eval"),
        ))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["metric.f1"])

        assert len(pack.claims) == 1
        claim = pack.claims[0]
        assert claim.key == "metric.f1"
        assert claim.value == 0.88
        assert len(claim.evidence) == 1

    def test_conflict_awareness(self):
        rid = generate_run_id()
        store = SemanticStore()

        store.add(Fact(
            key="result.score",
            value=0.80,
            provenance=Provenance(run_id=rid, task_name="v1"),
        ))
        store.add(Fact(
            key="result.score",
            value=0.85,
            provenance=Provenance(run_id=rid, task_name="v2"),
        ))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["result.score"])

        assert len(pack.claims) == 1
        claim = pack.claims[0]
        assert claim.has_conflicts is True
        assert len(pack.conflicted_claims) == 1
