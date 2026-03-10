"""Cross-run memory store — ABC and SQLite implementation."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from agentos.schemas.memory import MemoryConfig, MemoryEntry, MemoryQuery, MemoryType


class MemoryStore(ABC):
    """Abstract base for cross-run memory storage.

    Stores findings, decisions, and feedback from completed workflows
    so that subsequent runs can benefit from accumulated knowledge.
    """

    @abstractmethod
    def store(self, entry: MemoryEntry) -> None:
        """Store a memory entry."""

    @abstractmethod
    def query(self, q: MemoryQuery) -> list[MemoryEntry]:
        """Query memories matching the given criteria."""

    @abstractmethod
    def get(self, memory_id: str) -> MemoryEntry | None:
        """Get a specific memory by ID."""

    @abstractmethod
    def decay(self) -> int:
        """Apply confidence decay to all entries. Returns count of pruned entries."""

    @abstractmethod
    def prune(self) -> int:
        """Remove expired and low-confidence entries. Returns count removed."""

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored memories."""


class SQLiteMemoryStore(MemoryStore):
    """SQLite-backed cross-run memory store."""

    def __init__(self, config: MemoryConfig, db_path: str = ":memory:") -> None:
        self._config = config
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                tags TEXT NOT NULL DEFAULT '[]',
                ttl_hours INTEGER,
                created_at TEXT NOT NULL,
                last_accessed TEXT,
                access_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories(confidence);
        """)
        self._conn.commit()

    def store(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO memories
                   (memory_id, workflow_id, task_id, memory_type, content,
                    confidence, tags, ttl_hours, created_at, last_accessed, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.memory_id,
                    entry.workflow_id,
                    entry.task_id,
                    entry.memory_type.value,
                    entry.content,
                    entry.confidence,
                    json.dumps(entry.tags),
                    entry.ttl_hours,
                    entry.created_at.isoformat(),
                    entry.last_accessed.isoformat() if entry.last_accessed else None,
                    entry.access_count,
                ),
            )
            self._conn.commit()

    def query(self, q: MemoryQuery) -> list[MemoryEntry]:
        clauses: list[str] = ["confidence >= ?"]
        params: list[object] = [q.min_confidence]

        if q.memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(q.memory_type.value)

        sql = f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(q.limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        results = [self._row_to_entry(r) for r in rows]

        # Filter by tags in Python (simpler than JSON querying in SQLite)
        if q.tags:
            tag_set = set(q.tags)
            results = [e for e in results if tag_set & set(e.tags)]

        # Update access metadata
        now = datetime.now().isoformat()
        with self._lock:
            for entry in results:
                self._conn.execute(
                    "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE memory_id = ?",
                    (now, entry.memory_id),
                )
            self._conn.commit()

        return results

    def get(self, memory_id: str) -> MemoryEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def decay(self) -> int:
        """Apply confidence decay based on age. Prune entries below threshold."""
        now = datetime.now()
        with self._lock:
            rows = self._conn.execute("SELECT memory_id, confidence, created_at FROM memories").fetchall()

        pruned = 0
        for memory_id, confidence, created_at_str in rows:
            created_at = datetime.fromisoformat(created_at_str)
            age_days = (now - created_at).total_seconds() / 86400
            new_confidence = max(0.0, confidence - self._config.decay_rate * age_days)

            if new_confidence < self._config.min_confidence:
                with self._lock:
                    self._conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                pruned += 1
            else:
                with self._lock:
                    self._conn.execute(
                        "UPDATE memories SET confidence = ? WHERE memory_id = ?",
                        (new_confidence, memory_id),
                    )

        with self._lock:
            self._conn.commit()
        return pruned

    def prune(self) -> int:
        """Remove expired (TTL) and low-confidence entries."""
        now = datetime.now()
        removed = 0

        with self._lock:
            # Remove low confidence
            cursor = self._conn.execute(
                "DELETE FROM memories WHERE confidence < ?",
                (self._config.min_confidence,),
            )
            removed += cursor.rowcount

            # Remove expired TTL entries
            rows = self._conn.execute(
                "SELECT memory_id, created_at, ttl_hours FROM memories WHERE ttl_hours IS NOT NULL"
            ).fetchall()

        for memory_id, created_at_str, ttl_hours in rows:
            created_at = datetime.fromisoformat(created_at_str)
            if now > created_at + timedelta(hours=ttl_hours):
                with self._lock:
                    self._conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                removed += 1

        with self._lock:
            self._conn.commit()
        return removed

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_entry(row: tuple) -> MemoryEntry:
        return MemoryEntry(
            memory_id=row[0],
            workflow_id=row[1],
            task_id=row[2],
            memory_type=MemoryType(row[3]),
            content=row[4],
            confidence=row[5],
            tags=json.loads(row[6]),
            ttl_hours=row[7],
            created_at=row[8],
            last_accessed=row[9],
            access_count=row[10],
        )


def extract_memories_from_output(
    workflow_id: str,
    task_id: str,
    findings: list[dict],
    gate_feedback: str | None = None,
) -> list[MemoryEntry]:
    """Extract memory entries from task output data.

    Converts key findings and gate feedback into storable memories.
    """
    memories: list[MemoryEntry] = []

    for finding in findings:
        memories.append(
            MemoryEntry(
                memory_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                task_id=task_id,
                memory_type=MemoryType.FINDING,
                content=finding.get("content", str(finding)),
                confidence=finding.get("confidence", 0.8),
                tags=finding.get("tags", []),
            )
        )

    if gate_feedback:
        memories.append(
            MemoryEntry(
                memory_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                task_id=task_id,
                memory_type=MemoryType.GATE_FEEDBACK,
                content=gate_feedback,
                confidence=1.0,
                tags=["gate", "feedback"],
            )
        )

    return memories
