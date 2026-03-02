"""FileWriteTool — write file contents within workspace scope."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import FileWriteInput, FileWriteOutput


class FileWriteTool(BaseTool):
    """Write content to a file within the workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileWriteInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return FileWriteOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.WRITE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, FileWriteInput)
        resolved = self._workspace.resolve_path(input_data.path)

        # Ensure parent directory exists
        resolved.parent.mkdir(parents=True, exist_ok=True)

        content_bytes = input_data.content.encode("utf-8")
        resolved.write_bytes(content_bytes)
        sha = hashlib.sha256(content_bytes).hexdigest()

        return FileWriteOutput(
            path=input_data.path,
            bytes_written=len(content_bytes),
            sha256=sha,
        )
