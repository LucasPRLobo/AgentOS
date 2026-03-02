"""Coding agent workflow — orchestrate AgentRunner with CodeOS tools."""

from __future__ import annotations

from agentos.core.identifiers import RunId
from agentos.governance.budget_manager import BudgetManager
from agentos.governance.permissions import PermissionsEngine, PermissionPolicy
from agentos.governance.stop_conditions import StopConditionChecker
from agentos.lm.acceptance import AcceptanceChecker
from agentos.lm.agent_config import AgentConfig
from agentos.lm.agent_runner import AgentRunner
from agentos.lm.provider import BaseLMProvider
from agentos.runtime.event_log import EventLog, SQLiteEventLog
from agentos.runtime.workspace import Workspace, WorkspaceConfig
from agentos.schemas.budget import BudgetSpec
from agentos.tools.registry import ToolRegistry
from codeos.tools.file_read import FileReadTool
from codeos.tools.file_write import FileWriteTool
from codeos.tools.git_commit import GitCommitTool
from codeos.tools.git_diff import GitDiffTool
from codeos.tools.git_status import GitStatusTool
from codeos.tools.grep import GrepTool
from codeos.tools.run_command import RunCommandTool


def run_coding_agent(
    task_description: str,
    lm_provider: BaseLMProvider,
    workspace_config: WorkspaceConfig,
    *,
    event_log: EventLog | None = None,
    budget_spec: BudgetSpec | None = None,
    permission_policy: PermissionPolicy | None = None,
    acceptance_checker: AcceptanceChecker | None = None,
    agent_config: AgentConfig | None = None,
) -> tuple[RunId, str | None]:
    """Run a coding agent with all 7 CodeOS tools.

    Creates the full governance stack and registers tools, then
    delegates to AgentRunner.

    Returns (run_id, final_result).
    """
    if event_log is None:
        event_log = SQLiteEventLog(":memory:")

    # Create workspace
    workspace = Workspace(workspace_config)

    # Register all CodeOS tools
    registry = ToolRegistry()
    registry.register(FileReadTool(workspace))
    registry.register(FileWriteTool(workspace))
    registry.register(GrepTool(workspace))
    registry.register(RunCommandTool(workspace))
    registry.register(GitStatusTool(workspace))
    registry.register(GitDiffTool(workspace))
    registry.register(GitCommitTool(workspace))

    # Generate run_id for governance components
    from agentos.core.identifiers import generate_run_id

    rid = generate_run_id()

    # Build governance stack
    budget_manager = None
    if budget_spec is not None:
        budget_manager = BudgetManager(budget_spec, event_log, rid)

    stop_checker = StopConditionChecker(event_log, rid)

    permissions_engine = None
    if permission_policy is not None:
        permissions_engine = PermissionsEngine(permission_policy, event_log, rid)

    # Create and run the agent
    runner = AgentRunner(
        event_log,
        lm_provider,
        registry,
        budget_manager=budget_manager,
        stop_checker=stop_checker,
        permissions_engine=permissions_engine,
        acceptance_checker=acceptance_checker,
    )

    return runner.run(task_description, run_id=rid, config=agent_config)
