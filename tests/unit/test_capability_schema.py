"""Tests for capability schemas — CapabilityGrant and CapabilityPolicy."""

from __future__ import annotations

import pytest

from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy


# ---------------------------------------------------------------------------
# CapabilityGrant
# ---------------------------------------------------------------------------

class TestCapabilityGrantParsing:

    def test_prefix_extraction(self):
        g = CapabilityGrant(type="tool:file_read")
        assert g.prefix == "tool"
        assert g.value == "file_read"

    def test_prefix_no_colon(self):
        g = CapabilityGrant(type="anything")
        assert g.prefix == "anything"
        assert g.value == ""

    def test_nested_colons(self):
        g = CapabilityGrant(type="action:secret:API_KEY")
        assert g.prefix == "action"
        assert g.value == "secret:API_KEY"


class TestToolMatching:

    def test_exact_match(self):
        g = CapabilityGrant(type="tool:file_read")
        assert g.matches_tool("file_read") is True
        assert g.matches_tool("file_write") is False

    def test_wildcard_tool(self):
        g = CapabilityGrant(type="tool:*")
        assert g.matches_tool("file_read") is True
        assert g.matches_tool("shell_exec") is True

    def test_non_tool_grant(self):
        g = CapabilityGrant(type="path:src/**")
        assert g.matches_tool("file_read") is False


class TestPathMatching:

    def test_exact_file(self):
        g = CapabilityGrant(type="path:src/main.py")
        assert g.matches_path("src/main.py") is True
        assert g.matches_path("src/other.py") is False

    def test_glob_pattern(self):
        g = CapabilityGrant(type="path:src/*.py")
        assert g.matches_path("src/main.py") is True
        assert g.matches_path("src/utils.py") is True
        assert g.matches_path("tests/test.py") is False

    def test_recursive_glob(self):
        g = CapabilityGrant(type="path:src/**")
        assert g.matches_path("src/a/b/c.py") is True

    def test_wildcard_path(self):
        g = CapabilityGrant(type="path:*")
        assert g.matches_path("anything/here.txt") is True

    def test_non_path_grant(self):
        g = CapabilityGrant(type="tool:file_read")
        assert g.matches_path("src/main.py") is False


class TestDomainMatching:

    def test_exact_domain(self):
        g = CapabilityGrant(type="domain:api.example.com")
        assert g.matches_domain("api.example.com") is True
        assert g.matches_domain("other.example.com") is False

    def test_subdomain_match(self):
        g = CapabilityGrant(type="domain:example.com")
        assert g.matches_domain("example.com") is True
        assert g.matches_domain("api.example.com") is True
        assert g.matches_domain("evil.com") is False

    def test_wildcard_domain(self):
        g = CapabilityGrant(type="domain:*")
        assert g.matches_domain("anything.com") is True

    def test_non_domain_grant(self):
        g = CapabilityGrant(type="tool:web_search")
        assert g.matches_domain("api.example.com") is False


class TestActionMatching:

    def test_exact_action(self):
        g = CapabilityGrant(type="action:secret:API_KEY")
        assert g.matches_action("secret:API_KEY") is True
        assert g.matches_action("secret:OTHER") is False

    def test_action_prefix_match(self):
        g = CapabilityGrant(type="action:secret")
        assert g.matches_action("secret:API_KEY") is True
        assert g.matches_action("secret:DB_PASS") is True
        assert g.matches_action("other:thing") is False

    def test_wildcard_action(self):
        g = CapabilityGrant(type="action:*")
        assert g.matches_action("anything") is True


# ---------------------------------------------------------------------------
# CapabilityPolicy
# ---------------------------------------------------------------------------

class TestPolicyDenyByDefault:

    def test_no_grants_denies_all(self):
        p = CapabilityPolicy(agent_id="ag1", deny_by_default=True)
        assert p.has_tool("file_read") is False
        assert p.has_path("anything.py") is False
        assert p.has_domain("example.com") is False
        assert p.has_action("secret:KEY") is False

    def test_grants_allow_matching(self):
        p = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="tool:file_write"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        assert p.has_tool("file_read") is True
        assert p.has_tool("shell_exec") is False
        assert p.has_path("src/main.py") is True
        assert p.has_path("tests/test.py") is False


class TestPolicyPermissive:

    def test_deny_by_default_false_allows_all(self):
        p = CapabilityPolicy(agent_id="ag1", deny_by_default=False)
        assert p.has_tool("anything") is True
        assert p.has_path("anything") is True
        assert p.has_domain("anything") is True
        assert p.has_action("anything") is True


class TestPolicyMultipleGrants:

    def test_multiple_tool_grants(self):
        p = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="tool:file_write"),
                CapabilityGrant(type="tool:web_search"),
            ],
        )
        assert p.has_tool("file_read") is True
        assert p.has_tool("file_write") is True
        assert p.has_tool("web_search") is True
        assert p.has_tool("shell_exec") is False

    def test_mixed_grant_types(self):
        p = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/**"),
                CapabilityGrant(type="domain:api.example.com"),
                CapabilityGrant(type="action:secret:API_KEY"),
            ],
        )
        assert p.has_tool("file_read") is True
        assert p.has_path("src/deep/file.py") is True
        assert p.has_domain("api.example.com") is True
        assert p.has_action("secret:API_KEY") is True
        # Not granted
        assert p.has_tool("shell_exec") is False
        assert p.has_path("tests/test.py") is False
        assert p.has_domain("evil.com") is False
        assert p.has_action("secret:OTHER") is False
