"""Tests for the SandboxManager and sandbox isolation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.capability import CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.schemas.sandbox import SandboxConfig, SandboxLevel
from agentos.security.sandbox import (
    ContainerSandbox,
    NamespaceSandbox,
    NoopSandbox,
    SandboxManager,
)


@pytest.fixture
def sandbox_manager(event_log, seq) -> SandboxManager:
    return SandboxManager(event_log=event_log, seq=seq, workflow_id="test-wf")


class TestSandboxLevels:
    def test_sandbox_none_creates_noop(self, sandbox_manager, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NONE)
        handle = sandbox_manager.create("agent-1", config, tmp_path)
        assert isinstance(handle, NoopSandbox)
        assert handle.level == SandboxLevel.NONE

    def test_sandbox_namespace_creates_namespace(self, sandbox_manager, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NAMESPACE)
        handle = sandbox_manager.create("agent-1", config, tmp_path)
        assert isinstance(handle, NamespaceSandbox)
        assert handle.level == SandboxLevel.NAMESPACE

    def test_sandbox_container_creates_container(self, sandbox_manager, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER)
        handle = sandbox_manager.create("agent-1", config, tmp_path)
        assert isinstance(handle, ContainerSandbox)
        assert handle.level == SandboxLevel.CONTAINER


class TestSandboxEvents:
    def test_creation_event(self, sandbox_manager, event_log, tmp_path):
        config = SandboxConfig(
            level=SandboxLevel.NAMESPACE,
            network_enabled=False,
            memory_limit_mb=512,
        )
        sandbox_manager.create("agent-1", config, tmp_path)
        events = event_log.query(event_type=EventType.SANDBOX_CREATED)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["agent_id"] == "agent-1"
        assert payload["level"] == "namespace"
        assert payload["network_enabled"] is False
        assert payload["memory_limit_mb"] == 512
        assert events[0].schema_version == "0.2"

    def test_destruction_event(self, sandbox_manager, event_log, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NONE)
        sandbox_manager.create("agent-1", config, tmp_path)
        sandbox_manager.destroy("agent-1")
        events = event_log.query(event_type=EventType.SANDBOX_DESTROYED)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "agent-1"

    def test_destroy_nonexistent_noop(self, sandbox_manager, event_log):
        sandbox_manager.destroy("nonexistent")
        events = event_log.query(event_type=EventType.SANDBOX_DESTROYED)
        assert len(events) == 0

    def test_violation_event(self, sandbox_manager, event_log):
        sandbox_manager.report_violation("agent-1", "Attempted network access")
        events = event_log.query(event_type=EventType.SANDBOX_VIOLATION)
        assert len(events) == 1
        assert events[0].payload["agent_id"] == "agent-1"
        assert events[0].payload["detail"] == "Attempted network access"


class TestNoopSandbox:
    def test_run_subprocess(self, tmp_path):
        sandbox = NoopSandbox(tmp_path)
        result = sandbox.run(["python", "-c", "print('hello')"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_teardown_is_noop(self, tmp_path):
        sandbox = NoopSandbox(tmp_path)
        sandbox.teardown()  # Should not raise


class TestNamespaceSandbox:
    def test_builds_unshare_command(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NAMESPACE, network_enabled=True)
        sandbox = NamespaceSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo", "test"])
            args = mock_run.call_args[0][0]
            assert args[:4] == ["unshare", "--pid", "--mount", "--fork"]
            assert "--net" not in args
            assert args[-2:] == ["echo", "test"]

    def test_network_disabled_adds_net_flag(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NAMESPACE, network_enabled=False)
        sandbox = NamespaceSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo", "test"])
            args = mock_run.call_args[0][0]
            assert "--net" in args


class TestContainerSandbox:
    def test_builds_docker_command(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER)
        sandbox = ContainerSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["python", "script.py"])
            args = mock_run.call_args[0][0]
            assert args[0] == "docker"
            assert "run" in args
            assert "--rm" in args
            assert f"{tmp_path}:/workspace" in " ".join(args)

    def test_memory_limit(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER, memory_limit_mb=256)
        sandbox = ContainerSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo"])
            args = mock_run.call_args[0][0]
            assert "--memory" in args
            idx = args.index("--memory")
            assert args[idx + 1] == "256m"

    def test_cpu_limit(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER, cpu_limit=2.0)
        sandbox = ContainerSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo"])
            args = mock_run.call_args[0][0]
            assert "--cpus" in args
            idx = args.index("--cpus")
            assert args[idx + 1] == "2.0"

    def test_network_none(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER, network_enabled=False)
        sandbox = ContainerSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo"])
            args = mock_run.call_args[0][0]
            assert "--network" in args
            idx = args.index("--network")
            assert args[idx + 1] == "none"

    def test_readonly_filesystem(self, tmp_path):
        config = SandboxConfig(level=SandboxLevel.CONTAINER, filesystem_readonly=True)
        sandbox = ContainerSandbox(config, tmp_path)
        with patch("agentos.security.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = None
            sandbox.run(["echo"])
            args = mock_run.call_args[0][0]
            assert "--read-only" in args


class TestSandboxManagerLifecycle:
    def test_get_active_sandbox(self, sandbox_manager, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NONE)
        sandbox_manager.create("agent-1", config, tmp_path)
        handle = sandbox_manager.get("agent-1")
        assert handle is not None
        assert isinstance(handle, NoopSandbox)

    def test_get_nonexistent_returns_none(self, sandbox_manager):
        assert sandbox_manager.get("nonexistent") is None

    def test_destroy_removes_from_active(self, sandbox_manager, tmp_path):
        config = SandboxConfig(level=SandboxLevel.NONE)
        sandbox_manager.create("agent-1", config, tmp_path)
        sandbox_manager.destroy("agent-1")
        assert sandbox_manager.get("agent-1") is None


class TestCapabilityPolicySandbox:
    def test_default_sandbox_none(self):
        policy = CapabilityPolicy(agent_id="a1")
        assert policy.sandbox == SandboxLevel.NONE

    def test_sandbox_field_set(self):
        policy = CapabilityPolicy(agent_id="a1", sandbox=SandboxLevel.CONTAINER)
        assert policy.sandbox == SandboxLevel.CONTAINER

    def test_backward_compat_no_sandbox(self):
        """Policies without sandbox field default to NONE."""
        data = {"agent_id": "a1", "grants": [], "deny_by_default": True}
        policy = CapabilityPolicy.model_validate(data)
        assert policy.sandbox == SandboxLevel.NONE


class TestSandboxConfigDefaults:
    def test_defaults(self):
        config = SandboxConfig()
        assert config.level == SandboxLevel.NONE
        assert config.network_enabled is True
        assert config.filesystem_readonly is False
        assert config.memory_limit_mb == 0
        assert config.cpu_limit == 0.0
        assert config.allowed_paths == []

    def test_serialization_roundtrip(self):
        config = SandboxConfig(
            level=SandboxLevel.CONTAINER,
            network_enabled=False,
            memory_limit_mb=1024,
            cpu_limit=4.0,
        )
        data = config.model_dump(mode="json")
        restored = SandboxConfig.model_validate(data)
        assert restored == config
