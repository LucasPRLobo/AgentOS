"""GitDiffTool — get git diff output within workspace."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import GitDiffInput, GitDiffOutput


class GitDiffTool(BaseTool):
    """Get the git diff output for the workspace repository."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "git_diff"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GitDiffInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GitDiffOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, GitDiffInput)
        cwd = str(self._workspace.root)

        cmd = ["git", "diff"]
        if input_data.staged:
            cmd.append("--cached")
        if input_data.path:
            cmd.append("--")
            cmd.append(input_data.path)

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        diff_text = result.stdout

        # Count files changed from diff stat
        stat_cmd = ["git", "diff", "--stat"]
        if input_data.staged:
            stat_cmd.append("--cached")
        if input_data.path:
            stat_cmd.append("--")
            stat_cmd.append(input_data.path)

        stat_result = subprocess.run(stat_cmd, capture_output=True, text=True, cwd=cwd)
        # Count lines that look like file entries (contain "|")
        files_changed = sum(
            1 for line in stat_result.stdout.splitlines() if "|" in line
        )

        return GitDiffOutput(diff=diff_text, files_changed=files_changed)
