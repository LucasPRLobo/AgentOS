"""Tests for CapabilityEnforcer — tool call interception."""

from __future__ import annotations

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.security.enforcer import CapabilityDeniedError, CapabilityEnforcer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


def _enforcer(policies, event_log, seq, workflow_id="test-wf"):
    return CapabilityEnforcer(policies, event_log, seq, workflow_id)


# ---------------------------------------------------------------------------
# Tests: Tool allowlist
# ---------------------------------------------------------------------------

class TestToolAllowlist:

    def test_allowed_tool_passes(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_read", {"path": "test.py"})

    def test_disallowed_tool_raises(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError, match="tool not in allowlist"):
            enforcer.check_tool_call("ag1", "shell_exec", {"command": "rm -rf /"})

    def test_wildcard_tool_allows_all(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:*")],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "shell_exec", {"command": "ls"})
        enforcer.check_tool_call("ag1", "file_read", {"path": "test.py"})

    def test_no_policy_allows_all(self, event_log, seq):
        """Agents without a policy are unconstrained."""
        enforcer = _enforcer({}, event_log, seq)
        enforcer.check_tool_call("ag1", "shell_exec", {"command": "rm -rf /"})


# ---------------------------------------------------------------------------
# Tests: Path scoping
# ---------------------------------------------------------------------------

class TestPathScoping:

    def test_file_read_in_scope(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_read", {"path": "src/main.py"})

    def test_file_read_out_of_scope(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError, match="path not in scope"):
            enforcer.check_tool_call("ag1", "file_read", {"path": "secrets/key.pem"})

    def test_file_write_path_scoped(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_write"),
                CapabilityGrant(type="path:output/*"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_write", {"path": "output/result.json", "content": "{}"})
        with pytest.raises(CapabilityDeniedError, match="path not in scope"):
            enforcer.check_tool_call("ag1", "file_write", {"path": "/etc/passwd", "content": "hacked"})

    def test_path_traversal_blocked(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:*"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError, match="path traversal"):
            enforcer.check_tool_call("ag1", "file_read", {"path": "../../../etc/passwd"})

    def test_wildcard_path_allows_any(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:*"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_read", {"path": "anywhere/file.txt"})


# ---------------------------------------------------------------------------
# Tests: Domain whitelisting
# ---------------------------------------------------------------------------

class TestDomainWhitelist:

    def test_allowed_domain(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:api.example.com"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "web_search", {"query": "test", "domain": "api.example.com"})

    def test_blocked_domain(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:api.example.com"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError, match="domain not in whitelist"):
            enforcer.check_tool_call("ag1", "web_search", {"query": "test", "domain": "evil.com"})

    def test_url_domain_extraction(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:example.com"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "web_search", {
            "query": "test", "url": "https://api.example.com/data",
        })

    def test_url_blocked_domain(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:safe.com"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError, match="domain not in whitelist"):
            enforcer.check_tool_call("ag1", "web_search", {
                "query": "test", "url": "https://evil.com/steal",
            })


# ---------------------------------------------------------------------------
# Tests: Event emission
# ---------------------------------------------------------------------------

class TestEventEmission:

    def test_granted_event_emitted(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_read", {"path": "test.py"})

        events = event_log.query(event_type=EventType.CAPABILITY_GRANTED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["tool_name"] == "file_read"

    def test_denied_event_emitted(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError):
            enforcer.check_tool_call("ag1", "shell_exec", {"command": "ls"})

        events = event_log.query(event_type=EventType.CAPABILITY_DENIED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "ag1"
        assert events[0].payload["tool_name"] == "shell_exec"
        assert "allowlist" in events[0].payload["reason"]

    def test_multiple_calls_multiple_events(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="tool:file_write"),
            ],
        )
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        enforcer.check_tool_call("ag1", "file_read", {"path": "a.py"})
        enforcer.check_tool_call("ag1", "file_write", {"path": "b.py", "content": ""})

        events = event_log.query(event_type=EventType.CAPABILITY_GRANTED)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Tests: Deny by default
# ---------------------------------------------------------------------------

class TestDenyByDefault:

    def test_deny_by_default_true_requires_grants(self, event_log, seq):
        policy = CapabilityPolicy(agent_id="ag1", deny_by_default=True)
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        with pytest.raises(CapabilityDeniedError):
            enforcer.check_tool_call("ag1", "file_read", {"path": "test.py"})

    def test_deny_by_default_false_allows_all_tools(self, event_log, seq):
        policy = CapabilityPolicy(agent_id="ag1", deny_by_default=False)
        enforcer = _enforcer({"ag1": policy}, event_log, seq)
        # Should not raise
        enforcer.check_tool_call("ag1", "shell_exec", {"command": "ls"})
        enforcer.check_tool_call("ag1", "file_read", {"path": "anything"})
