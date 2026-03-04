"""Manager Agent — LLM-powered message router with rule-based fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class RouteAction(StrEnum):
    FORWARD = "forward"
    ESCALATE = "escalate"
    DROP = "drop"


@dataclass
class RoutingRule:
    """A rule for routing messages to agents."""

    pattern: str  # regex pattern to match against message content
    target_agent: str
    priority: int = 0  # higher = checked first
    action: RouteAction = RouteAction.FORWARD


@dataclass
class RouteDecision:
    """The result of a routing decision."""

    action: RouteAction
    target_agent: str | None = None
    confidence: float = 1.0
    reason: str = ""


@dataclass
class EscalationPolicy:
    """When to escalate to human gate."""

    min_confidence: float = 0.5
    escalation_message: str = "Routing confidence below threshold — human review needed"


class ManagerAgent:
    """LLM-powered message router with rule-based fallback.

    Routing flow:
    1. Check explicit routing rules (regex patterns)
    2. If no rule matches, use keyword-based heuristic routing
    3. If confidence is below threshold, escalate to human gate

    In production, step 2 would use an LLM call. Here we implement
    a keyword-based heuristic as the routing logic.
    """

    def __init__(
        self,
        rules: list[RoutingRule] | None = None,
        agents: list[str] | None = None,
        escalation: EscalationPolicy | None = None,
    ) -> None:
        self._rules = sorted(rules or [], key=lambda r: -r.priority)
        self._agents = agents or []
        self._escalation = escalation or EscalationPolicy()
        self._agent_keywords: dict[str, list[str]] = {}

    def register_agent(self, agent_id: str, keywords: list[str] | None = None) -> None:
        """Register an agent with optional keyword associations."""
        if agent_id not in self._agents:
            self._agents.append(agent_id)
        if keywords:
            self._agent_keywords[agent_id] = [k.lower() for k in keywords]

    def add_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def route(self, message: str) -> RouteDecision:
        """Route a message to the appropriate agent.

        Returns a RouteDecision with the target agent and confidence.
        """
        # Step 1: Check explicit rules
        for rule in self._rules:
            if re.search(rule.pattern, message, re.IGNORECASE):
                return RouteDecision(
                    action=rule.action,
                    target_agent=rule.target_agent,
                    confidence=1.0,
                    reason=f"Matched rule pattern: {rule.pattern}",
                )

        # Step 2: Keyword-based heuristic routing
        message_lower = message.lower()
        best_match: str | None = None
        best_score = 0
        total_possible = 0

        for agent_id, keywords in self._agent_keywords.items():
            if not keywords:
                continue
            matches = sum(1 for kw in keywords if kw in message_lower)
            score = matches / len(keywords)
            total_possible = max(total_possible, len(keywords))
            if score > best_score:
                best_score = score
                best_match = agent_id

        if best_match and best_score > 0:
            confidence = min(1.0, best_score * 2)  # Scale up slightly
            if confidence < self._escalation.min_confidence:
                return RouteDecision(
                    action=RouteAction.ESCALATE,
                    target_agent=best_match,
                    confidence=confidence,
                    reason=self._escalation.escalation_message,
                )
            return RouteDecision(
                action=RouteAction.FORWARD,
                target_agent=best_match,
                confidence=confidence,
                reason=f"Keyword match (score={best_score:.2f})",
            )

        # Step 3: No match — escalate
        return RouteDecision(
            action=RouteAction.ESCALATE,
            target_agent=None,
            confidence=0.0,
            reason="No routing rule or keyword match found",
        )

    def route_batch(self, messages: list[str]) -> list[RouteDecision]:
        """Route multiple messages."""
        return [self.route(msg) for msg in messages]
