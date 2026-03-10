"""Tests for SecretStore — credential management with capability gating."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.security.secrets import SecretAccessDenied, SecretStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


# ---------------------------------------------------------------------------
# Tests: Basic operations
# ---------------------------------------------------------------------------

class TestBasicOperations:

    def test_set_and_get(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("API_KEY", "sk-12345")
        assert store.get("ag1", "API_KEY") == "sk-12345"

    def test_get_nonexistent_raises(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        with pytest.raises(KeyError, match="MISSING"):
            store.get("ag1", "MISSING")

    def test_list_names(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("B_KEY", "val")
        store.set("A_KEY", "val")
        assert store.list_names() == ["A_KEY", "B_KEY"]

    def test_delete(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("KEY", "val")
        store.delete("KEY")
        with pytest.raises(KeyError):
            store.get("ag1", "KEY")

    def test_delete_nonexistent_is_noop(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.delete("NEVER_EXISTED")  # Should not raise

    def test_overwrite_secret(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("KEY", "old")
        store.set("KEY", "new")
        assert store.get("ag1", "KEY") == "new"


# ---------------------------------------------------------------------------
# Tests: Capability-gated access
# ---------------------------------------------------------------------------

class TestCapabilityGatedAccess:

    def test_agent_with_specific_grant(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="action:secret:API_KEY")],
        )
        store = SecretStore({"ag1": policy}, event_log, seq, "test-wf")
        store.set("API_KEY", "sk-12345")
        assert store.get("ag1", "API_KEY") == "sk-12345"

    def test_agent_denied_wrong_secret(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="action:secret:API_KEY")],
        )
        store = SecretStore({"ag1": policy}, event_log, seq, "test-wf")
        store.set("DB_PASS", "supersecret")
        with pytest.raises(SecretAccessDenied, match="ag1.*DB_PASS"):
            store.get("ag1", "DB_PASS")

    def test_agent_with_wildcard_secret_grant(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="action:secret")],
        )
        store = SecretStore({"ag1": policy}, event_log, seq, "test-wf")
        store.set("API_KEY", "k1")
        store.set("DB_PASS", "k2")
        assert store.get("ag1", "API_KEY") == "k1"
        assert store.get("ag1", "DB_PASS") == "k2"

    def test_agent_without_policy_can_access(self, event_log, seq):
        """Agents without a policy are unconstrained."""
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("KEY", "val")
        assert store.get("unknown_agent", "KEY") == "val"

    def test_permissive_policy_allows_all(self, event_log, seq):
        policy = CapabilityPolicy(agent_id="ag1", deny_by_default=False)
        store = SecretStore({"ag1": policy}, event_log, seq, "test-wf")
        store.set("KEY", "val")
        assert store.get("ag1", "KEY") == "val"

    def test_different_agents_different_access(self, event_log, seq):
        policy_a = CapabilityPolicy(
            agent_id="ag_a",
            grants=[CapabilityGrant(type="action:secret:API_KEY")],
        )
        policy_b = CapabilityPolicy(
            agent_id="ag_b",
            grants=[CapabilityGrant(type="action:secret:DB_PASS")],
        )
        store = SecretStore(
            {"ag_a": policy_a, "ag_b": policy_b},
            event_log, seq, "test-wf",
        )
        store.set("API_KEY", "k1")
        store.set("DB_PASS", "k2")

        assert store.get("ag_a", "API_KEY") == "k1"
        with pytest.raises(SecretAccessDenied):
            store.get("ag_a", "DB_PASS")

        assert store.get("ag_b", "DB_PASS") == "k2"
        with pytest.raises(SecretAccessDenied):
            store.get("ag_b", "API_KEY")


# ---------------------------------------------------------------------------
# Tests: Event emission
# ---------------------------------------------------------------------------

class TestSecretEvents:

    def test_granted_event_on_access(self, event_log, seq):
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("KEY", "val")
        store.get("ag1", "KEY")

        events = event_log.query(event_type=EventType.CAPABILITY_GRANTED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["action"] == "secret:KEY"

    def test_denied_event_on_blocked_access(self, event_log, seq):
        policy = CapabilityPolicy(agent_id="ag1", grants=[])
        store = SecretStore({"ag1": policy}, event_log, seq, "test-wf")
        store.set("KEY", "val")

        with pytest.raises(SecretAccessDenied):
            store.get("ag1", "KEY")

        events = event_log.query(event_type=EventType.CAPABILITY_DENIED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["action"] == "secret:KEY"

    def test_secret_value_never_in_events(self, event_log, seq):
        """Critical: secret values must NEVER appear in event payloads."""
        store = SecretStore({}, event_log, seq, "test-wf")
        store.set("KEY", "super-secret-value-12345")
        store.get("ag1", "KEY")

        all_events = event_log.replay("test-wf")
        for event in all_events:
            payload_str = str(event.payload)
            assert "super-secret-value-12345" not in payload_str
