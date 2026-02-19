"""workspace_status tool — list workspace files with metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentos.runtime.workspace_manifest import WorkspaceManifest
from agentos.tools.base import BaseTool, SideEffect


class WorkspaceStatusInput(BaseModel):
    """Input for workspace_status tool."""

    filter_agent: str = Field(
        default="",
        description="Filter files by creating agent name (optional, empty = all files)",
    )


class WorkspaceStatusOutput(BaseModel):
    """Output for workspace_status tool."""

    files: list[dict] = Field(default_factory=list)
    total_count: int = 0


class WorkspaceStatusTool(BaseTool):
    """List all files in the shared workspace with metadata."""

    def __init__(self, *, manifest: WorkspaceManifest) -> None:
        self._manifest = manifest

    @property
    def name(self) -> str:
        return "workspace_status"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return WorkspaceStatusInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return WorkspaceStatusOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, WorkspaceStatusInput)

        if input_data.filter_agent:
            entries = self._manifest.files_by_agent(input_data.filter_agent)
        else:
            entries = self._manifest.list_files()

        files = [
            {
                "path": e.path,
                "size_bytes": e.size_bytes,
                "created_by_agent": e.created_by_agent,
                "modified": e.modified,
            }
            for e in entries
        ]
        return WorkspaceStatusOutput(files=files, total_count=len(files))
