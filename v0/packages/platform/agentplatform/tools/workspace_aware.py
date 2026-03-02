"""EventEmittingFileWriteTool — wraps file_write to emit file events."""

from __future__ import annotations

import threading

from pydantic import BaseModel

from agentos.core.identifiers import RunId
from agentos.runtime.event_log import EventLog
from agentos.runtime.workspace_manifest import WorkspaceManifest
from agentos.schemas.events import FileCreated, FileModified
from agentos.tools.base import BaseTool, SideEffect


class FileEventSeqCounter:
    """Thread-safe sequence counter for file events (shared across wrappers)."""

    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            v = self._value
            self._value += 1
            return v


class EventEmittingFileWriteTool(BaseTool):
    """Wraps any file_write tool to emit file events and update manifest."""

    def __init__(
        self,
        inner: BaseTool,
        event_log: EventLog,
        manifest: WorkspaceManifest,
        workspace_run_id: RunId,
        seq_counter: FileEventSeqCounter,
        agent_name: str,
    ) -> None:
        self._inner = inner
        self._event_log = event_log
        self._manifest = manifest
        self._ws_run_id = workspace_run_id
        self._seq = seq_counter
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def version(self) -> str:
        return self._inner.version

    @property
    def input_schema(self) -> type[BaseModel]:
        return self._inner.input_schema

    @property
    def output_schema(self) -> type[BaseModel]:
        return self._inner.output_schema

    @property
    def side_effect(self) -> SideEffect:
        return self._inner.side_effect

    def execute(self, input_data: BaseModel) -> BaseModel:
        output = self._inner.execute(input_data)

        # Extract file metadata from output (FileWriteOutput convention)
        file_path = getattr(output, "path", "")
        size_bytes = getattr(output, "bytes_written", 0)
        sha256 = getattr(output, "sha256", "")

        if file_path:
            is_new, _entry = self._manifest.record_file(
                path=file_path,
                size=size_bytes,
                sha256=sha256,
                agent_name=self._agent_name,
            )

            event_cls = FileCreated if is_new else FileModified
            self._event_log.append(
                event_cls(
                    run_id=self._ws_run_id,
                    seq=self._seq.next(),
                    payload={
                        "file_path": file_path,
                        "size_bytes": size_bytes,
                        "sha256": sha256,
                        "created_by_agent": self._agent_name,
                    },
                )
            )

        return output
