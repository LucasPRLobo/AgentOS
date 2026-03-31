"""Round-trip serialization tests for task and event schemas."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agentos.schemas.events import EVENT_TABLE_DDL, Event, EventType
from agentos.schemas.task import (
    Confidence,
    FileReference,
    Finding,
    TaskMetrics,
    TaskOutput,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# TaskStatus enum
# ---------------------------------------------------------------------------


class TestTaskStatus:
    def test_all_values(self):
        assert set(TaskStatus) == {"pending", "running", "succeeded", "failed", "waiting", "skipped"}

    def test_string_comparison(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.WAITING == "waiting"


# ---------------------------------------------------------------------------
# Confidence enum
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_all_values(self):
        assert set(Confidence) == {"high", "medium", "low"}

    def test_string_comparison(self):
        assert Confidence.HIGH == "high"


# ---------------------------------------------------------------------------
# Finding model
# ---------------------------------------------------------------------------


class TestFinding:
    def test_round_trip(self):
        f = Finding(
            finding="API rate limit is 100 req/min",
            confidence=Confidence.HIGH,
            sources=["https://docs.example.com/limits"],
        )
        data = json.loads(f.model_dump_json())
        f2 = Finding.model_validate(data)
        assert f2.finding == f.finding
        assert f2.confidence == Confidence.HIGH
        assert f2.sources == ["https://docs.example.com/limits"]

    def test_default_sources_empty(self):
        f = Finding(finding="test", confidence=Confidence.LOW)
        assert f.sources == []

    def test_json_serializable(self):
        f = Finding(finding="x", confidence=Confidence.MEDIUM)
        raw = f.model_dump_json()
        assert '"confidence":"medium"' in raw


# ---------------------------------------------------------------------------
# FileReference model
# ---------------------------------------------------------------------------


class TestFileReference:
    def test_round_trip(self):
        fr = FileReference(path="src/main.py", description="Main entry point")
        data = json.loads(fr.model_dump_json())
        fr2 = FileReference.model_validate(data)
        assert fr2.path == "src/main.py"
        assert fr2.role == "primary"

    def test_custom_role(self):
        fr = FileReference(path="debug.log", description="Debug log", role="log")
        assert fr.role == "log"


# ---------------------------------------------------------------------------
# TaskMetrics model
# ---------------------------------------------------------------------------


class TestTaskMetrics:
    def test_defaults(self):
        m = TaskMetrics()
        assert m.tokens_consumed == 0
        assert m.api_calls_made == 0
        assert m.execution_time_seconds == 0.0
        assert m.estimated_cost_usd == 0.0

    def test_round_trip(self):
        m = TaskMetrics(
            tokens_consumed=4200,
            api_calls_made=3,
            execution_time_seconds=12.5,
            estimated_cost_usd=0.07,
        )
        data = json.loads(m.model_dump_json())
        m2 = TaskMetrics.model_validate(data)
        assert m2.tokens_consumed == 4200
        assert m2.estimated_cost_usd == pytest.approx(0.07)


# ---------------------------------------------------------------------------
# TaskOutput model — research task
# ---------------------------------------------------------------------------


class TestTaskOutputResearch:
    def test_research_round_trip(self):
        output = TaskOutput(
            task_id="t1",
            agent_id="researcher-01",
            status=TaskStatus.SUCCEEDED,
            summary="Analyzed 3 API docs and found rate limiting patterns.",
            key_findings=[
                Finding(
                    finding="Rate limit is 100 req/min",
                    confidence=Confidence.HIGH,
                    sources=["https://docs.example.com"],
                ),
                Finding(
                    finding="Retry-After header supported",
                    confidence=Confidence.MEDIUM,
                ),
            ],
            files_produced=[
                FileReference(path="research/findings.md", description="Research summary"),
            ],
            open_questions=["Is there a burst limit?"],
            metrics=TaskMetrics(tokens_consumed=3500, api_calls_made=2),
        )
        raw = output.model_dump_json()
        restored = TaskOutput.model_validate_json(raw)
        assert restored.task_id == "t1"
        assert restored.status == TaskStatus.SUCCEEDED
        assert len(restored.key_findings) == 2
        assert restored.key_findings[0].confidence == Confidence.HIGH
        assert restored.open_questions == ["Is there a burst limit?"]
        assert restored.metrics is not None
        assert restored.metrics.tokens_consumed == 3500


# ---------------------------------------------------------------------------
# TaskOutput model — code implementation task
# ---------------------------------------------------------------------------


class TestTaskOutputImplementation:
    def test_implementation_round_trip(self):
        output = TaskOutput(
            task_id="t2",
            agent_id="coder-01",
            status=TaskStatus.SUCCEEDED,
            summary="Implemented retry logic with exponential backoff.",
            key_findings=[
                Finding(
                    finding="Added retry with max 3 attempts",
                    confidence=Confidence.HIGH,
                    sources=["src/client.py:42"],
                ),
            ],
            files_produced=[
                FileReference(path="src/client.py", description="HTTP client with retry"),
                FileReference(path="tests/test_client.py", description="Client tests", role="supporting"),
            ],
            metrics=TaskMetrics(
                tokens_consumed=8000,
                api_calls_made=5,
                execution_time_seconds=45.2,
                estimated_cost_usd=0.12,
            ),
        )
        data = json.loads(output.model_dump_json())
        restored = TaskOutput.model_validate(data)
        assert len(restored.files_produced) == 2
        assert restored.files_produced[1].role == "supporting"
        assert restored.schema_version == "0.1"


# ---------------------------------------------------------------------------
# TaskOutput model — failed task
# ---------------------------------------------------------------------------


class TestTaskOutputFailed:
    def test_failed_task_round_trip(self):
        output = TaskOutput(
            task_id="t3",
            agent_id="coder-02",
            status=TaskStatus.FAILED,
            summary="Build failed due to missing dependency.",
            open_questions=["Is numpy required?", "Which version?"],
        )
        raw = output.model_dump_json()
        restored = TaskOutput.model_validate_json(raw)
        assert restored.status == TaskStatus.FAILED
        assert len(restored.open_questions) == 2
        assert restored.key_findings == []
        assert restored.files_produced == []
        assert restored.metrics is None


# ---------------------------------------------------------------------------
# TaskOutput — defaults
# ---------------------------------------------------------------------------


class TestTaskOutputDefaults:
    def test_schema_version_default(self):
        output = TaskOutput(
            task_id="t0", agent_id="a0", status=TaskStatus.PENDING, summary="test"
        )
        assert output.schema_version == "0.1"

    def test_timestamp_auto_generated(self):
        output = TaskOutput(
            task_id="t0", agent_id="a0", status=TaskStatus.RUNNING, summary="test"
        )
        assert isinstance(output.timestamp, datetime)


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------


class TestEventType:
    def test_count(self):
        assert len(EventType) == 76

    def test_all_dotted_format(self):
        for et in EventType:
            assert "." in et.value, f"{et} should use dotted format"

    def test_string_comparison(self):
        assert EventType.WORKFLOW_STARTED == "workflow.started"
        assert EventType.BUDGET_EXCEEDED == "budget.exceeded"


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class TestEvent:
    def test_round_trip_minimal(self):
        event = Event(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-001",
            seq=0,
        )
        raw = event.model_dump_json()
        restored = Event.model_validate_json(raw)
        assert restored.event_type == EventType.WORKFLOW_STARTED
        assert restored.workflow_id == "wf-001"
        assert restored.seq == 0
        assert restored.schema_version == "0.1"
        assert restored.payload == {}
        assert restored.metadata == {}

    def test_round_trip_with_payload(self):
        event = Event(
            event_type=EventType.TASK_STATE_CHANGED,
            workflow_id="wf-002",
            seq=5,
            payload={
                "task_id": "t1",
                "from_state": "pending",
                "to_state": "running",
                "agent_id": "a1",
            },
        )
        data = json.loads(event.model_dump_json())
        restored = Event.model_validate(data)
        assert restored.payload["task_id"] == "t1"
        assert restored.payload["from_state"] == "pending"

    def test_event_id_auto_generated(self):
        e1 = Event(event_type=EventType.ERROR_OCCURRED, workflow_id="wf", seq=0)
        e2 = Event(event_type=EventType.ERROR_OCCURRED, workflow_id="wf", seq=1)
        assert e1.event_id != e2.event_id

    def test_timestamp_is_utc(self):
        event = Event(event_type=EventType.WORKFLOW_STARTED, workflow_id="wf", seq=0)
        assert event.timestamp.tzinfo is not None

    def test_seq_must_be_non_negative(self):
        with pytest.raises(Exception):
            Event(event_type=EventType.WORKFLOW_STARTED, workflow_id="wf", seq=-1)

    def test_metadata_round_trip(self):
        event = Event(
            event_type=EventType.AGENT_SPAWNED,
            workflow_id="wf-003",
            seq=2,
            metadata={"trace_id": "abc123", "retry_count": 0},
        )
        raw = event.model_dump_json()
        restored = Event.model_validate_json(raw)
        assert restored.metadata["trace_id"] == "abc123"

    def test_budget_consumed_payload(self):
        event = Event(
            event_type=EventType.BUDGET_CONSUMED,
            workflow_id="wf-004",
            seq=10,
            payload={
                "agent_id": "a1",
                "resource": "tokens",
                "amount": 500,
                "cumulative": 2100,
                "limit": 10000,
            },
        )
        data = json.loads(event.model_dump_json())
        restored = Event.model_validate(data)
        assert restored.payload["resource"] == "tokens"
        assert restored.payload["cumulative"] == 2100

    def test_gate_resolved_payload(self):
        event = Event(
            event_type=EventType.GATE_RESOLVED,
            workflow_id="wf-005",
            seq=7,
            payload={
                "gate_id": "g1",
                "resolution": "approved",
                "reviewer": "user",
                "feedback": "Looks good",
            },
        )
        raw = event.model_dump_json()
        restored = Event.model_validate_json(raw)
        assert restored.payload["resolution"] == "approved"


# ---------------------------------------------------------------------------
# EVENT_TABLE_DDL
# ---------------------------------------------------------------------------


class TestEventDDL:
    def test_ddl_contains_create_table(self):
        assert "CREATE TABLE IF NOT EXISTS events" in EVENT_TABLE_DDL

    def test_ddl_contains_indexes(self):
        assert "idx_events_workflow" in EVENT_TABLE_DDL
        assert "idx_events_type" in EVENT_TABLE_DDL
        assert "idx_events_timestamp" in EVENT_TABLE_DDL

    def test_ddl_contains_unique_constraint(self):
        assert "UNIQUE(workflow_id, seq)" in EVENT_TABLE_DDL
