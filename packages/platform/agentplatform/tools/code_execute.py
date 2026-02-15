"""Code execution tool — run code in a sandboxed subprocess."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect


# ── Schemas ────────────────────────────────────────────────────────


class CodeExecuteInput(BaseModel):
    """Input schema for code execution."""

    language: Literal["python", "node"] = Field(
        default="python", description="Programming language to execute"
    )
    code: str = Field(..., description="Source code to execute")
    timeout_seconds: int = Field(
        default=30, ge=1, le=300, description="Max execution time in seconds"
    )


class CodeExecuteOutput(BaseModel):
    """Output schema for code execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    error: str | None = None


# ── Tool ───────────────────────────────────────────────────────────

_LANGUAGE_COMMANDS: dict[str, list[str]] = {
    "python": [sys.executable, "-c"],
    "node": ["node", "-e"],
}


class CodeExecuteTool(BaseTool):
    """Execute code in a sandboxed subprocess with resource limits."""

    def __init__(self, *, workspace_dir: str | Path = ".") -> None:
        self._workspace_dir = Path(workspace_dir)

    @property
    def name(self) -> str:
        return "code_execute"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return CodeExecuteInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return CodeExecuteOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, CodeExecuteInput)

        cmd_prefix = _LANGUAGE_COMMANDS.get(input_data.language)
        if cmd_prefix is None:
            return CodeExecuteOutput(
                error=f"Unsupported language: {input_data.language}"
            )

        cmd = [*cmd_prefix, input_data.code]
        env = self._restricted_env()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=input_data.timeout_seconds,
                cwd=str(self._workspace_dir),
                env=env,
                preexec_fn=self._set_resource_limits,
            )
            return CodeExecuteOutput(
                stdout=result.stdout[:50_000],
                stderr=result.stderr[:50_000],
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return CodeExecuteOutput(
                stdout="",
                stderr="Execution timed out",
                exit_code=-1,
                timed_out=True,
            )
        except OSError as exc:
            return CodeExecuteOutput(error=f"Failed to execute: {exc}")

    @staticmethod
    def _restricted_env() -> dict[str, str]:
        """Build a minimal environment for the subprocess."""
        import os

        env: dict[str, str] = {}
        for key in ("PATH", "HOME", "LANG", "TERM", "PYTHONPATH"):
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    @staticmethod
    def _set_resource_limits() -> None:
        """Apply resource limits (Linux only). Called in child process via preexec_fn."""
        try:
            import resource

            # 512 MB memory limit
            mem_limit = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))

            # 60 second CPU limit
            resource.setrlimit(resource.RLIMIT_CPU, (60, 60))

            # 100 MB max file size
            file_limit = 100 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
        except (ImportError, ValueError, OSError):
            pass  # Non-Linux or limits not supported
