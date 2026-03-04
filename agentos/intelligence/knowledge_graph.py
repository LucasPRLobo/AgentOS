"""Knowledge Graph — entities, relationships, observations with provenance."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Entity:
    entity_id: str
    entity_type: str
    name: str
    properties: dict[str, str] = field(default_factory=dict)
    source_workflow: str = ""
    created_at: str = ""


@dataclass
class Relationship:
    relationship_id: str
    from_entity: str
    to_entity: str
    relation_type: str
    properties: dict[str, str] = field(default_factory=dict)
    source_workflow: str = ""
    created_at: str = ""


@dataclass
class Observation:
    observation_id: str
    entity_id: str
    content: str
    confidence: float = 1.0
    source_workflow: str = ""
    created_at: str = ""


class KnowledgeGraph(ABC):
    """Abstract base for knowledge graph storage."""

    @abstractmethod
    def add_entity(self, entity_type: str, name: str, properties: dict[str, str] | None = None, source_workflow: str = "") -> Entity: ...

    @abstractmethod
    def add_relationship(self, from_entity: str, to_entity: str, relation_type: str, properties: dict[str, str] | None = None, source_workflow: str = "") -> Relationship: ...

    @abstractmethod
    def add_observation(self, entity_id: str, content: str, confidence: float = 1.0, source_workflow: str = "") -> Observation: ...

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None: ...

    @abstractmethod
    def get_relationships(self, entity_id: str) -> list[Relationship]: ...

    @abstractmethod
    def get_observations(self, entity_id: str) -> list[Observation]: ...

    @abstractmethod
    def search_entities(self, entity_type: str | None = None, name_pattern: str | None = None) -> list[Entity]: ...

    @abstractmethod
    def bfs(self, start_entity: str, max_depth: int = 3) -> list[Entity]: ...

    @abstractmethod
    def entity_count(self) -> int: ...

    @abstractmethod
    def relationship_count(self) -> int: ...


class SQLiteKnowledgeGraph(KnowledgeGraph):
    """SQLite-backed knowledge graph."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                name TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                source_workflow TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relationships (
                relationship_id TEXT PRIMARY KEY,
                from_entity TEXT NOT NULL REFERENCES entities(entity_id),
                to_entity TEXT NOT NULL REFERENCES entities(entity_id),
                relation_type TEXT NOT NULL,
                properties TEXT NOT NULL DEFAULT '{}',
                source_workflow TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL REFERENCES entities(entity_id),
                content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source_workflow TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
            CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_entity);
            CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_entity);
            CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_id);
        """)
        self._conn.commit()

    def add_entity(self, entity_type: str, name: str, properties: dict[str, str] | None = None, source_workflow: str = "") -> Entity:
        entity_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        props = properties or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO entities (entity_id, entity_type, name, properties, source_workflow, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (entity_id, entity_type, name, json.dumps(props), source_workflow, now),
            )
            self._conn.commit()
        return Entity(entity_id=entity_id, entity_type=entity_type, name=name, properties=props, source_workflow=source_workflow, created_at=now)

    def add_relationship(self, from_entity: str, to_entity: str, relation_type: str, properties: dict[str, str] | None = None, source_workflow: str = "") -> Relationship:
        rel_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        props = properties or {}
        with self._lock:
            self._conn.execute(
                "INSERT INTO relationships (relationship_id, from_entity, to_entity, relation_type, properties, source_workflow, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rel_id, from_entity, to_entity, relation_type, json.dumps(props), source_workflow, now),
            )
            self._conn.commit()
        return Relationship(relationship_id=rel_id, from_entity=from_entity, to_entity=to_entity, relation_type=relation_type, properties=props, source_workflow=source_workflow, created_at=now)

    def add_observation(self, entity_id: str, content: str, confidence: float = 1.0, source_workflow: str = "") -> Observation:
        obs_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO observations (observation_id, entity_id, content, confidence, source_workflow, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (obs_id, entity_id, content, confidence, source_workflow, now),
            )
            self._conn.commit()
        return Observation(observation_id=obs_id, entity_id=entity_id, content=content, confidence=confidence, source_workflow=source_workflow, created_at=now)

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if row is None:
            return None
        return Entity(entity_id=row[0], entity_type=row[1], name=row[2], properties=json.loads(row[3]), source_workflow=row[4], created_at=row[5])

    def get_relationships(self, entity_id: str) -> list[Relationship]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM relationships WHERE from_entity = ? OR to_entity = ?",
                (entity_id, entity_id),
            ).fetchall()
        return [Relationship(relationship_id=r[0], from_entity=r[1], to_entity=r[2], relation_type=r[3], properties=json.loads(r[4]), source_workflow=r[5], created_at=r[6]) for r in rows]

    def get_observations(self, entity_id: str) -> list[Observation]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM observations WHERE entity_id = ?", (entity_id,)).fetchall()
        return [Observation(observation_id=r[0], entity_id=r[1], content=r[2], confidence=r[3], source_workflow=r[4], created_at=r[5]) for r in rows]

    def search_entities(self, entity_type: str | None = None, name_pattern: str | None = None) -> list[Entity]:
        clauses: list[str] = []
        params: list[str] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if name_pattern:
            clauses.append("name LIKE ?")
            params.append(f"%{name_pattern}%")
        sql = "SELECT * FROM entities"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [Entity(entity_id=r[0], entity_type=r[1], name=r[2], properties=json.loads(r[3]), source_workflow=r[4], created_at=r[5]) for r in rows]

    def bfs(self, start_entity: str, max_depth: int = 3) -> list[Entity]:
        """Breadth-first traversal from start entity."""
        visited: set[str] = set()
        result: list[Entity] = []
        queue: deque[tuple[str, int]] = deque([(start_entity, 0)])

        while queue:
            eid, depth = queue.popleft()
            if eid in visited or depth > max_depth:
                continue
            visited.add(eid)
            entity = self.get_entity(eid)
            if entity:
                result.append(entity)
            if depth < max_depth:
                rels = self.get_relationships(eid)
                for rel in rels:
                    neighbor = rel.to_entity if rel.from_entity == eid else rel.from_entity
                    if neighbor not in visited:
                        queue.append((neighbor, depth + 1))
        return result

    def entity_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()
        return row[0] if row else 0

    def relationship_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM relationships").fetchone()
        return row[0] if row else 0
