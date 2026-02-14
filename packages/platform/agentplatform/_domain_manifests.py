"""Built-in domain pack manifests for LabOS and CodeOS."""

from __future__ import annotations

from agentos.runtime.domain_registry import (
    DomainPackManifest,
    ToolManifestEntry,
    WorkflowManifestEntry,
)
from agentos.runtime.role_template import RoleTemplate
from agentos.schemas.budget import BudgetSpec

# ── LabOS Manifest ──────────────────────────────────────────────────

_LABOS_TOOLS = [
    ToolManifestEntry(
        name="dataset_loader",
        description="Load a dataset and compute a reproducibility checksum",
        side_effect="READ",
        factory="labos.tools.dataset:DatasetTool",
    ),
    ToolManifestEntry(
        name="python_runner",
        description="Train an sklearn model on a cached dataset and evaluate accuracy",
        side_effect="PURE",
        factory="labos.tools.python_runner:PythonRunnerTool",
    ),
    ToolManifestEntry(
        name="plot_generator",
        description="Generate a confusion matrix PNG from experiment results",
        side_effect="WRITE",
        factory="labos.tools.plot:PlotTool",
    ),
    ToolManifestEntry(
        name="reviewer",
        description="Validate a ReproducibilityRecord for completeness and correctness",
        side_effect="PURE",
        factory="labos.tools.reviewer:ReviewerTool",
    ),
]

_LABOS_ROLES = [
    RoleTemplate(
        name="planner",
        display_name="Planning Agent",
        description="Writes experiment plans as JSON based on experiment configuration",
        system_prompt=(
            "You are a PlanningAgent. Write an experiment plan as JSON to "
            "experiment_plan.json. Respond with JSON tool calls only."
        ),
        tool_names=["file_write"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=10_000, max_tool_calls=5,
            max_time_seconds=60.0, max_recursion_depth=1,
        ),
        max_steps=10,
    ),
    RoleTemplate(
        name="data_experimenter",
        display_name="Data & Experiment Agent",
        description="Loads datasets and trains ML models",
        system_prompt=(
            "You are a DataExperimentAgent. Load the dataset, then train and "
            "evaluate the model. Respond with JSON tool calls only."
        ),
        tool_names=["dataset_loader", "python_runner"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=20_000, max_tool_calls=10,
            max_time_seconds=120.0, max_recursion_depth=1,
        ),
        max_steps=15,
    ),
    RoleTemplate(
        name="analyst",
        display_name="Analysis Agent",
        description="Generates plots and writes analysis notes",
        system_prompt=(
            "You are an AnalysisAgent. Generate a confusion matrix plot and "
            "write analysis notes. Respond with JSON tool calls only."
        ),
        tool_names=["plot_generator", "file_write"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=15_000, max_tool_calls=10,
            max_time_seconds=90.0, max_recursion_depth=1,
        ),
        max_steps=10,
    ),
    RoleTemplate(
        name="writer",
        display_name="Writing Agent",
        description="Reads analysis and writes a paper summarizing findings",
        system_prompt=(
            "You are a WritingAgent. Read the analysis notes and write a paper "
            "summarizing the experiment findings. Respond with JSON tool calls only."
        ),
        tool_names=["file_read", "file_write"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=20_000, max_tool_calls=10,
            max_time_seconds=90.0, max_recursion_depth=1,
        ),
        max_steps=15,
    ),
    RoleTemplate(
        name="reviewer",
        display_name="Review Agent",
        description="Validates reproducibility of the entire pipeline",
        system_prompt=(
            "You are a ReviewAgent. Validate the reproducibility of the "
            "entire experiment pipeline. Respond with JSON tool calls only."
        ),
        tool_names=["reviewer"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=10_000, max_tool_calls=5,
            max_time_seconds=60.0, max_recursion_depth=1,
        ),
        max_steps=10,
    ),
]

_LABOS_WORKFLOWS = [
    WorkflowManifestEntry(
        name="ml_replication",
        description="Single-pass ML experiment replication (DAG pipeline)",
        factory="labos.workflows.ml_replication:build_dag_workflow",
        default_roles=[],
    ),
    WorkflowManifestEntry(
        name="multi_agent_research",
        description="5-phase multi-agent research pipeline (planning → data → analysis → writing → review)",
        factory="labos.workflows.multi_agent_research:build_research_dag",
        default_roles=["planner", "data_experimenter", "analyst", "writer", "reviewer"],
    ),
]

