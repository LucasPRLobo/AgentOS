"""V3 integration tests — dynamic composition, knowledge graph, learning."""

from __future__ import annotations

import uuid

import pytest

from agentos.intelligence.knowledge_graph import SQLiteKnowledgeGraph
from agentos.intelligence.learning import (
    ConfigRecommender,
    PatternDetector,
    WorkflowRecord,
)
from agentos.kernel.mutable_dag import MutableDAG
from agentos.kernel.team_composer import TeamComposer
from agentos.schemas.spawn import AgentArchetype, SpawnPolicy, SpawnStatus


class TestDynamicCompositionE2E:
    """Agent spawns new agent mid-workflow, output feeds downstream."""

    def test_spawn_and_wire_into_dag(self):
        # Set up DAG: research -> summarize
        dag = MutableDAG()
        dag.add_node("research", {"type": "task"})
        dag.add_node("summarize", {"type": "task"})
        dag.add_edge("research", "summarize")

        # Set up team composer
        policy = SpawnPolicy(allow_spawn=True, require_approval=False, max_spawns_per_workflow=3)
        archetypes = {"reviewer": AgentArchetype(name="reviewer", role="Code reviewer")}
        composer = TeamComposer(policy, archetypes)

        # Research agent requests a reviewer
        spawn_req = composer.request_spawn("research", "reviewer", "Need code review")
        assert spawn_req.status == SpawnStatus.APPROVED  # Auto-approved

        # Provision the new agent
        config = composer.provision(spawn_req.request_id)
        new_agent_id = config["agent_id"]

        # Wire new agent into DAG: research -> review -> summarize
        dag.add_node(new_agent_id, {"type": "task", "spawned": True})
        dag.add_edge("research", new_agent_id)
        dag.add_edge(new_agent_id, "summarize")

        # Verify topology
        order = dag.topological_sort()
        assert order.index("research") < order.index(new_agent_id)
        assert order.index(new_agent_id) < order.index("summarize")

        # Verify ready nodes flow
        assert dag.get_ready_nodes(set()) == ["research"]
        assert new_agent_id in dag.get_ready_nodes({"research"})
        assert "summarize" not in dag.get_ready_nodes({"research"})
        assert "summarize" in dag.get_ready_nodes({"research", new_agent_id})

    def test_multiple_spawns_with_dag(self):
        dag = MutableDAG()
        dag.add_node("start", {"type": "task"})
        dag.add_node("end", {"type": "task"})
        dag.add_edge("start", "end")

        policy = SpawnPolicy(allow_spawn=True, require_approval=False, max_spawns_per_workflow=5)
        archetypes = {"worker": AgentArchetype(name="worker")}
        composer = TeamComposer(policy, archetypes)

        # Spawn 3 parallel workers
        workers = []
        for i in range(3):
            req = composer.request_spawn("start", "worker", f"Worker {i}")
            config = composer.provision(req.request_id)
            wid = config["agent_id"]
            workers.append(wid)
            dag.add_node(wid, {"type": "spawned"})
            dag.add_edge("start", wid)
            dag.add_edge(wid, "end")

        assert dag.node_count == 5  # start + 3 workers + end
        assert composer.spawn_count == 3

        # After start, all workers are ready
        ready = dag.get_ready_nodes({"start"})
        assert set(ready) == set(workers)


class TestKnowledgeGraphAccumulation:
    """Knowledge graph populated across 5+ runs."""

    def test_five_runs_accumulate(self):
        kg = SQLiteKnowledgeGraph()

        for run in range(5):
            wf_id = f"wf-{run}"
            # Each run discovers an entity and adds observations
            entity = kg.add_entity("finding", f"Finding from run {run}", source_workflow=wf_id)
            kg.add_observation(entity.entity_id, f"Detail from run {run}", confidence=0.8, source_workflow=wf_id)

            # Connect to previous run's entity
            if run > 0:
                prev_entities = kg.search_entities(name_pattern=f"run {run - 1}")
                if prev_entities:
                    kg.add_relationship(prev_entities[0].entity_id, entity.entity_id, "leads_to", source_workflow=wf_id)

        assert kg.entity_count() == 5
        assert kg.relationship_count() == 4

        # BFS from first entity should reach all
        first_entities = kg.search_entities(name_pattern="run 0")
        result = kg.bfs(first_entities[0].entity_id, max_depth=10)
        assert len(result) == 5


class TestLearningFromHistory:
    """Learning recommendations validated against historical data."""

    def test_recommendations_from_10_runs(self):
        detector = PatternDetector()

        # 10 runs with varying team sizes and outcomes
        for i in range(10):
            team = ["agent-a", "agent-b"] if i < 5 else ["agent-a", "agent-b", "agent-c"]
            quality = 0.6 + (i * 0.03) if i < 5 else 0.8 + (i - 5) * 0.02
            detector.add_record(WorkflowRecord(
                workflow_id=f"wf-{i}",
                workflow_name="test",
                team_composition=team,
                total_cost_usd=0.05 * (len(team)),
                total_duration_seconds=30.0 * len(team),
                quality_score=quality,
                success=quality > 0.6,
            ))

        patterns = detector.detect_patterns()
        assert len(patterns) > 0

        recommender = ConfigRecommender()
        recs = recommender.recommend(patterns, detector._records)
        assert len(recs) > 0
        # Should have budget recommendations
        assert any(r.category == "budget" for r in recs)

    def test_detect_failing_composition(self):
        detector = PatternDetector()

        # Failing team composition
        for i in range(5):
            detector.add_record(WorkflowRecord(
                workflow_id=f"fail-{i}",
                workflow_name="test",
                team_composition=["bad-agent"],
                total_cost_usd=0.1,
                total_duration_seconds=60.0,
                quality_score=0.3,
                success=False,
            ))

        patterns = detector.detect_patterns()
        fail_patterns = [p for p in patterns if "success rate" in p.description.lower()]
        assert len(fail_patterns) >= 1


class TestFullV3Flow:
    """Complete V3 flow: spawn → execute → learn → recommend."""

    def test_end_to_end(self):
        # 1. Set up mutable DAG
        dag = MutableDAG()
        dag.add_node("analyze")
        dag.add_node("report")
        dag.add_edge("analyze", "report")

        # 2. Spawn a new agent dynamically
        policy = SpawnPolicy(allow_spawn=True, require_approval=False)
        composer = TeamComposer(policy, {"helper": AgentArchetype(name="helper")})
        req = composer.request_spawn("analyze", "helper", "Need help")
        config = composer.provision(req.request_id)
        dag.add_node(config["agent_id"])
        dag.add_edge("analyze", config["agent_id"])
        dag.add_edge(config["agent_id"], "report")

        # 3. Record in knowledge graph
        kg = SQLiteKnowledgeGraph()
        entity = kg.add_entity("workflow_run", "v3-test", source_workflow="wf-e2e")
        kg.add_observation(entity.entity_id, "Spawned helper agent successfully")

        # 4. Record for learning
        detector = PatternDetector()
        detector.add_record(WorkflowRecord(
            workflow_id="wf-e2e",
            workflow_name="v3-test",
            team_composition=["analyze", config["agent_id"], "report"],
            total_cost_usd=0.15,
            total_duration_seconds=45.0,
            quality_score=0.85,
            success=True,
        ))

        # Verify all components worked
        assert dag.node_count == 3
        assert composer.spawn_count == 1
        assert kg.entity_count() == 1
        assert len(kg.get_observations(entity.entity_id)) == 1
