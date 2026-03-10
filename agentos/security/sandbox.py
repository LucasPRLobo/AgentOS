"""Process isolation manager — sandbox lifecycle for agent execution."""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType
from agentos.schemas.sandbox import SandboxConfig, SandboxLevel

logger = logging.getLogger(__name__)


class SandboxHandle(ABC):
    """Abstract handle for a running sandbox."""

    @abstractmethod
    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a command inside the sandbox."""

    def wrap_command(self, cmd: list[str]) -> list[str]:
        """Return the command with sandbox wrapper prepended.

        Used by streaming code paths that need Popen instead of run.
        Default: no wrapping.
        """
        return cmd

    @abstractmethod
    def teardown(self) -> None:
        """Tear down the sandbox and release resources."""

    @property
    @abstractmethod
    def level(self) -> SandboxLevel:
        """Return the sandbox isolation level."""


class NoopSandbox(SandboxHandle):
    """No isolation — direct subprocess (V1 behavior)."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=self._workspace, **kwargs)

    def teardown(self) -> None:
        pass

    @property
    def level(self) -> SandboxLevel:
        return SandboxLevel.NONE


class NamespaceSandbox(SandboxHandle):
    """Linux namespace isolation via unshare(2)."""

    def __init__(self, config: SandboxConfig, workspace: Path) -> None:
        self._config = config
        self._workspace = workspace

    def _unshare_prefix(self) -> list[str]:
        flags = ["unshare", "--pid", "--mount", "--fork"]
        if not self._config.network_enabled:
            flags.append("--net")
        return flags

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        # Use cwd from kwargs if provided, otherwise fall back to construction workspace
        if "cwd" not in kwargs:
            kwargs["cwd"] = self._workspace
        return subprocess.run(self._unshare_prefix() + cmd, **kwargs)

    def wrap_command(self, cmd: list[str]) -> list[str]:
        return self._unshare_prefix() + cmd

    def teardown(self) -> None:
        pass

    @property
    def level(self) -> SandboxLevel:
        return SandboxLevel.NAMESPACE


class ContainerSandbox(SandboxHandle):
    """Docker-based full isolation."""

    def __init__(self, config: SandboxConfig, workspace: Path) -> None:
        self._config = config
        self._workspace = workspace
        self._container_id: str | None = None

    def run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self._workspace}:/workspace",
            "-w",
            "/workspace",
        ]
        if not self._config.network_enabled:
            docker_cmd.extend(["--network", "none"])
        if self._config.memory_limit_mb > 0:
            docker_cmd.extend(["--memory", f"{self._config.memory_limit_mb}m"])
        if self._config.cpu_limit > 0:
            docker_cmd.extend(["--cpus", str(self._config.cpu_limit)])
        if self._config.filesystem_readonly:
            docker_cmd.append("--read-only")
        docker_cmd.extend(["python:3.11-slim"] + cmd)
        return subprocess.run(docker_cmd, **kwargs)

    def teardown(self) -> None:
        if self._container_id:
            subprocess.run(
                ["docker", "stop", self._container_id],
                capture_output=True,
            )

    @property
    def level(self) -> SandboxLevel:
        return SandboxLevel.CONTAINER


class SandboxManager:
    """Manages sandbox lifecycle for agent execution.

    Three isolation levels:
    - none: Direct subprocess (V1 behavior)
    - namespace: Linux unshare(2) — PID, mount, network namespaces
    - container: Docker run with resource limits
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._active: dict[str, SandboxHandle] = {}

    def create(
        self, agent_id: str, config: SandboxConfig, workspace: Path,
    ) -> SandboxHandle:
        """Create a sandbox for an agent. Emits sandbox.created event.

        Tests runtime availability at creation time. If namespace isolation
        requires root/CAP_SYS_ADMIN and is unavailable, falls back to
        NoopSandbox with a warning. Same for Docker-based container isolation.
        """
        actual_level = config.level

        if config.level == SandboxLevel.NONE:
            handle = NoopSandbox(workspace)
        elif config.level == SandboxLevel.NAMESPACE:
            # Test if unshare works (requires root or CAP_SYS_ADMIN)
            try:
                test = subprocess.run(
                    ["unshare", "--pid", "--fork", "true"],
                    capture_output=True, timeout=5,
                )
                if test.returncode != 0:
                    raise RuntimeError("unshare returned non-zero")
            except Exception:
                logger.warning(
                    "Namespace sandbox unavailable for %s "
                    "(unshare requires root). Falling back to no isolation.",
                    agent_id,
                )
                handle = NoopSandbox(workspace)
                actual_level = SandboxLevel.NONE
            else:
                handle = NamespaceSandbox(config, workspace)
        elif config.level == SandboxLevel.CONTAINER:
            # Test if Docker is available
            try:
                test = subprocess.run(
                    ["docker", "info"],
                    capture_output=True, timeout=10,
                )
                if test.returncode != 0:
                    raise RuntimeError("docker info returned non-zero")
            except Exception:
                logger.warning(
                    "Container sandbox unavailable for %s "
                    "(Docker not found). Falling back to no isolation.",
                    agent_id,
                )
                handle = NoopSandbox(workspace)
                actual_level = SandboxLevel.NONE
            else:
                handle = ContainerSandbox(config, workspace)
        else:
            raise ValueError(f"Unknown sandbox level: {config.level}")

        self._active[agent_id] = handle
        self._event_log.append(
            Event(
                event_type=EventType.SANDBOX_CREATED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={
                    "agent_id": agent_id,
                    "level": actual_level.value,
                    "requested_level": config.level.value,
                    "network_enabled": config.network_enabled,
                    "memory_limit_mb": config.memory_limit_mb,
                    "cpu_limit": config.cpu_limit,
                },
            )
        )
        return handle

    def destroy(self, agent_id: str) -> None:
        """Tear down an agent's sandbox. Emits sandbox.destroyed event."""
        handle = self._active.pop(agent_id, None)
        if handle is not None:
            handle.teardown()
            self._event_log.append(
                Event(
                    event_type=EventType.SANDBOX_DESTROYED,
                    workflow_id=self._workflow_id,
                    seq=self._seq.next(),
                    schema_version="0.2",
                    payload={"agent_id": agent_id},
                )
            )

    def get(self, agent_id: str) -> SandboxHandle | None:
        """Get the active sandbox handle for an agent."""
        return self._active.get(agent_id)

    def report_violation(self, agent_id: str, detail: str) -> None:
        """Report a sandbox violation. Emits sandbox.violation event."""
        self._event_log.append(
            Event(
                event_type=EventType.SANDBOX_VIOLATION,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                schema_version="0.2",
                payload={
                    "agent_id": agent_id,
                    "detail": detail,
                },
            )
        )
