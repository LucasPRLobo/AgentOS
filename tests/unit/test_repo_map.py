"""Tests for the repo map generator."""

import pytest
from pathlib import Path

from agentos.workspace.repo_map import RepoMapGenerator, write_workspace_claude_md


@pytest.fixture
def project_dir():
    """Use the actual AgentOS project for testing."""
    d = Path(__file__).resolve().parent.parent.parent
    if (d / "agentos").is_dir():
        return d
    pytest.skip("Cannot find project root")


class TestRepoMapGenerator:
    def test_generate_produces_output(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        result = gen.generate()
        assert len(result) > 100
        assert "Repository Map" in result

    def test_contains_key_classes(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        result = gen.generate()
        # Should contain key AgentOS classes
        assert "EventLog" in result or "EventType" in result
        assert "BoardManager" in result or "BoardPost" in result

    def test_contains_structure(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        result = gen.generate()
        assert "kernel/" in result
        assert "comms/" in result
        assert "workspace/" in result

    def test_within_token_budget(self, project_dir):
        budget = 1500
        gen = RepoMapGenerator(project_dir, token_budget=budget)
        result = gen.generate()
        estimated_tokens = len(result) // 4
        # Allow 20% overshoot since estimation is rough
        assert estimated_tokens < budget * 1.2

    def test_small_budget(self, project_dir):
        gen = RepoMapGenerator(project_dir, token_budget=500)
        result = gen.generate()
        # Should still produce something — structure section is fixed,
        # but key modules section gets truncated
        assert len(result) > 50
        # With 500 token budget, result should be smaller than full 1500-token version
        full_gen = RepoMapGenerator(project_dir, token_budget=1500)
        full_result = full_gen.generate()
        assert len(result) <= len(full_result)

    def test_cache_works(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        result1 = gen.generate()
        result2 = gen.generate()
        # Second call should return cached (identical content)
        assert result1 == result2

    def test_stale_detection(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        # If cache doesn't exist, it's stale
        if gen.cache_path.exists():
            gen.cache_path.unlink()
        assert gen.is_stale()

    def test_frontend_components(self, project_dir):
        gen = RepoMapGenerator(project_dir)
        result = gen.generate()
        # Should include frontend components if they exist
        frontend = project_dir / "agentos" / "dashboard" / "frontend" / "src"
        if frontend.exists():
            assert "Frontend" in result

    def test_handles_syntax_errors(self, tmp_path):
        """Generator should not crash on files with syntax errors."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "bad.py").write_text("def broken(:\n  pass")
        (pkg / "good.py").write_text("class Good:\n  def method(self): pass\n\nimport pkg.bad\n")
        gen = RepoMapGenerator(tmp_path)
        result = gen.generate()
        # Should still work, good.py parsed but bad.py skipped
        assert "Repository Map" in result


class TestWorkspaceClaudeMd:
    def test_writes_file(self, tmp_path):
        from agentos.workspace.schemas import WorkspaceConfig, WorkspaceParticipant

        config = WorkspaceConfig(
            name="Test Workspace",
            goal="Build something cool",
            team=[
                WorkspaceParticipant(name="agent-1", specialization="Research"),
                WorkspaceParticipant(name="lucas", type="human"),
            ],
        )
        write_workspace_claude_md(tmp_path, config, "# Repo Map\ntest")
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "Build something cool" in content
        assert "agent-1" in content
        assert "Repo Map" in content
        assert "check_messages" in content
