"""Tests for cross-run memory store."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from agentos.kernel.memory_store import (
    SQLiteMemoryStore,
    extract_memories_from_output,
)
from agentos.schemas.memory import (
    MemoryConfig,
    MemoryEntry,
    MemoryQuery,
    MemoryType,
)


@pytest.fixture
def config() -> MemoryConfig:
    return MemoryConfig(enabled=True, decay_rate=0.05, min_confidence=0.1)


@pytest.fixture
def store(config) -> SQLiteMemoryStore:
    return SQLiteMemoryStore(config)


def _make_entry(
    memory_type: MemoryType = MemoryType.FINDING,
    confidence: float = 0.8,
    tags: list[str] | None = None,
    ttl_hours: int | None = None,
    created_at: datetime | None = None,
) -> MemoryEntry:
    entry = MemoryEntry(
        memory_id=str(uuid.uuid4()),
        workflow_id="wf-1",
        task_id="t-1",
        memory_type=memory_type,
        content="Test memory content",
        confidence=confidence,
        tags=tags or [],
        ttl_hours=ttl_hours,
    )
    if created_at:
        entry.created_at = created_at
    return entry


class TestStoreAndRetrieve:
    def test_store_and_get(self, store):
        entry = _make_entry()
        store.store(entry)
        retrieved = store.get(entry.memory_id)
        assert retrieved is not None
        assert retrieved.memory_id == entry.memory_id
        assert retrieved.content == "Test memory content"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent") is None

    def test_count(self, store):
        assert store.count() == 0
        store.store(_make_entry())
        assert store.count() == 1
        store.store(_make_entry())
        assert store.count() == 2

    def test_upsert(self, store):
        entry = _make_entry()
        store.store(entry)
        entry.content = "Updated content"
        store.store(entry)
        assert store.count() == 1
        retrieved = store.get(entry.memory_id)
        assert retrieved.content == "Updated content"


class TestQuery:
    def test_query_all(self, store):
        for _ in range(3):
            store.store(_make_entry())
        results = store.query(MemoryQuery())
        assert len(results) == 3

    def test_query_by_type(self, store):
        store.store(_make_entry(memory_type=MemoryType.FINDING))
        store.store(_make_entry(memory_type=MemoryType.DECISION))
        store.store(_make_entry(memory_type=MemoryType.GATE_FEEDBACK))
        results = store.query(MemoryQuery(memory_type=MemoryType.FINDING))
        assert len(results) == 1
        assert results[0].memory_type == MemoryType.FINDING

    def test_query_by_min_confidence(self, store):
        store.store(_make_entry(confidence=0.9))
        store.store(_make_entry(confidence=0.5))
        store.store(_make_entry(confidence=0.2))
        results = store.query(MemoryQuery(min_confidence=0.5))
        assert len(results) == 2

    def test_query_by_tags(self, store):
        store.store(_make_entry(tags=["python", "security"]))
        store.store(_make_entry(tags=["javascript"]))
        store.store(_make_entry(tags=["python", "testing"]))
        results = store.query(MemoryQuery(tags=["python"]))
        assert len(results) == 2

    def test_query_limit(self, store):
        for _ in range(5):
            store.store(_make_entry())
        results = store.query(MemoryQuery(limit=3))
        assert len(results) == 3

    def test_query_updates_access_count(self, store):
        entry = _make_entry()
        store.store(entry)
        store.query(MemoryQuery())
        retrieved = store.get(entry.memory_id)
        assert retrieved.access_count == 1

    def test_query_ordered_by_confidence(self, store):
        store.store(_make_entry(confidence=0.3))
        store.store(_make_entry(confidence=0.9))
        store.store(_make_entry(confidence=0.6))
        results = store.query(MemoryQuery())
        assert results[0].confidence == 0.9
        assert results[1].confidence == 0.6
        assert results[2].confidence == 0.3


class TestDecay:
    def test_decay_reduces_confidence(self, store):
        old_entry = _make_entry(confidence=0.5)
        old_entry.created_at = datetime.now() - timedelta(days=10)
        store.store(old_entry)
        store.decay()
        retrieved = store.get(old_entry.memory_id)
        # After 10 days at 0.05 rate: 0.5 - (0.05 * 10) = 0.0, should be pruned
        assert retrieved is None

    def test_decay_prunes_below_threshold(self, config, store):
        entry = _make_entry(confidence=0.15)
        entry.created_at = datetime.now() - timedelta(days=2)
        store.store(entry)
        pruned = store.decay()
        assert pruned >= 1
        assert store.count() == 0

    def test_fresh_entries_survive_decay(self, store):
        entry = _make_entry(confidence=0.9)
        store.store(entry)
        store.decay()
        assert store.count() == 1


class TestPrune:
    def test_prune_low_confidence(self, store):
        store.store(_make_entry(confidence=0.05))  # Below 0.1 threshold
        store.store(_make_entry(confidence=0.8))
        removed = store.prune()
        assert removed >= 1
        assert store.count() == 1

    def test_prune_expired_ttl(self, store):
        entry = _make_entry(ttl_hours=1)
        entry.created_at = datetime.now() - timedelta(hours=2)
        store.store(entry)
        removed = store.prune()
        assert removed >= 1
        assert store.count() == 0

    def test_prune_keeps_valid_ttl(self, store):
        entry = _make_entry(ttl_hours=24)
        store.store(entry)
        store.prune()
        assert store.count() == 1


class TestExtractMemories:
    def test_extract_findings(self):
        findings = [
            {"content": "Finding 1", "confidence": 0.9, "tags": ["security"]},
            {"content": "Finding 2", "confidence": 0.7},
        ]
        memories = extract_memories_from_output("wf-1", "t-1", findings)
        assert len(memories) == 2
        assert memories[0].memory_type == MemoryType.FINDING
        assert memories[0].content == "Finding 1"
        assert memories[0].confidence == 0.9
        assert memories[0].tags == ["security"]

    def test_extract_gate_feedback(self):
        memories = extract_memories_from_output(
            "wf-1", "t-1", [], gate_feedback="Approved with changes needed"
        )
        assert len(memories) == 1
        assert memories[0].memory_type == MemoryType.GATE_FEEDBACK
        assert memories[0].content == "Approved with changes needed"

    def test_extract_both(self):
        findings = [{"content": "A finding"}]
        memories = extract_memories_from_output(
            "wf-1", "t-1", findings, gate_feedback="OK"
        )
        assert len(memories) == 2

    def test_extract_empty(self):
        memories = extract_memories_from_output("wf-1", "t-1", [])
        assert len(memories) == 0


class TestSchemaRoundTrip:
    def test_memory_entry_serialization(self):
        entry = _make_entry(tags=["test", "python"])
        data = entry.model_dump(mode="json")
        restored = MemoryEntry.model_validate(data)
        assert restored.memory_id == entry.memory_id
        assert restored.tags == ["test", "python"]

    def test_memory_config_serialization(self):
        config = MemoryConfig(enabled=True, decay_rate=0.1, min_confidence=0.2)
        data = config.model_dump(mode="json")
        restored = MemoryConfig.model_validate(data)
        assert restored.decay_rate == 0.1

    def test_memory_query_serialization(self):
        q = MemoryQuery(tags=["python"], memory_type=MemoryType.FINDING, min_confidence=0.5)
        data = q.model_dump(mode="json")
        restored = MemoryQuery.model_validate(data)
        assert restored.memory_type == MemoryType.FINDING
