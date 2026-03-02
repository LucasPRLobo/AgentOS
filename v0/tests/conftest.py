"""Shared test fixtures for AgentOS."""

from __future__ import annotations

from typing import Any

import pytest

from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.permissions import (
    PermissionPolicy,
    PermissionRule,
    PolicyAction,
)
from agentos.lm.provider import BaseLMProvider, LMMessage, LMResponse
from agentos.runtime.event_log import SQLiteEventLog
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import BaseEvent, EventType
from agentos.tools.base import SideEffect


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def event_log():
    """In-memory SQLiteEventLog."""
    log = SQLiteEventLog(":memory:")
    yield log
    log.close()


@pytest.fixture()
def event_log_file(tmp_path):
    """File-backed SQLiteEventLog (for WAL/thread tests)."""
    db_path = tmp_path / "events.db"
    log = SQLiteEventLog(db_path)
    yield log
    log.close()


@pytest.fixture()
def run_id() -> RunId:
    """Generate a fresh RunId."""
    return generate_run_id()


@pytest.fixture()
def budget_tiny() -> BudgetSpec:
    """Tiny budget for testing limit enforcement."""
    return BudgetSpec(
        max_tokens=100,
        max_tool_calls=3,
        max_time_seconds=5.0,
        max_recursion_depth=1,
        max_parallel=1,
    )


@pytest.fixture()
def budget_small() -> BudgetSpec:
    """Small budget for slightly larger tests."""
    return BudgetSpec(
        max_tokens=10_000,
        max_tool_calls=50,
        max_time_seconds=60.0,
        max_recursion_depth=3,
        max_parallel=2,
    )


@pytest.fixture()
def deny_write_policy() -> PermissionPolicy:
    """Policy that denies WRITE and DESTRUCTIVE, allows PURE and READ."""
    return PermissionPolicy(
        rules=[
            PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW),
            PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
            PermissionRule(
                side_effect=SideEffect.WRITE,
                action=PolicyAction.DENY,
                reason="Write operations denied",
            ),
            PermissionRule(
                side_effect=SideEffect.DESTRUCTIVE,
                action=PolicyAction.DENY,
                reason="Destructive operations denied",
            ),
        ],
        default_action=PolicyAction.DENY,
    )


@pytest.fixture()
def allow_all_policy() -> PermissionPolicy:
    """Policy that allows everything by default."""
    return PermissionPolicy(
        rules=[
            PermissionRule(side_effect=SideEffect.PURE, action=PolicyAction.ALLOW),
            PermissionRule(side_effect=SideEffect.READ, action=PolicyAction.ALLOW),
            PermissionRule(side_effect=SideEffect.WRITE, action=PolicyAction.ALLOW),
            PermissionRule(side_effect=SideEffect.DESTRUCTIVE, action=PolicyAction.ALLOW),
        ],
        default_action=PolicyAction.ALLOW,
    )


# ── MockLMProvider ─────────────────────────────────────────────────


class MockLMProvider(BaseLMProvider):
    """Deterministic mock LM provider with scripted responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses) if responses else ["Hello"]
        self._call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    @property
    def call_count(self) -> int:
        return self._call_count

    def complete(self, messages: list[LMMessage]) -> LMResponse:
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        return LMResponse(
            content=content,
            tokens_used=len(content),
            prompt_tokens=sum(len(m.content) for m in messages),
            completion_tokens=len(content),
        )


# ── Assertion Helpers ──────────────────────────────────────────────


def assert_event_sequence(events: list[BaseEvent], expected_types: list[EventType]) -> None:
    """Assert that events match the expected EventType sequence."""
    actual = [e.event_type for e in events]
    assert actual == expected_types, (
        f"Event sequence mismatch.\n"
        f"  Expected: {[t.value for t in expected_types]}\n"
        f"  Actual:   {[t.value for t in actual]}"
    )


def assert_has_event(
    events: list[BaseEvent],
    event_type: EventType,
    **payload_checks: Any,
) -> BaseEvent:
    """Assert that at least one event of the given type exists and matches payload checks.

    Returns the first matching event.
    """
    matching = [e for e in events if e.event_type == event_type]
    assert matching, f"No event of type {event_type.value} found in {len(events)} events"

    if payload_checks:
        for event in matching:
            if all(event.payload.get(k) == v for k, v in payload_checks.items()):
                return event
        checked = {k: v for k, v in payload_checks.items()}
        raise AssertionError(
            f"Found {len(matching)} {event_type.value} event(s) but none matched "
            f"payload checks: {checked}\n"
            f"Payloads: {[e.payload for e in matching]}"
        )

    return matching[0]
