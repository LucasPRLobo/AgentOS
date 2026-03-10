"""Thread-safe Mutable DAG — supports runtime task insertion."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


class CycleError(Exception):
    """Raised when an operation would create a cycle in the DAG."""


class MutableDAG:
    """Thread-safe directed acyclic graph that supports runtime modifications.

    Tasks can be added and wired during execution. All mutations are
    atomic (protected by a lock) and can emit events for replay.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # node -> set of dependencies
        self._reverse_edges: dict[str, set[str]] = defaultdict(set)  # node -> set of dependents

    def add_node(self, node_id: str, data: dict[str, Any] | None = None) -> None:
        """Add a node to the DAG. Idempotent — re-adding updates data."""
        with self._lock:
            self._nodes[node_id] = data or {}
            if node_id not in self._edges:
                self._edges[node_id] = set()

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a directed edge (from_node must complete before to_node).

        Raises CycleError if this would create a cycle.
        Raises ValueError if either node doesn't exist.
        """
        with self._lock:
            if from_node not in self._nodes:
                raise ValueError(f"Node not found: {from_node}")
            if to_node not in self._nodes:
                raise ValueError(f"Node not found: {to_node}")

            # Check for cycle: can we reach from_node from to_node?
            if self._would_create_cycle(from_node, to_node):
                raise CycleError(f"Edge {from_node} -> {to_node} would create a cycle")

            self._edges[to_node].add(from_node)
            self._reverse_edges[from_node].add(to_node)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges. Returns True if found."""
        with self._lock:
            if node_id not in self._nodes:
                return False

            # Remove all edges involving this node
            for dep in list(self._edges.get(node_id, set())):
                self._reverse_edges[dep].discard(node_id)
            del self._edges[node_id]

            for dependent in list(self._reverse_edges.get(node_id, set())):
                self._edges[dependent].discard(node_id)
            if node_id in self._reverse_edges:
                del self._reverse_edges[node_id]

            del self._nodes[node_id]
            return True

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get node data."""
        with self._lock:
            return self._nodes.get(node_id)

    def get_dependencies(self, node_id: str) -> set[str]:
        """Get the set of nodes that must complete before node_id."""
        with self._lock:
            return set(self._edges.get(node_id, set()))

    def get_dependents(self, node_id: str) -> set[str]:
        """Get the set of nodes that depend on node_id."""
        with self._lock:
            return set(self._reverse_edges.get(node_id, set()))

    def get_ready_nodes(self, completed: set[str]) -> list[str]:
        """Get nodes whose dependencies are all in the completed set."""
        with self._lock:
            ready = []
            for node_id in self._nodes:
                if node_id in completed:
                    continue
                deps = self._edges.get(node_id, set())
                if deps <= completed:
                    ready.append(node_id)
            return ready

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order. Raises CycleError if cycle exists."""
        with self._lock:
            in_degree: dict[str, int] = {n: 0 for n in self._nodes}
            for node, deps in self._edges.items():
                in_degree[node] = len(deps)

            queue = [n for n, d in in_degree.items() if d == 0]
            result: list[str] = []

            while queue:
                node = queue.pop(0)
                result.append(node)
                for dependent in self._reverse_edges.get(node, set()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            if len(result) != len(self._nodes):
                raise CycleError("DAG contains a cycle")

            return result

    @property
    def node_count(self) -> int:
        with self._lock:
            return len(self._nodes)

    @property
    def edge_count(self) -> int:
        with self._lock:
            return sum(len(deps) for deps in self._edges.values())

    def nodes(self) -> list[str]:
        with self._lock:
            return list(self._nodes.keys())

    def _would_create_cycle(self, from_node: str, to_node: str) -> bool:
        """Check if adding from_node -> to_node would create a cycle.

        This means: can we reach from_node starting from to_node
        using existing edges? If yes, adding this edge creates a cycle.
        """
        if from_node == to_node:
            return True

        visited: set[str] = set()
        stack = [to_node]
        while stack:
            current = stack.pop()
            if current == from_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            # Follow reverse edges (dependents of current)
            for dep in self._reverse_edges.get(current, set()):
                stack.append(dep)

        return False
