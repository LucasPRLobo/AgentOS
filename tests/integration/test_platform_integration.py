"""Platform integration tests — multi-user, cross-run memory, builder E2E."""

from __future__ import annotations

import uuid

import pytest
import yaml

from agentos.dashboard.auth import AuthManager
from agentos.dashboard.builder import WorkflowBuilder
from agentos.kernel.memory_store import SQLiteMemoryStore, extract_memories_from_output
from agentos.schemas.auth import AuthConfig, Role
from agentos.schemas.memory import MemoryConfig, MemoryQuery, MemoryType


class TestMultiUserIsolation:
    """Two users should see only their own data."""

    def test_two_users_separate_workflows(self):
        auth = AuthManager(AuthConfig(enabled=True, jwt_secret="test-secret"))
        alice = auth.create_user("alice", "pass1")
        bob = auth.create_user("bob", "pass2")

        assert alice.user_id != bob.user_id
        assert alice.username == "alice"
        assert bob.username == "bob"

        # Each user gets their own JWT
        alice_token = auth.create_jwt(alice)
        bob_token = auth.create_jwt(bob)
        assert alice_token != bob_token

        # Verify tokens return correct users
        assert auth.verify_jwt(alice_token).username == "alice"
        assert auth.verify_jwt(bob_token).username == "bob"

    def test_api_keys_per_user(self):
        auth = AuthManager(AuthConfig(enabled=True, jwt_secret="test-secret"))
        alice = auth.create_user("alice", "pass1")
        bob = auth.create_user("bob", "pass2")

        _, alice_key = auth.create_api_key(alice.user_id, "alice-key")
        _, bob_key = auth.create_api_key(bob.user_id, "bob-key")

        alice_keys = auth.list_api_keys(alice.user_id)
        bob_keys = auth.list_api_keys(bob.user_id)

        assert len(alice_keys) == 1
        assert len(bob_keys) == 1
        assert alice_keys[0].name == "alice-key"
        assert bob_keys[0].name == "bob-key"

    def test_role_based_access(self):
        auth = AuthManager(AuthConfig(enabled=True, jwt_secret="test-secret"))
        admin = auth.create_user("admin", "pass", Role.ADMIN)
        viewer = auth.create_user("viewer", "pass", Role.VIEWER)

        assert auth.has_permission(admin, "manage_users") is True
        assert auth.has_permission(viewer, "manage_users") is False
        assert auth.has_permission(viewer, "read") is True


class TestCrossRunMemory:
    """Run #2 should benefit from findings of run #1."""

    def test_findings_persist_across_runs(self):
        store = SQLiteMemoryStore(MemoryConfig(enabled=True))

        # Run #1 produces findings
        findings = [
            {"content": "API rate limit is 100/min", "confidence": 0.95, "tags": ["api"]},
            {"content": "Auth token expires in 1 hour", "confidence": 0.9, "tags": ["auth"]},
        ]
        memories = extract_memories_from_output("wf-run-1", "t-1", findings)
        for m in memories:
            store.store(m)

        # Run #2 queries for relevant memories
        results = store.query(MemoryQuery(tags=["api"]))
        assert len(results) == 1
        assert "rate limit" in results[0].content

    def test_gate_feedback_available_for_next_run(self):
        store = SQLiteMemoryStore(MemoryConfig(enabled=True))

        # Run #1 has gate feedback
        memories = extract_memories_from_output(
            "wf-run-1", "t-gate", [],
            gate_feedback="Rejected: need more error handling"
        )
        for m in memories:
            store.store(m)

        # Run #2 can query gate feedback
        results = store.query(MemoryQuery(memory_type=MemoryType.GATE_FEEDBACK))
        assert len(results) == 1
        assert "error handling" in results[0].content

    def test_confidence_decay_filters_old_memories(self):
        config = MemoryConfig(enabled=True, decay_rate=0.5, min_confidence=0.3)
        store = SQLiteMemoryStore(config)

        from datetime import datetime, timedelta
        from agentos.schemas.memory import MemoryEntry

        old_memory = MemoryEntry(
            memory_id=str(uuid.uuid4()),
            workflow_id="wf-old",
            task_id="t-1",
            memory_type=MemoryType.FINDING,
            content="Old finding",
            confidence=0.4,
            created_at=datetime.now() - timedelta(days=5),
        )
        store.store(old_memory)
        store.decay()
        assert store.count() == 0  # Should be pruned


class TestBuilderToExecuteFlow:
    """Builder creates template → validates → ready for execution."""

    def test_builder_create_validate_flow(self):
        builder = WorkflowBuilder()
        workflow_yaml = yaml.dump({
            "name": "builder-e2e",
            "version": "1.0",
            "agents": {
                "researcher": {
                    "adapter": "tier1",
                    "model": "claude-sonnet-4-20250514",
                    "role": "Research analyst",
                }
            },
            "tasks": {
                "analyze": {
                    "name": "analyze",
                    "agent": "researcher",
                    "description": "Analyze the data",
                },
                "summarize": {
                    "name": "summarize",
                    "agent": "researcher",
                    "description": "Summarize findings",
                    "depends_on": ["analyze"],
                },
            },
        })

        # Create template
        template = builder.create_template("E2E Workflow", workflow_yaml, "Integration test")
        assert template.template_id

        # Validate
        result = builder.validate_workflow(template.workflow_yaml)
        assert result.valid is True

        # Update
        updated = builder.update_template(template.template_id, description="Updated description")
        assert updated.description == "Updated description"

        # List
        templates = builder.list_templates()
        assert any(t.template_id == template.template_id for t in templates)
