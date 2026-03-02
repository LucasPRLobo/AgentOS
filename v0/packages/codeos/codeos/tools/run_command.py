"""RunCommandTool — execute shell commands within workspace scope."""

from __future__ import annotations

import subprocess

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import RunCommandInput, RunCommandOutput


class RunCommandTool(BaseTool):
    """Execute a shell command within the workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "run_command"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return RunCommandInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return RunCommandOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.DESTRUCTIVE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, RunCommandInput)

        if not self._workspace.is_command_allowed(input_data.command):
            raise PermissionError(
                f"Command not allowed: '{input_data.command}'. "
                f"Allowed commands: {self._workspace.config.allowed_commands}"
            )

        try:
            result = subprocess.run(
                input_data.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=input_data.timeout,
                cwd=str(self._workspace.root),
            )
            return RunCommandOutput(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            return RunCommandOutput(
                stdout="",
                stderr=f"Command timed out after {input_data.timeout}s",
                exit_code=-1,
                timed_out=True,
            )
