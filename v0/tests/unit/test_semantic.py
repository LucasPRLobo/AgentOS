"""Tests for SemanticStore — facts, provenance, and conflict detection."""

from agentos.core.identifiers import RunId, generate_run_id
from agentos.memory.semantic import Fact, Provenance, SemanticStore


def _make_fact(key: str, value: object, run_id: RunId | None = None) -> Fact:
    return Fact(
        key=key,
        value=value,
        provenance=Provenance(
            run_id=run_id or generate_run_id(),
            task_name="test_task",
        ),
    )


class TestSemanticStoreBasic:
    def test_add_and_get(self) -> None:
        store = SemanticStore()
        fact = _make_fact("model.accuracy", 0.95)
        store.add(fact)

        retrieved = store.get("model.accuracy")
        assert retrieved is not None
        assert retrieved.value == 0.95

    def test_get_nonexistent(self) -> None:
        store = SemanticStore()
        assert store.get("missing") is None

    def test_latest_wins(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        store.add(_make_fact("x", 2))

        assert store.get("x") is not None
        assert store.get("x").value == 2

    def test_history(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        store.add(_make_fact("x", 2))
        store.add(_make_fact("x", 3))

        history = store.get_history("x")
        assert len(history) == 3
        assert [f.value for f in history] == [1, 2, 3]

    def test_keys(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("a", 1))
        store.add(_make_fact("b", 2))

        assert sorted(store.keys()) == ["a", "b"]

    def test_len(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("a", 1))
        store.add(_make_fact("b", 2))
        assert len(store) == 2


class TestSemanticStoreConflicts:
    def test_no_conflict_same_value(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        conflict = store.add(_make_fact("x", 1))
        assert conflict is None

    def test_conflict_different_value(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        conflict = store.add(_make_fact("x", 2))

        assert conflict is not None
        assert conflict.key == "x"
        assert conflict.fact_a.value == 1
        assert conflict.fact_b.value == 2
        assert conflict.resolved is False

    def test_get_conflicts(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        store.add(_make_fact("x", 2))
        store.add(_make_fact("y", "a"))
        store.add(_make_fact("y", "b"))

        conflicts = store.get_conflicts()
        assert len(conflicts) == 2

    def test_unresolved_only(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        store.add(_make_fact("x", 2))
        store.add(_make_fact("y", "a"))
        store.add(_make_fact("y", "b"))

        store.resolve_conflict(0, "Newer is correct")

        unresolved = store.get_conflicts(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].key == "y"

    def test_resolve_conflict(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("x", 1))
        store.add(_make_fact("x", 2))

        store.resolve_conflict(0, "Updated value is correct")
        conflicts = store.get_conflicts()
        assert conflicts[0].resolved is True
        assert conflicts[0].resolution == "Updated value is correct"


class TestSemanticStoreQueries:
    def test_query_by_prefix(self) -> None:
        store = SemanticStore()
        store.add(_make_fact("model.accuracy", 0.95))
        store.add(_make_fact("model.loss", 0.05))
        store.add(_make_fact("data.rows", 1000))

        results = store.query_by_prefix("model.")
        assert len(results) == 2
        assert "model.accuracy" in results
        assert "model.loss" in results

    def test_query_by_run(self) -> None:
        store = SemanticStore()
        rid = generate_run_id()
        store.add(_make_fact("a", 1, run_id=rid))
        store.add(_make_fact("b", 2, run_id=rid))
        store.add(_make_fact("c", 3))  # different run

        results = store.query_by_run(rid)
        assert len(results) == 2
        assert all(f.provenance.run_id == rid for f in results)

    def test_provenance_tracking(self) -> None:
        store = SemanticStore()
        rid = generate_run_id()
        fact = Fact(
            key="result",
            value=42,
            provenance=Provenance(
                run_id=rid, task_name="compute", tool_name="calculator"
            ),
            confidence=0.9,
        )
        store.add(fact)

        retrieved = store.get("result")
        assert retrieved is not None
        assert retrieved.provenance.run_id == rid
        assert retrieved.provenance.task_name == "compute"
        assert retrieved.provenance.tool_name == "calculator"
        assert retrieved.confidence == 0.9
