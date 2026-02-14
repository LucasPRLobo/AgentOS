"""Unit tests for DomainRegistry and manifest models."""

import pytest

from agentos.runtime.domain_registry import (
    DomainPackManifest,
    DomainRegistry,
    ToolManifestEntry,
    WorkflowManifestEntry,
    _import_from_path,
)
from agentos.runtime.role_template import RoleTemplate
from agentos.schemas.budget import BudgetSpec


def _make_manifest(name: str = "testpack") -> DomainPackManifest:
    return DomainPackManifest(
        name=name,
        display_name="Test Pack",
        description="A test domain pack",
        version="0.1.0",
        tools=[
            ToolManifestEntry(
                name="dataset_loader",
                description="Load a dataset",
                side_effect="READ",
                factory="labos.tools.dataset:DatasetTool",
            ),
        ],
        role_templates=[
            RoleTemplate(
                name="tester",
                display_name="Test Agent",
                description="A test role",
                system_prompt="You are a test agent.",
                tool_names=["dataset_loader"],
                budget_profile=BudgetSpec(
                    max_tokens=1000, max_tool_calls=5,
                    max_time_seconds=30.0, max_recursion_depth=1,
                ),
            ),
        ],
        workflows=[
            WorkflowManifestEntry(
                name="test_workflow",
                description="A test workflow",
                factory="labos.workflows.ml_replication:build_dag_workflow",
                default_roles=["tester"],
            ),
        ],
    )


class TestDomainPackManifest:
    def test_manifest_creation(self) -> None:
        m = _make_manifest()
        assert m.name == "testpack"
        assert m.display_name == "Test Pack"
        assert len(m.tools) == 1
        assert len(m.role_templates) == 1
        assert len(m.workflows) == 1

    def test_manifest_defaults(self) -> None:
        m = DomainPackManifest(
            name="minimal",
            display_name="Minimal",
            description="No tools/roles/workflows",
            version="0.0.1",
        )
        assert m.tools == []
        assert m.role_templates == []
        assert m.workflows == []


class TestDomainRegistry:
    def test_register_and_lookup(self) -> None:
        registry = DomainRegistry()
        manifest = _make_manifest()
        registry.register(manifest)
        assert registry.has_pack("testpack")
        assert registry.get_pack("testpack") is manifest

    def test_list_packs(self) -> None:
        registry = DomainRegistry()
        m1 = _make_manifest("pack_a")
        m2 = _make_manifest("pack_b")
        registry.register(m1)
        registry.register(m2)
        packs = registry.list_packs()
        assert len(packs) == 2
        assert {p.name for p in packs} == {"pack_a", "pack_b"}

    def test_duplicate_name_raises(self) -> None:
        registry = DomainRegistry()
        registry.register(_make_manifest("dup"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_make_manifest("dup"))

    def test_get_unknown_pack_raises(self) -> None:
        registry = DomainRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get_pack("nonexistent")

    def test_has_pack_false(self) -> None:
        registry = DomainRegistry()
        assert not registry.has_pack("missing")

    def test_load_tool_dynamic_import(self) -> None:
        # Use an agentos-internal class to avoid sklearn dependency
        registry = DomainRegistry()
        entry = ToolManifestEntry(
            name="tool_registry",
            description="A registry (used to test dynamic import)",
            side_effect="PURE",
            factory="agentos.tools.registry:ToolRegistry",
        )
        obj = registry.load_tool(entry)
        # ToolRegistry is not a BaseTool, but load_tool does instantiate it
        assert obj is not None

    def test_get_role_template(self) -> None:
        registry = DomainRegistry()
        registry.register(_make_manifest())
        role = registry.get_role_template("testpack", "tester")
        assert role.name == "tester"
        assert role.display_name == "Test Agent"

    def test_get_role_template_unknown_raises(self) -> None:
        registry = DomainRegistry()
        registry.register(_make_manifest())
        with pytest.raises(KeyError, match="not found"):
            registry.get_role_template("testpack", "nonexistent")

    def test_len(self) -> None:
        registry = DomainRegistry()
        assert len(registry) == 0
        registry.register(_make_manifest())
        assert len(registry) == 1


class TestImportFromPath:
    def test_valid_import(self) -> None:
        cls = _import_from_path("agentos.tools.registry:ToolRegistry")
        assert cls.__name__ == "ToolRegistry"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid factory path"):
            _import_from_path("labos.tools.dataset.DatasetTool")

    def test_missing_module_raises(self) -> None:
        with pytest.raises(ModuleNotFoundError):
            _import_from_path("nonexistent.module:Foo")
