"""Tests for PermissionsEngine — policy evaluation and event emission."""

import pytest

from agentos.core.errors import PermissionDeniedError
from agentos.core.identifiers import generate_run_id
from agentos.governance.permissions import (
    PermissionPolicy,
    PermissionRule,
    PermissionsEngine,
    PolicyAction,
)
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.events import EventType
from agentos.tools.base import SideEffect


class TestPermissionPolicy:
    def test_allow_rule(self) -> None:
        policy = PermissionPolicy(
            rules=[PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW)]
        )
        action, _ = policy.evaluate(SideEffect.PURE)
        assert action == PolicyAction.ALLOW

    def test_deny_rule(self) -> None:
        policy = PermissionPolicy(
            rules=[
                PermissionRule(
                    side_effect=SideEffect.DESTRUCTIVE,
                    action=PolicyAction.DENY,
                    reason="destructive ops blocked",
                )
            ]
        )
        action, reason = policy.evaluate(SideEffect.DESTRUCTIVE)
        assert action == PolicyAction.DENY
        assert "destructive ops blocked" in reason

    def test_default_deny(self) -> None:
        policy = PermissionPolicy(default_action=PolicyAction.DENY)
        action, _ = policy.evaluate(SideEffect.WRITE)
        assert action == PolicyAction.DENY

    def test_default_allow(self) -> None:
        policy = PermissionPolicy(default_action=PolicyAction.ALLOW)
        action, _ = policy.evaluate(SideEffect.WRITE)
        assert action == PolicyAction.ALLOW

    def test_first_match_wins(self) -> None:
        policy = PermissionPolicy(
            rules=[
                PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
                PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.DENY),
            ]
        )
        action, _ = policy.evaluate(SideEffect.READ)
        assert action == PolicyAction.ALLOW


class TestPermissionsEngine:
    def test_allowed_tool(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        policy = PermissionPolicy(
            rules=[PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW)]
        )
        engine = PermissionsEngine(policy, log, run_id)

        engine.check("my_tool", SideEffect.PURE, seq=0)  # should not raise

    def test_denied_tool_raises(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        policy = PermissionPolicy(default_action=PolicyAction.DENY)
        engine = PermissionsEngine(policy, log, run_id)

        with pytest.raises(PermissionDeniedError, match="my_tool"):
            engine.check("my_tool", SideEffect.WRITE, seq=0)

    def test_emits_allow_event(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        policy = PermissionPolicy(
            rules=[PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW)]
        )
        engine = PermissionsEngine(policy, log, run_id)

        engine.check("reader", SideEffect.READ, seq=0)

        events = log.query_by_type(run_id, EventType.POLICY_DECISION)
        assert len(events) == 1
        assert events[0].payload["action"] == "ALLOW"
        assert events[0].payload["tool_name"] == "reader"

    def test_emits_deny_event(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        policy = PermissionPolicy(default_action=PolicyAction.DENY)
        engine = PermissionsEngine(policy, log, run_id)

        with pytest.raises(PermissionDeniedError):
            engine.check("writer", SideEffect.WRITE, seq=0)

        events = log.query_by_type(run_id, EventType.POLICY_DECISION)
        assert len(events) == 1
        assert events[0].payload["action"] == "DENY"

    def test_mixed_policy(self) -> None:
        log = SQLiteEventLog()
        run_id = generate_run_id()
        policy = PermissionPolicy(
            rules=[
                PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW),
                PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
                PermissionRule(
                    side_effect=SideEffect.DESTRUCTIVE,
                    action=PolicyAction.DENY,
                    reason="no destructive ops",
                ),
            ],
            default_action=PolicyAction.DENY,
        )
        engine = PermissionsEngine(policy, log, run_id)

        engine.check("calc", SideEffect.PURE, seq=0)
        engine.check("fetcher", SideEffect.READ, seq=1)

        with pytest.raises(PermissionDeniedError, match="no destructive ops"):
            engine.check("deleter", SideEffect.DESTRUCTIVE, seq=2)

        with pytest.raises(PermissionDeniedError):
            engine.check("writer", SideEffect.WRITE, seq=3)
