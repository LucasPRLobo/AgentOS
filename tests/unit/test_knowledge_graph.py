"""Tests for knowledge graph store."""

from __future__ import annotations

import pytest

from agentos.intelligence.knowledge_graph import SQLiteKnowledgeGraph


@pytest.fixture
def kg() -> SQLiteKnowledgeGraph:
    return SQLiteKnowledgeGraph()


class TestEntityCRUD:
    def test_add_entity(self, kg):
        e = kg.add_entity("person", "Alice", {"role": "researcher"})
        assert e.entity_id
        assert e.name == "Alice"
        assert e.properties == {"role": "researcher"}

    def test_get_entity(self, kg):
        e = kg.add_entity("person", "Alice")
        retrieved = kg.get_entity(e.entity_id)
        assert retrieved is not None
        assert retrieved.name == "Alice"

    def test_get_nonexistent(self, kg):
        assert kg.get_entity("nonexistent") is None

    def test_entity_count(self, kg):
        assert kg.entity_count() == 0
        kg.add_entity("person", "Alice")
        kg.add_entity("person", "Bob")
        assert kg.entity_count() == 2

    def test_search_by_type(self, kg):
        kg.add_entity("person", "Alice")
        kg.add_entity("tool", "Hammer")
        kg.add_entity("person", "Bob")
        results = kg.search_entities(entity_type="person")
        assert len(results) == 2

    def test_search_by_name(self, kg):
        kg.add_entity("person", "Alice Smith")
        kg.add_entity("person", "Bob Jones")
        results = kg.search_entities(name_pattern="Alice")
        assert len(results) == 1
        assert results[0].name == "Alice Smith"

    def test_search_combined(self, kg):
        kg.add_entity("person", "Alice")
        kg.add_entity("tool", "Alice's Hammer")
        results = kg.search_entities(entity_type="person", name_pattern="Alice")
        assert len(results) == 1


class TestRelationships:
    def test_add_relationship(self, kg):
        a = kg.add_entity("person", "Alice")
        b = kg.add_entity("person", "Bob")
        r = kg.add_relationship(a.entity_id, b.entity_id, "knows")
        assert r.relation_type == "knows"
        assert r.from_entity == a.entity_id
        assert r.to_entity == b.entity_id

    def test_get_relationships(self, kg):
        a = kg.add_entity("person", "Alice")
        b = kg.add_entity("person", "Bob")
        kg.add_relationship(a.entity_id, b.entity_id, "knows")
        rels = kg.get_relationships(a.entity_id)
        assert len(rels) == 1
        assert rels[0].relation_type == "knows"

    def test_bidirectional_lookup(self, kg):
        a = kg.add_entity("person", "Alice")
        b = kg.add_entity("person", "Bob")
        kg.add_relationship(a.entity_id, b.entity_id, "knows")
        # Both sides should see the relationship
        assert len(kg.get_relationships(a.entity_id)) == 1
        assert len(kg.get_relationships(b.entity_id)) == 1

    def test_relationship_count(self, kg):
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        c = kg.add_entity("person", "C")
        kg.add_relationship(a.entity_id, b.entity_id, "r1")
        kg.add_relationship(b.entity_id, c.entity_id, "r2")
        assert kg.relationship_count() == 2

    def test_relationship_properties(self, kg):
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        r = kg.add_relationship(a.entity_id, b.entity_id, "works_with", {"since": "2024"})
        assert r.properties == {"since": "2024"}


class TestObservations:
    def test_add_observation(self, kg):
        e = kg.add_entity("concept", "ML")
        obs = kg.add_observation(e.entity_id, "ML is used for prediction", confidence=0.9)
        assert obs.content == "ML is used for prediction"
        assert obs.confidence == 0.9

    def test_get_observations(self, kg):
        e = kg.add_entity("concept", "ML")
        kg.add_observation(e.entity_id, "Observation 1")
        kg.add_observation(e.entity_id, "Observation 2")
        obs = kg.get_observations(e.entity_id)
        assert len(obs) == 2

    def test_observation_provenance(self, kg):
        e = kg.add_entity("concept", "ML")
        obs = kg.add_observation(e.entity_id, "Finding", source_workflow="wf-1")
        assert obs.source_workflow == "wf-1"


class TestBFS:
    def test_bfs_simple(self, kg):
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        c = kg.add_entity("person", "C")
        kg.add_relationship(a.entity_id, b.entity_id, "knows")
        kg.add_relationship(b.entity_id, c.entity_id, "knows")
        result = kg.bfs(a.entity_id, max_depth=3)
        names = {e.name for e in result}
        assert names == {"A", "B", "C"}

    def test_bfs_depth_limit(self, kg):
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        c = kg.add_entity("person", "C")
        kg.add_relationship(a.entity_id, b.entity_id, "knows")
        kg.add_relationship(b.entity_id, c.entity_id, "knows")
        result = kg.bfs(a.entity_id, max_depth=1)
        names = {e.name for e in result}
        assert "A" in names
        assert "B" in names
        assert "C" not in names

    def test_bfs_single_node(self, kg):
        a = kg.add_entity("person", "A")
        result = kg.bfs(a.entity_id)
        assert len(result) == 1

    def test_bfs_cycle_safe(self, kg):
        a = kg.add_entity("person", "A")
        b = kg.add_entity("person", "B")
        kg.add_relationship(a.entity_id, b.entity_id, "knows")
        kg.add_relationship(b.entity_id, a.entity_id, "knows_back")
        result = kg.bfs(a.entity_id)
        assert len(result) == 2


class TestCrossRunAccumulation:
    def test_multiple_workflows_accumulate(self, kg):
        # Workflow 1 adds entities
        e1 = kg.add_entity("finding", "API rate limit", source_workflow="wf-1")
        kg.add_observation(e1.entity_id, "Rate limit is 100/min", source_workflow="wf-1")

        # Workflow 2 adds more
        e2 = kg.add_entity("finding", "Auth method", source_workflow="wf-2")
        kg.add_observation(e2.entity_id, "Uses JWT tokens", source_workflow="wf-2")
        kg.add_relationship(e1.entity_id, e2.entity_id, "related_to", source_workflow="wf-2")

        assert kg.entity_count() == 2
        assert kg.relationship_count() == 1

        # Can traverse across workflow boundaries
        result = kg.bfs(e1.entity_id)
        assert len(result) == 2
