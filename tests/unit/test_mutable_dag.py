"""Tests for mutable DAG."""

from __future__ import annotations

import threading

import pytest

from agentos.kernel.mutable_dag import CycleError, MutableDAG


@pytest.fixture
def dag() -> MutableDAG:
    return MutableDAG()


class TestNodeOperations:
    def test_add_node(self, dag):
        dag.add_node("a", {"type": "task"})
        assert dag.get_node("a") == {"type": "task"}
        assert dag.node_count == 1

    def test_add_node_idempotent(self, dag):
        dag.add_node("a", {"v": 1})
        dag.add_node("a", {"v": 2})
        assert dag.get_node("a") == {"v": 2}
        assert dag.node_count == 1

    def test_get_nonexistent(self, dag):
        assert dag.get_node("x") is None

    def test_remove_node(self, dag):
        dag.add_node("a")
        assert dag.remove_node("a") is True
        assert dag.node_count == 0

    def test_remove_nonexistent(self, dag):
        assert dag.remove_node("x") is False

    def test_remove_cleans_edges(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        dag.remove_node("b")
        assert dag.get_dependencies("c") == set()
        assert dag.get_dependents("a") == set()

    def test_list_nodes(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        assert set(dag.nodes()) == {"a", "b"}


class TestEdgeOperations:
    def test_add_edge(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_edge("a", "b")
        assert "a" in dag.get_dependencies("b")
        assert "b" in dag.get_dependents("a")

    def test_edge_count(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        assert dag.edge_count == 2

    def test_edge_missing_from_node(self, dag):
        dag.add_node("b")
        with pytest.raises(ValueError, match="Node not found"):
            dag.add_edge("a", "b")

    def test_edge_missing_to_node(self, dag):
        dag.add_node("a")
        with pytest.raises(ValueError, match="Node not found"):
            dag.add_edge("a", "b")

    def test_self_loop_raises(self, dag):
        dag.add_node("a")
        with pytest.raises(CycleError):
            dag.add_edge("a", "a")

    def test_cycle_raises(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        with pytest.raises(CycleError):
            dag.add_edge("c", "a")


class TestTopologicalSort:
    def test_linear(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_node("d")
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        dag.add_edge("b", "d")
        dag.add_edge("c", "d")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_empty(self, dag):
        assert dag.topological_sort() == []

    def test_single(self, dag):
        dag.add_node("a")
        assert dag.topological_sort() == ["a"]


class TestReadyNodes:
    def test_all_ready_no_deps(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        ready = dag.get_ready_nodes(set())
        assert set(ready) == {"a", "b"}

    def test_ready_with_completed_deps(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        dag.add_edge("a", "b")
        assert dag.get_ready_nodes(set()) == ["a"]
        assert dag.get_ready_nodes({"a"}) == ["b"]

    def test_skip_completed(self, dag):
        dag.add_node("a")
        dag.add_node("b")
        assert "a" not in dag.get_ready_nodes({"a"})


class TestConcurrency:
    def test_concurrent_inserts(self, dag):
        """Multiple threads adding nodes concurrently."""
        errors: list[Exception] = []

        def add_nodes(start: int, count: int):
            try:
                for i in range(start, start + count):
                    dag.add_node(f"node-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_nodes, args=(i * 50, 50)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert dag.node_count == 200

    def test_concurrent_edges(self, dag):
        """Add edges concurrently without cycles."""
        for i in range(100):
            dag.add_node(f"n{i}")

        errors: list[Exception] = []

        def add_edges(start: int):
            try:
                for i in range(start, min(start + 25, 99)):
                    dag.add_edge(f"n{i}", f"n{i + 1}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_edges, args=(i * 25,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors (all edges are forward, no cycles)
        assert not errors


class TestRuntimeInsertion:
    """Simulate runtime task insertion during execution."""

    def test_insert_task_mid_execution(self, dag):
        # Initial DAG: a -> b -> c
        dag.add_node("a")
        dag.add_node("b")
        dag.add_node("c")
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")

        # "a" completes, "b" is running
        completed = {"a"}
        assert dag.get_ready_nodes(completed) == ["b"]

        # Runtime insertion: add "d" between "b" and "c"
        dag.add_node("d", {"type": "dynamic"})
        dag.add_edge("b", "d")
        dag.add_edge("d", "c")

        # After "b" completes, "d" should be ready (not "c")
        completed.add("b")
        ready = dag.get_ready_nodes(completed)
        assert "d" in ready
        assert "c" not in ready

        # After "d" completes, "c" should be ready
        completed.add("d")
        ready = dag.get_ready_nodes(completed)
        assert "c" in ready

    def test_insert_parallel_branch(self, dag):
        # Initial: a -> c
        dag.add_node("a")
        dag.add_node("c")
        dag.add_edge("a", "c")

        # Insert parallel branch: a -> b -> c
        dag.add_node("b")
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")

        # "c" now needs both "a" and "b"
        assert dag.get_dependencies("c") == {"a", "b"}

        # Only "a" ready initially
        assert dag.get_ready_nodes(set()) == ["a"]

        # After "a", "b" is ready but "c" is not
        ready = dag.get_ready_nodes({"a"})
        assert "b" in ready
        assert "c" not in ready
