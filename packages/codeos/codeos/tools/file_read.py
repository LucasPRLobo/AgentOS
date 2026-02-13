"""FileReadTool — read file contents within workspace scope."""

from __future__ import annotations

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import FileReadInput, FileReadOutput


class FileReadTool(BaseTool):
    """Read the contents of a file within the workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileReadInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return FileReadOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, FileReadInput)
        resolved = self._workspace.resolve_path(input_data.path)

        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {input_data.path}")

        all_lines = resolved.read_text(encoding="utf-8").splitlines()
        total_lines = len(all_lines)

        offset = input_data.offset
        limit = input_data.limit

        if limit > 0:
            selected = all_lines[offset : offset + limit]
        else:
            selected = all_lines[offset:]

        content = "\n".join(selected)
        return FileReadOutput(
            content=content,
            lines=len(selected),
            total_lines=total_lines,
        )
