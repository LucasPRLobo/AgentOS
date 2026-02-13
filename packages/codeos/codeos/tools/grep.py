"""GrepTool — search file contents within workspace scope."""

from __future__ import annotations

import fnmatch
import re

from pydantic import BaseModel

from agentos.runtime.workspace import Workspace
from agentos.tools.base import BaseTool, SideEffect
from codeos.domain.schemas import GrepInput, GrepMatch, GrepOutput


class GrepTool(BaseTool):
    """Search for a regex pattern in files within the workspace."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "grep"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return GrepInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return GrepOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.READ

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, GrepInput)
        search_path = self._workspace.resolve_path(input_data.path)
        pattern = re.compile(input_data.pattern)
        matches: list[GrepMatch] = []

        if search_path.is_file():
            files = [search_path]
        elif search_path.is_dir():
            files = [
                f
                for f in search_path.rglob("*")
                if f.is_file() and fnmatch.fnmatch(f.name, input_data.glob)
            ]
        else:
            return GrepOutput(matches=[])

        for file_path in sorted(files):
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, PermissionError):
                continue
            for line_num, line in enumerate(lines, 1):
                if pattern.search(line):
                    rel_path = str(file_path.relative_to(self._workspace.root))
                    matches.append(
                        GrepMatch(file=rel_path, line=line_num, content=line)
                    )

        return GrepOutput(matches=matches)
