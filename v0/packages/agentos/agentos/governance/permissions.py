"""Permissions engine — evaluate tool calls against side-effect policy."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agentos.core.errors import PermissionDeniedError
from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.schemas.events import PolicyDecision
from agentos.tools.base import SideEffect


class PolicyAction(StrEnum):
    """Action to take when a policy rule matches."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class PermissionRule(BaseModel):
    """A single rule in the permission policy."""

    side_effect: SideEffect
    action: PolicyAction
    reason: str = ""


class PermissionPolicy(BaseModel):
    """A set of rules governing tool execution permissions.

    Rules are evaluated in order. The first matching rule wins.
    If no rule matches, the default action is applied.
    """

    rules: list[PermissionRule] = Field(default_factory=list)
    default_action: PolicyAction = PolicyAction.DENY

    def evaluate(self, side_effect: SideEffect) -> tuple[PolicyAction, str]:
        """Evaluate a side-effect against the policy. Returns (action, reason)."""
        for rule in self.rules:
            if rule.side_effect == side_effect:
                return rule.action, rule.reason or f"Matched rule for {side_effect.value}"
        return self.default_action, f"Default policy: {self.default_action.value}"


class PermissionsEngine:
    """Evaluates tool calls against a PermissionPolicy and emits PolicyDecision events."""

    def __init__(
        self,
        policy: PermissionPolicy,
        event_log: EventLog,
        run_id: RunId,
    ) -> None:
        self._policy = policy
        self._event_log = event_log
        self._run_id = run_id

    @property
    def policy(self) -> PermissionPolicy:
        return self._policy

    def check(self, tool_name: str, side_effect: SideEffect, seq: int) -> None:
        """Check if a tool call is allowed. Emits PolicyDecision event.

        Raises PermissionDeniedError if denied.
        """
        action, reason = self._policy.evaluate(side_effect)

        self._event_log.append(
            PolicyDecision(
                run_id=self._run_id,
                seq=seq,
                payload={
                    "tool_name": tool_name,
                    "side_effect": side_effect.value,
                    "action": action.value,
                    "reason": reason,
                },
            )
        )

        if action == PolicyAction.DENY:
            raise PermissionDeniedError(
                f"Tool '{tool_name}' denied: {reason} "
                f"(side_effect={side_effect.value})"
            )
