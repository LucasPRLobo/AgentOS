"""Semantic store — structured facts with provenance and conflict detection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agentos.core.identifiers import RunId


class Provenance(BaseModel):
    """Where a fact came from."""

    run_id: RunId
    task_name: str = ""
    tool_name: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Fact(BaseModel):
    """A single structured fact with provenance."""

    key: str = Field(description="Namespace-qualified key, e.g. 'model.accuracy'")
    value: Any
    provenance: Provenance
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    supersedes: str | None = Field(
        default=None, description="Fact ID this supersedes, if any"
    )


class ConflictRecord(BaseModel):
    """Records a conflict between two facts with the same key."""

    key: str
    fact_a: Fact
    fact_b: Fact
    resolved: bool = False
    resolution: str = ""


class SemanticStore:
    """Stores structured facts with provenance tracking and conflict detection.

    Facts are keyed by string. When a new fact conflicts with an existing one
    (same key, different value), the conflict is recorded and both facts are kept.
    """

    def __init__(self) -> None:
        self._facts: dict[str, list[Fact]] = {}
        self._conflicts: list[ConflictRecord] = []

    def add(self, fact: Fact) -> ConflictRecord | None:
        """Add a fact. Returns a ConflictRecord if it conflicts with an existing fact."""
        existing = self._facts.get(fact.key, [])

        conflict = None
        if existing:
            latest = existing[-1]
            if latest.value != fact.value:
                conflict = ConflictRecord(
                    key=fact.key, fact_a=latest, fact_b=fact
                )
                self._conflicts.append(conflict)

        self._facts.setdefault(fact.key, []).append(fact)
        return conflict

    def get(self, key: str) -> Fact | None:
        """Get the latest fact for a key, or None."""
        facts = self._facts.get(key, [])
        return facts[-1] if facts else None

    def get_history(self, key: str) -> list[Fact]:
        """Get all facts for a key, oldest first."""
        return list(self._facts.get(key, []))

    def query_by_prefix(self, prefix: str) -> dict[str, Fact]:
        """Get latest fact for all keys matching a prefix."""
        result: dict[str, Fact] = {}
        for key, facts in self._facts.items():
            if key.startswith(prefix) and facts:
                result[key] = facts[-1]
        return result

    def query_by_run(self, run_id: RunId) -> list[Fact]:
        """Get all facts produced by a specific run."""
        result: list[Fact] = []
        for facts in self._facts.values():
            for fact in facts:
                if fact.provenance.run_id == run_id:
                    result.append(fact)
        return result

    def get_conflicts(self, *, unresolved_only: bool = False) -> list[ConflictRecord]:
        """Get all conflict records."""
        if unresolved_only:
            return [c for c in self._conflicts if not c.resolved]
        return list(self._conflicts)

    def resolve_conflict(self, index: int, resolution: str) -> None:
        """Mark a conflict as resolved with a reason."""
        self._conflicts[index].resolved = True
        self._conflicts[index].resolution = resolution

    def keys(self) -> list[str]:
        """Return all keys with at least one fact."""
        return [k for k, v in self._facts.items() if v]

    def __len__(self) -> int:
        """Total number of unique keys."""
        return len(self._facts)
