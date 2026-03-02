"""GitCommitTool — create git commits within workspace."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import GitCommitInput, GitCommitOutput


class GitCommitTool(BaseTool):
    """Create a git commit in the workspace repository."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GitCommitInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GitCommitOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, GitCommitInput)
        cwd = str(self._workspace.root)

        # Stage specific files if provided
        if input_data.files:
            for file_path in input_data.files:
                result = subprocess.run(
                    ["git", "add", file_path],
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"git add failed for '{file_path}': {result.stderr}")

        # Create commit
        commit_result = subprocess.run(
            ["git", "commit", "-m", input_data.message],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if commit_result.returncode != 0:
            raise RuntimeError(f"git commit failed: {commit_result.stderr}")

        # Get commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        sha = sha_result.stdout.strip()

        # Count files committed
        show_result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        files_committed = len(
            [line for line in show_result.stdout.splitlines() if line.strip()]
        )

        return GitCommitOutput(
            sha=sha,
            message=input_data.message,
            files_committed=files_committed,
        )
