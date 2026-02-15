"""Tests for the filesystem-based workflow store."""

from pathlib import Path

import pytest

from agentplatform.workflow_store import WorkflowStore, WorkflowSummary
from agentos.schemas.workflow import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeConfig,
)


def _make_workflow(name: str = "Test Workflow", wf_id: str | None = None) -> WorkflowDefinition:
    nodes = [
        WorkflowNode(
            id="n1", role="researcher", display_name="Researcher",
            config=WorkflowNodeConfig(model="gpt-4o-mini"),
        ),
        WorkflowNode(
            id="n2", role="writer", display_name="Writer",
            config=WorkflowNodeConfig(model="gpt-4o-mini"),
        ),
    ]
    edges = [WorkflowEdge(source="n1", target="n2")]
    kwargs: dict = {"name": name, "nodes": nodes, "edges": edges}
    if wf_id:
        kwargs["id"] = wf_id
    return WorkflowDefinition(**kwargs)


class TestWorkflowStore:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> WorkflowStore:
        return WorkflowStore(str(tmp_path / "workflows"))

    def test_save_and_load(self, store: WorkflowStore) -> None:
        wf = _make_workflow()
        store.save(wf)
        loaded = store.load(wf.id)
        assert loaded.name == wf.name
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1

    def test_load_nonexistent_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            store.load("nonexistent-id")

    def test_list_empty(self, store: WorkflowStore) -> None:
        assert store.list() == []

    def test_list_after_save(self, store: WorkflowStore) -> None:
        wf1 = _make_workflow("First")
        wf2 = _make_workflow("Second")
        store.save(wf1)
        store.save(wf2)
        listing = store.list()
        assert len(listing) == 2
        names = {s.name for s in listing}
        assert "First" in names
        assert "Second" in names

    def test_delete(self, store: WorkflowStore) -> None:
        wf = _make_workflow()
        store.save(wf)
        assert store.exists(wf.id)
        store.delete(wf.id)
        assert not store.exists(wf.id)

    def test_delete_nonexistent_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            store.delete("nonexistent-id")

    def test_clone(self, store: WorkflowStore) -> None:
        original = _make_workflow("Original")
        store.save(original)
        cloned = store.clone(original.id)
        assert cloned.id != original.id
        assert cloned.name == "Original (copy)"
        assert cloned.template_source == original.id
        assert store.exists(cloned.id)

    def test_clone_nonexistent_raises(self, store: WorkflowStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.clone("nonexistent-id")

    def test_exists(self, store: WorkflowStore) -> None:
        wf = _make_workflow()
        assert not store.exists(wf.id)
        store.save(wf)
        assert store.exists(wf.id)

    def test_creates_directory(self, store: WorkflowStore) -> None:
        assert not store.base_dir.exists()
        store.save(_make_workflow())
        assert store.base_dir.exists()

    def test_updated_at_changes_on_save(self, store: WorkflowStore) -> None:
        wf = _make_workflow()
        store.save(wf)
        first = store.load(wf.id)

        import time
        time.sleep(0.01)
        store.save(wf)
        second = store.load(wf.id)
        assert second.updated_at >= first.updated_at
