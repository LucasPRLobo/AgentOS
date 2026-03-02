"""Tests for ContextPackBuilder — claims, evidence, freshness, conflicts."""

from agentos.core.identifiers import generate_run_id
from agentos.memory.context_pack import ContextPackBuilder
from agentos.memory.semantic import Fact, Provenance, SemanticStore


def _fact(key: str, value: object, **kwargs: object) -> Fact:
    return Fact(
        key=key,
        value=value,
        provenance=Provenance(run_id=generate_run_id(), task_name="t", **kwargs),
    )


class TestContextPackBuilder:
    def test_build_all_keys(self) -> None:
        store = SemanticStore()
        store.add(_fact("a", 1))
        store.add(_fact("b", 2))

        builder = ContextPackBuilder(store)
        pack = builder.build()

        assert len(pack.claims) == 2
        keys = {c.key for c in pack.claims}
        assert keys == {"a", "b"}

    def test_build_specific_keys(self) -> None:
        store = SemanticStore()
        store.add(_fact("a", 1))
        store.add(_fact("b", 2))
        store.add(_fact("c", 3))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["a", "c"])

        assert len(pack.claims) == 2
        keys = {c.key for c in pack.claims}
        assert keys == {"a", "c"}

    def test_build_for_prefix(self) -> None:
        store = SemanticStore()
        store.add(_fact("model.acc", 0.95))
        store.add(_fact("model.loss", 0.05))
        store.add(_fact("data.rows", 100))

        builder = ContextPackBuilder(store)
        pack = builder.build_for_prefix("model.")

        assert len(pack.claims) == 2

    def test_missing_key_skipped(self) -> None:
        store = SemanticStore()
        store.add(_fact("a", 1))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["a", "nonexistent"])

        assert len(pack.claims) == 1


class TestClaimEvidence:
    def test_evidence_includes_history(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))
        store.add(_fact("x", 2))
        store.add(_fact("x", 3))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["x"])

        claim = pack.claims[0]
        assert claim.value == 3  # latest
        assert len(claim.evidence) == 3

    def test_latest_has_full_relevance(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))
        store.add(_fact("x", 2))

        builder = ContextPackBuilder(store)
        pack = builder.build(keys=["x"])

        claim = pack.claims[0]
        # Latest fact should have relevance 1.0
        latest_evidence = [e for e in claim.evidence if e.fact.value == 2]
        assert len(latest_evidence) == 1
        assert latest_evidence[0].relevance == 1.0

        # Older fact should have reduced relevance
        older_evidence = [e for e in claim.evidence if e.fact.value == 1]
        assert len(older_evidence) == 1
        assert older_evidence[0].relevance == 0.5


class TestClaimConflicts:
    def test_no_conflicts(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))

        builder = ContextPackBuilder(store)
        pack = builder.build()

        assert len(pack.conflicted_claims) == 0
        assert len(pack.clean_claims) == 1

    def test_conflict_attached(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))
        store.add(_fact("x", 2))

        builder = ContextPackBuilder(store)
        pack = builder.build()

        assert len(pack.conflicted_claims) == 1
        claim = pack.conflicted_claims[0]
        assert claim.has_conflicts is True
        assert len(claim.conflicts) == 1

    def test_unresolved_conflicts(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))
        store.add(_fact("x", 2))

        builder = ContextPackBuilder(store)
        pack = builder.build()

        claim = pack.claims[0]
        assert len(claim.unresolved_conflicts) == 1

    def test_resolved_conflict_not_in_unresolved(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))
        store.add(_fact("x", 2))
        store.resolve_conflict(0, "newer is correct")

        builder = ContextPackBuilder(store)
        pack = builder.build()

        claim = pack.claims[0]
        assert claim.has_conflicts is True  # still recorded
        assert len(claim.unresolved_conflicts) == 0  # but resolved


class TestClaimConfidence:
    def test_single_fact_confidence(self) -> None:
        store = SemanticStore()
        store.add(
            Fact(
                key="x",
                value=1,
                provenance=Provenance(run_id=generate_run_id()),
                confidence=0.8,
            )
        )

        builder = ContextPackBuilder(store)
        pack = builder.build()
        assert pack.claims[0].confidence == pytest.approx(0.8)

    def test_conflict_reduces_confidence(self) -> None:
        store = SemanticStore()
        store.add(
            Fact(
                key="x",
                value=1,
                provenance=Provenance(run_id=generate_run_id()),
                confidence=0.9,
            )
        )
        store.add(
            Fact(
                key="x",
                value=2,
                provenance=Provenance(run_id=generate_run_id()),
                confidence=0.9,
            )
        )

        builder = ContextPackBuilder(store)
        pack = builder.build()

        claim = pack.claims[0]
        # Confidence should be reduced by unresolved conflict
        assert claim.confidence < 0.9

    def test_no_evidence_zero_confidence(self) -> None:
        claim = Claim(key="empty", value=None)
        assert claim.confidence == 0.0


class TestFreshness:
    def test_recent_fact_high_freshness(self) -> None:
        store = SemanticStore()
        store.add(_fact("x", 1))

        builder = ContextPackBuilder(store, max_age_seconds=3600.0)
        pack = builder.build()

        # Just created, should be very fresh
        assert pack.claims[0].freshness_score > 0.99


# Need these imports for the test
import pytest
from agentos.memory.context_pack import Claim
