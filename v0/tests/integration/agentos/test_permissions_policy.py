"""Integration tests for permissions engine with event emission."""

from __future__ import annotations

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

from tests.conftest import assert_has_event

pytestmark = pytest.mark.integration


class TestWriteDenied:
    """Verify WRITE tool with deny policy raises and emits DENY event."""

    def test_write_tool_denied(self, event_log, run_id, deny_write_policy):
        engine = PermissionsEngine(deny_write_policy, event_log, run_id)

        with pytest.raises(PermissionDeniedError):
            engine.check("file_writer", SideEffect.WRITE, seq=0)

        events = event_log.query_by_run(run_id)
        evt = assert_has_event(events, EventType.POLICY_DECISION, action="DENY")
        assert evt.payload["tool_name"] == "file_writer"
        assert evt.payload["side_effect"] == "WRITE"


class TestDenyEmitsPolicyDecision:
    """Verify DENY emits PolicyDecision event with correct payload."""

    def test_deny_event_payload(self, event_log, run_id, deny_write_policy):
        engine = PermissionsEngine(deny_write_policy, event_log, run_id)

        with pytest.raises(PermissionDeniedError):
            engine.check("destroyer", SideEffect.DESTRUCTIVE, seq=0)

        events = event_log.query_by_run(run_id)
        evt = assert_has_event(events, EventType.POLICY_DECISION)
        assert evt.payload["action"] == "DENY"
        assert evt.payload["side_effect"] == "DESTRUCTIVE"


class TestPureAllowed:
    """Verify PURE tool allowed emits PolicyDecision(ALLOW) event."""

    def test_pure_tool_allowed(self, event_log, run_id, deny_write_policy):
        engine = PermissionsEngine(deny_write_policy, event_log, run_id)

        # Should not raise
        engine.check("calculator", SideEffect.PURE, seq=0)

        events = event_log.query_by_run(run_id)
        evt = assert_has_event(events, EventType.POLICY_DECISION, action="ALLOW")
        assert evt.payload["tool_name"] == "calculator"


class TestDefaultDenyBlocksAll:
    """Verify default-DENY policy blocks all side effects when no rules match."""

    def test_default_deny(self, event_log, run_id):
        policy = PermissionPolicy(rules=[], default_action=PolicyAction.DENY)
        engine = PermissionsEngine(policy, event_log, run_id)

        for seq, side_effect in enumerate(SideEffect):
            with pytest.raises(PermissionDeniedError):
                engine.check(f"tool_{side_effect.value}", side_effect, seq=seq)
