"""File list tool — list files and directories within a workspace."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from agentos.tools.base import BaseTool, SideEffect


# ── Schemas ────────────────────────────────────────────────────────


class FileListInput(BaseModel):
    """Input schema for file listing."""

    path: str = Field(default=".", description="Directory path to list (relative to workspace)")
    pattern: str = Field(default="*", description="Glob pattern to filter files")
    recursive: bool = Field(default=False, description="List recursively")
    max_entries: int = Field(default=200, ge=1, le=1000, description="Maximum entries to return")


class FileEntry(BaseModel):
    """A single file or directory entry."""

    name: str
    path: str
    size: int = 0
    modified: str = ""
    type: str = "file"  # "file" or "directory"


class FileListOutput(BaseModel):
    """Output schema for file listing."""

    entries: list[FileEntry] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False
    error: str | None = None


# ── Tool ───────────────────────────────────────────────────────────


class FileListTool(BaseTool):
    """List files and directories, with optional glob filtering."""

    def __init__(self, *, workspace_dir: str | Path = ".") -> None:
        self._workspace_dir = Path(workspace_dir).resolve()

    @property
    def name(self) -> str:
        return "file_list"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileListInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return FileListOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, FileListInput)

        target = (self._workspace_dir / input_data.path).resolve()

        # Prevent path traversal outside workspace
        try:
            target.relative_to(self._workspace_dir)
        except ValueError:
            return FileListOutput(error="Path is outside workspace")

        if not target.is_dir():
            return FileListOutput(error=f"Not a directory: {input_data.path}")

        if input_data.recursive:
            matches = sorted(target.rglob(input_data.pattern))
        else:
            matches = sorted(target.glob(input_data.pattern))

        entries: list[FileEntry] = []
        for p in matches:
            if len(entries) >= input_data.max_entries:
                break
            try:
                stat = p.stat()
                rel = str(p.relative_to(self._workspace_dir))
                entries.append(FileEntry(
                    name=p.name,
                    path=rel,
                    size=stat.st_size,
                    modified=str(int(stat.st_mtime)),
                    type="directory" if p.is_dir() else "file",
                ))
            except OSError:
                continue

        return FileListOutput(
            entries=entries,
            total=len(entries),
            truncated=len(matches) > input_data.max_entries,
        )
