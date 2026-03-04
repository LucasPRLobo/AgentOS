"""Tests for manager agent message router."""

from __future__ import annotations

import pytest

from agentos.adapters.manager_agent import (
    EscalationPolicy,
    ManagerAgent,
    RouteAction,
    RouteDecision,
    RoutingRule,
)


@pytest.fixture
def manager() -> ManagerAgent:
    m = ManagerAgent(
        escalation=EscalationPolicy(min_confidence=0.5),
    )
    m.register_agent("researcher", keywords=["research", "analyze", "find", "investigate"])
    m.register_agent("coder", keywords=["code", "implement", "fix", "debug", "program"])
    m.register_agent("reviewer", keywords=["review", "check", "approve", "validate"])
    return m


class TestRuleBasedRouting:
    def test_exact_pattern_match(self, manager):
        manager.add_rule(RoutingRule(pattern=r"^deploy", target_agent="devops", priority=10))
        result = manager.route("deploy to production")
        assert result.action == RouteAction.FORWARD
        assert result.target_agent == "devops"
        assert result.confidence == 1.0

    def test_regex_pattern(self, manager):
        manager.add_rule(RoutingRule(pattern=r"bug\s*#\d+", target_agent="coder", priority=5))
        result = manager.route("Please fix bug #123")
        assert result.target_agent == "coder"

    def test_priority_ordering(self, manager):
        manager.add_rule(RoutingRule(pattern=r"test", target_agent="tester", priority=1))
        manager.add_rule(RoutingRule(pattern=r"test", target_agent="qa", priority=10))
        result = manager.route("run test suite")
        assert result.target_agent == "qa"  # Higher priority wins

    def test_case_insensitive(self, manager):
        manager.add_rule(RoutingRule(pattern=r"URGENT", target_agent="oncall"))
        result = manager.route("this is urgent please help")
        assert result.target_agent == "oncall"

    def test_escalate_action(self, manager):
        manager.add_rule(RoutingRule(pattern=r"dangerous", target_agent="admin", action=RouteAction.ESCALATE))
        result = manager.route("dangerous operation requested")
        assert result.action == RouteAction.ESCALATE

    def test_drop_action(self, manager):
        manager.add_rule(RoutingRule(pattern=r"^spam", target_agent="", action=RouteAction.DROP))
        result = manager.route("spam message here")
        assert result.action == RouteAction.DROP


class TestKeywordRouting:
    def test_keyword_match_researcher(self, manager):
        result = manager.route("Please research and analyze this topic")
        assert result.target_agent == "researcher"
        assert result.action == RouteAction.FORWARD

    def test_keyword_match_coder(self, manager):
        result = manager.route("implement the new feature and fix the bug")
        assert result.target_agent == "coder"

    def test_keyword_match_reviewer(self, manager):
        result = manager.route("review and approve the pull request")
        assert result.target_agent == "reviewer"

    def test_best_keyword_match_wins(self, manager):
        # "code implement fix debug" has 4 keywords for coder
        result = manager.route("code implement fix debug program")
        assert result.target_agent == "coder"


class TestEscalation:
    def test_no_match_escalates(self, manager):
        result = manager.route("do something completely unrelated")
        assert result.action == RouteAction.ESCALATE
        assert result.confidence == 0.0

    def test_low_confidence_escalates(self):
        m = ManagerAgent(escalation=EscalationPolicy(min_confidence=0.8))
        m.register_agent("researcher", keywords=["research", "analyze", "find", "investigate", "study", "explore"])
        # Only 1 out of 6 keywords matches → low confidence
        result = m.route("find something")
        assert result.action == RouteAction.ESCALATE

    def test_escalation_includes_message(self, manager):
        result = manager.route("completely unknown task")
        assert result.action == RouteAction.ESCALATE
        assert len(result.reason) > 0


class TestBatchRouting:
    def test_route_batch(self, manager):
        messages = [
            "research this topic",
            "implement the feature",
            "review the code",
        ]
        results = manager.route_batch(messages)
        assert len(results) == 3
        assert results[0].target_agent == "researcher"
        assert results[1].target_agent == "coder"
        assert results[2].target_agent == "reviewer"


class TestRegistration:
    def test_register_agent(self):
        m = ManagerAgent()
        m.register_agent("new-agent", keywords=["special"])
        result = m.route("special task")
        assert result.target_agent == "new-agent"

    def test_register_duplicate(self):
        m = ManagerAgent()
        m.register_agent("agent-1")
        m.register_agent("agent-1")
        assert m._agents.count("agent-1") == 1

    def test_add_rule_sorts_by_priority(self):
        m = ManagerAgent()
        m.add_rule(RoutingRule(pattern="a", target_agent="a", priority=1))
        m.add_rule(RoutingRule(pattern="b", target_agent="b", priority=10))
        m.add_rule(RoutingRule(pattern="c", target_agent="c", priority=5))
        assert m._rules[0].priority == 10
        assert m._rules[1].priority == 5
        assert m._rules[2].priority == 1
