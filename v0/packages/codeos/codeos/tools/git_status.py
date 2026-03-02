"""GitStatusTool — get git repository status within workspace."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import GitStatusInput, GitStatusOutput


class GitStatusTool(BaseTool):
    """Get the git status of the workspace repository."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GitStatusInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GitStatusOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        cwd = str(self._workspace.root)

        # Get current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

        # Get porcelain status
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )

        staged: list[str] = []
        modified: list[str] = []
        untracked: list[str] = []

        if status_result.returncode == 0:
            for line in status_result.stdout.splitlines():
                if len(line) < 4:
                    continue
                index_status = line[0]
                worktree_status = line[1]
                file_path = line[3:]

                if index_status in "AMDRC":
                    staged.append(file_path)
                if worktree_status == "M":
                    modified.append(file_path)
                if index_status == "?" and worktree_status == "?":
                    untracked.append(file_path)

        return GitStatusOutput(
            branch=branch,
            staged=staged,
            modified=modified,
            untracked=untracked,
        )
