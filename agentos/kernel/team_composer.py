"""Dynamic team composition — runtime agent spawning."""

from __future__ import annotations

import uuid
from typing import Any

from agentos.schemas.spawn import (
    AgentArchetype,
    SpawnPolicy,
    SpawnRequest,
    SpawnStatus,
)


class TeamComposer:
    """Manages dynamic team composition during workflow execution.

    Agents can request new team members via spawn requests.
    Requests are validated against policy and optionally gated
    for human approval.
    """

    def __init__(
        self,
        policy: SpawnPolicy,
        archetypes: dict[str, AgentArchetype] | None = None,
    ) -> None:
        self._policy = policy
        self._archetypes = archetypes or {}
        self._requests: dict[str, SpawnRequest] = {}
        self._spawn_count = 0

    def register_archetype(self, archetype: AgentArchetype) -> None:
        """Register an agent archetype template."""
        self._archetypes[archetype.name] = archetype

    def request_spawn(
        self,
        requesting_agent: str,
        archetype: str,
        reason: str,
        task_description: str = "",
    ) -> SpawnRequest:
        """Create a spawn request. Validates against policy."""
        if not self._policy.allow_spawn:
            raise ValueError("Agent spawning is disabled by policy")

        if self._spawn_count >= self._policy.max_spawns_per_workflow:
            raise ValueError(
                f"Maximum spawns ({self._policy.max_spawns_per_workflow}) reached"
            )

        if self._policy.allowed_archetypes and archetype not in self._policy.allowed_archetypes:
            raise ValueError(f"Archetype '{archetype}' not in allowed list")

        if archetype not in self._archetypes:
            raise ValueError(f"Unknown archetype: {archetype}")

        request = SpawnRequest(
            request_id=str(uuid.uuid4()),
            requesting_agent=requesting_agent,
            archetype=archetype,
            reason=reason,
            task_description=task_description,
        )

        # Auto-approve if no approval required
        if not self._policy.require_approval:
            request.status = SpawnStatus.APPROVED

        self._requests[request.request_id] = request
        return request

    def approve_spawn(self, request_id: str) -> SpawnRequest:
        """Approve a pending spawn request."""
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"Unknown request: {request_id}")
        if request.status != SpawnStatus.PENDING:
            raise ValueError(f"Request is {request.status}, not pending")
        request.status = SpawnStatus.APPROVED
        return request

    def reject_spawn(self, request_id: str) -> SpawnRequest:
        """Reject a pending spawn request."""
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"Unknown request: {request_id}")
        if request.status != SpawnStatus.PENDING:
            raise ValueError(f"Request is {request.status}, not pending")
        request.status = SpawnStatus.REJECTED
        return request

    def provision(self, request_id: str) -> dict[str, Any]:
        """Provision an approved spawn request. Returns agent config."""
        request = self._requests.get(request_id)
        if request is None:
            raise ValueError(f"Unknown request: {request_id}")
        if request.status != SpawnStatus.APPROVED:
            raise ValueError(f"Request must be approved, is {request.status}")

        archetype = self._archetypes[request.archetype]
        request.status = SpawnStatus.PROVISIONED
        self._spawn_count += 1

        return {
            "agent_id": f"spawned-{uuid.uuid4().hex[:8]}",
            "adapter": archetype.adapter,
            "model": archetype.model,
            "role": archetype.role or request.task_description,
            "tools": archetype.default_tools,
            "spawned_by": request.requesting_agent,
        }

    def get_request(self, request_id: str) -> SpawnRequest | None:
        return self._requests.get(request_id)

    def list_requests(self, status: SpawnStatus | None = None) -> list[SpawnRequest]:
        if status is None:
            return list(self._requests.values())
        return [r for r in self._requests.values() if r.status == status]

    @property
    def spawn_count(self) -> int:
        return self._spawn_count

    @property
    def remaining_spawns(self) -> int:
        return max(0, self._policy.max_spawns_per_workflow - self._spawn_count)
