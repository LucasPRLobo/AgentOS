"""Unit tests for workspace_status tool."""

from __future__ import annotations

from agentos.runtime.workspace_manifest import WorkspaceManifest
from agentplatform.tools.workspace_status import (
    WorkspaceStatusInput,
    WorkspaceStatusOutput,
    WorkspaceStatusTool,
)


class TestWorkspaceStatusTool:
    def test_empty_workspace(self) -> None:
        manifest = WorkspaceManifest()
        tool = WorkspaceStatusTool(manifest=manifest)
        output = tool.execute(WorkspaceStatusInput())
        assert isinstance(output, WorkspaceStatusOutput)
        assert output.total_count == 0
        assert output.files == []

    def test_list_all_files(self) -> None:
        manifest = WorkspaceManifest()
        manifest.record_file("a.md", 100, "sha1", "Agent1")
        manifest.record_file("b.md", 200, "sha2", "Agent2")
        tool = WorkspaceStatusTool(manifest=manifest)
        output = tool.execute(WorkspaceStatusInput())
        assert output.total_count == 2
        paths = [f["path"] for f in output.files]
        assert "a.md" in paths
        assert "b.md" in paths

    def test_filter_by_agent(self) -> None:
        manifest = WorkspaceManifest()
        manifest.record_file("a.md", 100, "sha1", "Alice")
        manifest.record_file("b.md", 200, "sha2", "Bob")
        manifest.record_file("c.md", 300, "sha3", "Alice")
        tool = WorkspaceStatusTool(manifest=manifest)

        output = tool.execute(WorkspaceStatusInput(filter_agent="Alice"))
        assert output.total_count == 2
        assert all(f["created_by_agent"] == "Alice" for f in output.files)

    def test_filter_no_match(self) -> None:
        manifest = WorkspaceManifest()
        manifest.record_file("a.md", 100, "sha1", "Alice")
        tool = WorkspaceStatusTool(manifest=manifest)

        output = tool.execute(WorkspaceStatusInput(filter_agent="Nobody"))
        assert output.total_count == 0

    def test_output_schema_fields(self) -> None:
        manifest = WorkspaceManifest()
        manifest.record_file("report.md", 4200, "sha_r", "Writer")
        tool = WorkspaceStatusTool(manifest=manifest)
        output = tool.execute(WorkspaceStatusInput())

        assert output.total_count == 1
        f = output.files[0]
        assert f["path"] == "report.md"
        assert f["size_bytes"] == 4200
        assert f["created_by_agent"] == "Writer"
        assert "modified" in f

    def test_tool_properties(self) -> None:
        manifest = WorkspaceManifest()
        tool = WorkspaceStatusTool(manifest=manifest)
        assert tool.name == "workspace_status"
        assert tool.version == "1.0.0"
        assert tool.side_effect.value == "READ"
