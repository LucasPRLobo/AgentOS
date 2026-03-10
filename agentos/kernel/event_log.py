"""EventLog ABC and SQLiteEventLog implementation."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from typing import Callable

from agentos.schemas.events import EVENT_TABLE_DDL, Event, EventType


class EventLog(ABC):
    """Append-only event log interface.

    All state in AgentOS is derived from events. Implementations must
    guarantee ordering within a workflow (by seq) and reject duplicate
    (workflow_id, seq) pairs.
    """

    @abstractmethod
    def append(self, event: Event) -> None:
        """Append an event to the log.

        Raises ValueError if (workflow_id, seq) already exists.
        """

    @abstractmethod
    def query(
        self,
        workflow_id: str | None = None,
        event_type: EventType | str | None = None,
        since_seq: int | None = None,
    ) -> list[Event]:
        """Query events with optional filters, ordered by seq."""

    @abstractmethod
    def replay(self, workflow_id: str) -> list[Event]:
        """Return all events for a workflow, ordered by seq."""

    @abstractmethod
    def last_seq(self, workflow_id: str) -> int:
        """Return the highest seq for a workflow, or -1 if none."""

    @abstractmethod
    def subscribe(self, callback: Callable[[Event], None]) -> str:
        """Subscribe to new events. Returns subscription ID."""

    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""


class SQLiteEventLog(EventLog):
    """SQLite-backed event log with WAL mode."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(EVENT_TABLE_DDL)
        self._lock = threading.Lock()
        self._subscribers: dict[str, Callable[[Event], None]] = {}

    def append(self, event: Event) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO events
                       (event_id, event_type, workflow_id, seq,
                        timestamp, schema_version, payload, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event.event_id,
                        str(event.event_type),
                        event.workflow_id,
                        event.seq,
                        event.timestamp.isoformat(),
                        event.schema_version,
                        json.dumps(event.payload),
                        json.dumps(event.metadata),
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Duplicate (workflow_id={event.workflow_id!r}, seq={event.seq})"
                ) from exc

        # Notify subscribers (outside the lock to avoid deadlocks)
        for callback in list(self._subscribers.values()):
            try:
                callback(event)
            except Exception:
                pass  # Subscriber errors must not block event logging

    def query(
        self,
        workflow_id: str | None = None,
        event_type: EventType | str | None = None,
        since_seq: int | None = None,
    ) -> list[Event]:
        clauses: list[str] = []
        params: list[object] = []

        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(str(event_type))
        if since_seq is not None:
            clauses.append("seq >= ?")
            params.append(since_seq)

        sql = "SELECT event_id, event_type, workflow_id, seq, timestamp, schema_version, payload, metadata FROM events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq"

        with self._lock:
            # End any implicit transaction so we see writes from other processes
            self._conn.rollback()
            rows = self._conn.execute(sql, params).fetchall()

        return [self._row_to_event(row) for row in rows]

    def replay(self, workflow_id: str) -> list[Event]:
        return self.query(workflow_id=workflow_id)

    def last_seq(self, workflow_id: str) -> int:
        with self._lock:
            self._conn.rollback()
            row = self._conn.execute(
                "SELECT MAX(seq) FROM events WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return -1
        return row[0]

    def subscribe(self, callback: Callable[[Event], None]) -> str:
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        self._subscribers.pop(subscription_id, None)

    @staticmethod
    def _row_to_event(row: tuple) -> Event:
        return Event(
            event_id=row[0],
            event_type=EventType(row[1]),
            workflow_id=row[2],
            seq=row[3],
            timestamp=row[4],
            schema_version=row[5],
            payload=json.loads(row[6]),
            metadata=json.loads(row[7]),
        )
