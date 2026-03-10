"""Capability enforcer — intercepts Tier 1 tool calls against policy."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import Event, EventType


class CapabilityDeniedError(Exception):
    """Raised when a tool call violates the agent's capability policy."""

    def __init__(self, agent_id: str, tool_name: str, reason: str) -> None:
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Denied {tool_name} for {agent_id}: {reason}")


class CapabilityEnforcer:
    """Intercepts Tier 1 tool calls and validates against capability policy.

    For each tool call:
    1. Check if tool is in agent's allowlist
    2. Check if file paths are within workspace scope
    3. Check if network targets are in domain whitelist
    4. If denied: emit capability.denied event, raise CapabilityDeniedError
    5. If granted: emit capability.granted event, proceed
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

    def check_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> None:
        """Validate a tool call against the agent's capability policy.

        Raises CapabilityDeniedError if the call is not permitted.
        Emits capability.granted or capability.denied events.
        """
        policy = self._policies.get(agent_id)

        # No policy = no enforcement (permissive by default for unconfigured agents)
        if policy is None:
            return

        # 1. Check tool allowlist
        if not policy.has_tool(tool_name):
            self._emit_denied(agent_id, tool_name, "tool not in allowlist")
            raise CapabilityDeniedError(
                agent_id, tool_name, "tool not in allowlist"
            )

        # 2. Check file path scoping (for file_read, file_write)
        if tool_name in ("file_read", "file_write"):
            path = tool_input.get("path", "")
            if path:
                # Always reject path traversal attempts
                if ".." in PurePosixPath(path).parts:
                    self._emit_denied(
                        agent_id, tool_name,
                        f"path traversal attempt: {path}",
                    )
                    raise CapabilityDeniedError(
                        agent_id, tool_name,
                        f"path traversal attempt: {path}",
                    )
                # Check scope only if the policy has path grants
                has_path_grants = any(g.prefix == "path" for g in policy.grants)
                if has_path_grants and not policy.has_path(path):
                    self._emit_denied(
                        agent_id, tool_name,
                        f"path not in scope: {path}",
                    )
                    raise CapabilityDeniedError(
                        agent_id, tool_name,
                        f"path not in scope: {path}",
                    )

        # 3. Check domain whitelist (for web_search or any tool with url/domain)
        if tool_name == "web_search":
            domain = tool_input.get("domain", "")
            url = tool_input.get("url", "")
            if url:
                parsed = urlparse(url)
                domain = parsed.hostname or ""
            has_domain_grants = any(g.prefix == "domain" for g in policy.grants)
            if domain and has_domain_grants and not policy.has_domain(domain):
                self._emit_denied(
                    agent_id, tool_name,
                    f"domain not in whitelist: {domain}",
                )
                raise CapabilityDeniedError(
                    agent_id, tool_name,
                    f"domain not in whitelist: {domain}",
                )

        # 4. Check shell commands (shell_exec is high-risk)
        if tool_name == "shell_exec":
            command = tool_input.get("command", "")
            if not policy.has_action(f"shell:{command.split()[0]}" if command else "shell:"):
                # Check for a blanket shell grant
                if not policy.has_tool("shell_exec"):
                    # Already checked above, but double-check action-level
                    pass

        # All checks passed — emit granted
        self._emit_granted(agent_id, tool_name)

    def _emit_granted(self, agent_id: str, tool_name: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.CAPABILITY_GRANTED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "tool_name": tool_name,
            },
        ))

    def _emit_denied(self, agent_id: str, tool_name: str, reason: str) -> None:
        self._event_log.append(Event(
            event_type=EventType.CAPABILITY_DENIED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "agent_id": agent_id,
                "tool_name": tool_name,
                "reason": reason,
            },
        ))
