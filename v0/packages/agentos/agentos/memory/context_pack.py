"""Context pack builder — assemble evidence packs for decision-making."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agentos.memory.semantic import ConflictRecord, Fact, SemanticStore


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting or contradicting a claim."""

    fact: Fact
    relevance: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def age_seconds(self) -> float:
        """Seconds since the fact was recorded."""
        return (datetime.now(UTC) - self.fact.provenance.timestamp).total_seconds()


class Claim(BaseModel):
    """A claim with supporting evidence, freshness, and conflict markers."""

    key: str
    value: object
    evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    freshness_score: float = Field(
        ge=0.0, le=1.0, default=1.0, description="1.0 = just produced, 0.0 = stale"
    )

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0

    @property
    def unresolved_conflicts(self) -> list[ConflictRecord]:
        return [c for c in self.conflicts if not c.resolved]

    @property
    def confidence(self) -> float:
        """Average confidence across evidence, penalized by unresolved conflicts."""
        if not self.evidence:
            return 0.0
        avg = sum(e.fact.confidence * e.relevance for e in self.evidence) / len(
            self.evidence
        )
        penalty = 0.1 * len(self.unresolved_conflicts)
        return max(0.0, avg - penalty)


class ContextPack(BaseModel):
    """A collection of claims assembled for a specific context."""

    claims: list[Claim] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def conflicted_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.has_conflicts]

    @property
    def clean_claims(self) -> list[Claim]:
        return [c for c in self.claims if not c.has_conflicts]


def _compute_freshness(fact: Fact, max_age_seconds: float) -> float:
    """Compute freshness score: 1.0 = just produced, decays toward 0.0."""
    age = (datetime.now(UTC) - fact.provenance.timestamp).total_seconds()
    if age <= 0 or max_age_seconds <= 0:
        return 1.0
    return max(0.0, 1.0 - (age / max_age_seconds))


class ContextPackBuilder:
    """Builds context packs from a semantic store.

    Assembles claims from facts, computes freshness scores, and
    attaches conflict markers.
    """

    def __init__(
        self,
        semantic_store: SemanticStore,
        *,
        max_age_seconds: float = 3600.0,
    ) -> None:
        self._store = semantic_store
        self._max_age_seconds = max_age_seconds

    def build(self, keys: list[str] | None = None) -> ContextPack:
        """Build a context pack for the given keys (or all keys if None)."""
        target_keys = keys if keys is not None else self._store.keys()
        claims: list[Claim] = []

        all_conflicts = self._store.get_conflicts()

        for key in target_keys:
            fact = self._store.get(key)
            if fact is None:
                continue

            history = self._store.get_history(key)
            evidence = [
                EvidenceItem(fact=f, relevance=1.0 if f is fact else 0.5)
                for f in history
            ]

            key_conflicts = [c for c in all_conflicts if c.key == key]
            freshness = _compute_freshness(fact, self._max_age_seconds)

            claims.append(
                Claim(
                    key=key,
                    value=fact.value,
                    evidence=evidence,
                    conflicts=key_conflicts,
                    freshness_score=freshness,
                )
            )

        return ContextPack(claims=claims)

    def build_for_prefix(self, prefix: str) -> ContextPack:
        """Build a context pack for all keys matching a prefix."""
        matching = self._store.query_by_prefix(prefix)
        return self.build(list(matching.keys()))