LABOS_MANIFEST = DomainPackManifest(
    name="labos",
    display_name="Lab Research OS",
    description="Scientific workflow automation — ML experiment replication and multi-agent research",
    version="0.1.0",
    tools=_LABOS_TOOLS,
    role_templates=_LABOS_ROLES,
    workflows=_LABOS_WORKFLOWS,
)

# ── CodeOS Manifest ─────────────────────────────────────────────────

_CODEOS_TOOLS = [
    ToolManifestEntry(
        name="file_read",
        description="Read the contents of a file within the workspace",
        side_effect="READ",
        factory="codeos.tools.file_read:FileReadTool",
    ),
    ToolManifestEntry(
        name="file_write",
        description="Write content to a file within the workspace",
        side_effect="WRITE",
        factory="codeos.tools.file_write:FileWriteTool",
    ),
    ToolManifestEntry(
        name="grep",
        description="Search for a regex pattern in files within the workspace",
        side_effect="READ",
        factory="codeos.tools.grep:GrepTool",
    ),
    ToolManifestEntry(
        name="run_command",
        description="Execute a shell command within the workspace",
        side_effect="DESTRUCTIVE",
        factory="codeos.tools.run_command:RunCommandTool",
    ),
    ToolManifestEntry(
        name="git_status",
        description="Get the git status of the workspace repository",
        side_effect="READ",
        factory="codeos.tools.git_status:GitStatusTool",
    ),
    ToolManifestEntry(
        name="git_diff",
        description="Get the git diff output for the workspace repository",
        side_effect="READ",
        factory="codeos.tools.git_diff:GitDiffTool",
    ),
    ToolManifestEntry(
        name="git_commit",
        description="Create a git commit in the workspace repository",
        side_effect="WRITE",
        factory="codeos.tools.git_commit:GitCommitTool",
    ),
]

_CODEOS_ROLES = [
    RoleTemplate(
        name="coder",
        display_name="Coding Agent",
        description="Reads, writes, and edits code files within a workspace",
        system_prompt=(
            "You are a coding agent. Use the available file and shell tools "
            "to implement the requested changes. Respond with JSON tool calls only."
        ),
        tool_names=["file_read", "file_write", "grep", "run_command"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=50_000, max_tool_calls=30,
            max_time_seconds=300.0, max_recursion_depth=1,
        ),
        max_steps=50,
    ),
    RoleTemplate(
        name="code_reviewer",
        display_name="Code Review Agent",
        description="Reviews code changes for correctness and style",
        system_prompt=(
            "You are a code review agent. Read the code changes and provide "
            "detailed review feedback. Respond with JSON tool calls only."
        ),
        tool_names=["file_read", "grep", "git_diff"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=30_000, max_tool_calls=20,
            max_time_seconds=120.0, max_recursion_depth=1,
        ),
        max_steps=20,
    ),
    RoleTemplate(
        name="architect",
        display_name="Architecture Agent",
        description="Plans implementation strategy and identifies affected files",
        system_prompt=(
            "You are an architecture agent. Analyze the codebase structure, "
            "plan the implementation, and identify files to modify. "
            "Respond with JSON tool calls only."
        ),
        tool_names=["file_read", "grep", "git_status"],
        suggested_model="llama3.1:latest",
        budget_profile=BudgetSpec(
            max_tokens=30_000, max_tool_calls=15,
            max_time_seconds=120.0, max_recursion_depth=1,
        ),
        max_steps=20,
    ),
]

_CODEOS_WORKFLOWS = [
    WorkflowManifestEntry(
        name="agent_coding",
        description="Single coding agent with file, shell, and git tools",
        factory="codeos.workflows.agent_coding:run_coding_agent",
        default_roles=["coder"],
    ),
]

CODEOS_MANIFEST = DomainPackManifest(
    name="codeos",
    display_name="Code OS",
    description="Coding domain — file operations, shell commands, and git workflows",
    version="0.1.0",
    tools=_CODEOS_TOOLS,
    role_templates=_CODEOS_ROLES,
    workflows=_CODEOS_WORKFLOWS,
)


def register_builtin_packs(registry: "DomainRegistry") -> None:  # noqa: F821
    """Register the built-in LabOS and CodeOS domain packs."""
    from agentos.runtime.domain_registry import DomainRegistry as _DR

    assert isinstance(registry, _DR)
    registry.register(LABOS_MANIFEST)
    registry.register(CODEOS_MANIFEST)
