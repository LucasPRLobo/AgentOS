"""Secret store — credential management with capability-gated access."""

from __future__ import annotations

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import Event, EventType


class SecretAccessDenied(Exception):
    """Raised when an agent attempts to access a secret it doesn't have."""

    def __init__(self, agent_id: str, secret_name: str) -> None:
        self.agent_id = agent_id
        self.secret_name = secret_name
        super().__init__(f"Agent {agent_id!r} denied access to secret {secret_name!r}")


class SecretStore:
    """Capability-gated credential store.

    Secrets are stored in memory keyed by name. Access is controlled by
    the agent's capability policy — agents need an `action:secret:<name>`
    grant to read a secret.

    Secret values are NEVER logged to the event log. Only the secret name
    and access result (granted/denied) are recorded.
    """

    def __init__(
        self,
        policies: dict[str, CapabilityPolicy],
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._policies = policies
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._secrets: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        """Store a secret. No event emitted (secret values never logged)."""
        self._secrets[name] = value

    def get(self, agent_id: str, name: str) -> str:
        """Retrieve a secret if the agent has the required capability.

        Requires an `action:secret:<name>` or `action:secret:*` grant.
        Raises SecretAccessDenied if the agent lacks permission.
        Raises KeyError if the secret doesn't exist.
        """
        policy = self._policies.get(agent_id)

        # Check capability
        if policy is not None and policy.deny_by_default:
            if not policy.has_action(f"secret:{name}"):
                self._emit_denied(agent_id, name)
                raise SecretAccessDenied(agent_id, name)

        if name not in self._secrets:
            raise KeyError(f"Secret not found: {name!r}")

        self._emit_granted(agent_id, name)
        return self._secrets[name]

    def list_names(self) -> list[str]:
        """Return the names of all stored secrets (not values)."""
        return sorted(self._secrets.keys())

    def delete(self, name: str) -> None:
        """Remove a secret."""
        self._secrets.pop(name, None)

    def _emit_granted(self, agent_id: str, secret_name: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.CAPABILITY_GRANTED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "action": f"secret:{secret_name}",
                "result": "granted",
            },
        ))

    def _emit_denied(self, agent_id: str, secret_name: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.CAPABILITY_DENIED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "action": f"secret:{secret_name}",
                "result": "denied",
            },
        ))
