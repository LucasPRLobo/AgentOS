"""Event log — append-only event persistence with SQLite backend."""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from agentos.core.identifiers import RunId
from agentos.schemas.events import BaseEvent, EventType


class EventLog(ABC):
    """Abstract interface for the append-only event log."""

    @abstractmethod
    def append(self, event: BaseEvent) -> None:
        """Append an event to the log. Must preserve ordering."""

    @abstractmethod
    def query_by_run(self, run_id: RunId) -> list[BaseEvent]:
        """Return all events for a run, ordered by sequence number."""

    @abstractmethod
    def query_by_type(self, run_id: RunId, event_type: EventType) -> list[BaseEvent]:
        """Return events of a specific type for a run."""

    @abstractmethod
    def replay(self, run_id: RunId) -> list[BaseEvent]:
        """Return full ordered event stream for deterministic replay."""


class SQLiteEventLog(EventLog):
    """SQLite-backed implementation of the event log."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            )
            """
        )
        self._conn.commit()

    def append(self, event: BaseEvent) -> None:
        """Append an event to the log. Thread-safe."""
        payload_json = event.model_dump_json()
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (run_id, seq, timestamp, event_type, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.run_id,
                    event.seq,
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    payload_json,
                ),
            )
            self._conn.commit()

    def _rows_to_events(self, rows: list[tuple[str, ...]]) -> list[BaseEvent]:
        return [BaseEvent.model_validate_json(row[4]) for row in rows]

    def query_by_run(self, run_id: RunId) -> list[BaseEvent]:
        """Return all events for a run, ordered by sequence number."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT run_id, seq, timestamp, event_type, payload_json "
                "FROM events WHERE run_id = ? ORDER BY seq",
                (run_id,),
            )
            return self._rows_to_events(cursor.fetchall())

    def query_by_type(self, run_id: RunId, event_type: EventType) -> list[BaseEvent]:
        """Return events of a specific type for a run."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT run_id, seq, timestamp, event_type, payload_json "
                "FROM events WHERE run_id = ? AND event_type = ? ORDER BY seq",
                (run_id, event_type.value),
            )
            return self._rows_to_events(cursor.fetchall())

    def replay(self, run_id: RunId) -> list[BaseEvent]:
        """Return full ordered event stream for deterministic replay."""
        return self.query_by_run(run_id)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
