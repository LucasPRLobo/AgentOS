"""Tests for dynamic team composition."""

from __future__ import annotations

import pytest

from agentos.kernel.team_composer import TeamComposer
from agentos.schemas.spawn import AgentArchetype, SpawnPolicy, SpawnStatus


@pytest.fixture
def archetypes() -> dict[str, AgentArchetype]:
    return {
        "researcher": AgentArchetype(name="researcher", role="Research analyst"),
        "coder": AgentArchetype(name="coder", role="Software engineer", default_tools=["file_read", "file_write"]),
    }


@pytest.fixture
def composer(archetypes) -> TeamComposer:
    policy = SpawnPolicy(
        allow_spawn=True,
        require_approval=True,
        max_spawns_per_workflow=3,
        allowed_archetypes=["researcher", "coder"],
    )
    return TeamComposer(policy, archetypes)


class TestSpawnRequest:
    def test_create_request(self, composer):
        req = composer.request_spawn("agent-1", "researcher", "Need research help")
        assert req.status == SpawnStatus.PENDING
        assert req.archetype == "researcher"
        assert req.requesting_agent == "agent-1"

    def test_auto_approve_when_no_approval_needed(self, archetypes):
        policy = SpawnPolicy(allow_spawn=True, require_approval=False, allowed_archetypes=["researcher"])
        c = TeamComposer(policy, archetypes)
        req = c.request_spawn("agent-1", "researcher", "Need help")
        assert req.status == SpawnStatus.APPROVED

    def test_spawn_disabled_raises(self, archetypes):
        policy = SpawnPolicy(allow_spawn=False)
        c = TeamComposer(policy, archetypes)
        with pytest.raises(ValueError, match="disabled"):
            c.request_spawn("agent-1", "researcher", "Need help")

    def test_max_spawns_exceeded(self, archetypes):
        policy = SpawnPolicy(allow_spawn=True, require_approval=False, max_spawns_per_workflow=1, allowed_archetypes=["researcher"])
        c = TeamComposer(policy, archetypes)
        req = c.request_spawn("a", "researcher", "r1")
        c.provision(req.request_id)
        with pytest.raises(ValueError, match="Maximum"):
            c.request_spawn("a", "researcher", "r2")

    def test_unknown_archetype(self, composer):
        with pytest.raises(ValueError, match="not in allowed"):
            composer.request_spawn("a", "unknown", "reason")

    def test_disallowed_archetype(self, archetypes):
        policy = SpawnPolicy(allow_spawn=True, allowed_archetypes=["researcher"])
        archetypes["hacker"] = AgentArchetype(name="hacker")
        c = TeamComposer(policy, archetypes)
        with pytest.raises(ValueError, match="not in allowed"):
            c.request_spawn("a", "hacker", "reason")


class TestApproval:
    def test_approve(self, composer):
        req = composer.request_spawn("a", "researcher", "r")
        approved = composer.approve_spawn(req.request_id)
        assert approved.status == SpawnStatus.APPROVED

    def test_reject(self, composer):
        req = composer.request_spawn("a", "researcher", "r")
        rejected = composer.reject_spawn(req.request_id)
        assert rejected.status == SpawnStatus.REJECTED

    def test_approve_nonexistent(self, composer):
        with pytest.raises(ValueError, match="Unknown"):
            composer.approve_spawn("bad-id")

    def test_approve_already_approved(self, composer):
        req = composer.request_spawn("a", "researcher", "r")
        composer.approve_spawn(req.request_id)
        with pytest.raises(ValueError, match="not pending"):
            composer.approve_spawn(req.request_id)


class TestProvisioning:
    def test_provision_approved(self, composer):
        req = composer.request_spawn("a", "researcher", "r")
        composer.approve_spawn(req.request_id)
        config = composer.provision(req.request_id)
        assert "agent_id" in config
        assert config["adapter"] == "tier1"
        assert config["spawned_by"] == "a"

    def test_provision_not_approved(self, composer):
        req = composer.request_spawn("a", "researcher", "r")
        with pytest.raises(ValueError, match="approved"):
            composer.provision(req.request_id)

    def test_provision_increments_count(self, composer):
        assert composer.spawn_count == 0
        req = composer.request_spawn("a", "researcher", "r")
        composer.approve_spawn(req.request_id)
        composer.provision(req.request_id)
        assert composer.spawn_count == 1
        assert composer.remaining_spawns == 2

    def test_provisioned_config_uses_archetype(self, composer):
        req = composer.request_spawn("a", "coder", "Need coder")
        composer.approve_spawn(req.request_id)
        config = composer.provision(req.request_id)
        assert config["role"] == "Software engineer"
        assert "file_read" in config["tools"]


class TestRegistration:
    def test_register_archetype(self):
        c = TeamComposer(SpawnPolicy(allow_spawn=True))
        c.register_archetype(AgentArchetype(name="new-type", role="tester"))
        req = c.request_spawn("a", "new-type", "need tester")
        assert req.archetype == "new-type"


class TestListRequests:
    def test_list_all(self, composer):
        composer.request_spawn("a", "researcher", "r1")
        composer.request_spawn("a", "coder", "r2")
        assert len(composer.list_requests()) == 2

    def test_list_by_status(self, composer):
        req1 = composer.request_spawn("a", "researcher", "r1")
        composer.request_spawn("a", "coder", "r2")
        composer.approve_spawn(req1.request_id)
        assert len(composer.list_requests(SpawnStatus.PENDING)) == 1
        assert len(composer.list_requests(SpawnStatus.APPROVED)) == 1


class TestSchemaRoundTrip:
    def test_spawn_request_serialization(self):
        from agentos.schemas.spawn import SpawnRequest
        req = SpawnRequest(
            request_id="r1",
            requesting_agent="a",
            archetype="researcher",
            reason="test",
        )
        data = req.model_dump(mode="json")
        restored = SpawnRequest.model_validate(data)
        assert restored.request_id == "r1"

    def test_spawn_policy_serialization(self):
        policy = SpawnPolicy(allow_spawn=True, max_spawns_per_workflow=10)
        data = policy.model_dump(mode="json")
        restored = SpawnPolicy.model_validate(data)
        assert restored.max_spawns_per_workflow == 10
