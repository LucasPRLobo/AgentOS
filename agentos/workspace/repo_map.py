"""Repo map generator — structural overview of the codebase for agents.

Generates a token-budgeted markdown map showing directory structure,
key classes/functions, and API surface. Agents receive this instead
of independently exploring the entire codebase.

Inspired by Aider's repo map (tree-sitter + PageRank) and the
RecursiveLM insight: context should be a queryable resource, not
a prompt payload. The map tells agents WHERE things are; they
query specific files on-demand.
"""

from __future__ import annotations

import ast
import logging
import re
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

# Compact directory descriptions — hardcoded for AgentOS
_DIR_DESCRIPTIONS = {
    "agentos/kernel/": "Core: event log, state machine, DAG executor, budget",
    "agentos/adapters/": "Agent adapters (Tier 1 API, Tier 2 Claude Code)",
    "agentos/comms/": "Board, messaging, MCP server, discussions",
    "agentos/workspace/": "Runtime, supervisor, backlog, coordinator, context",
    "agentos/dashboard/": "FastAPI backend + React frontend",
    "agentos/schemas/": "Pydantic v2 models (events, tasks, workflows)",
    "agentos/security/": "Capabilities, secrets, enforcer",
    "agentos/cli/": "Click CLI commands",
    "agentos/intelligence/": "Knowledge graph, specialization, fine-tuning",
    "agentos/validation/": "Workflow verification, adversarial checks",
    "tests/": "Unit, integration, e2e tests",
    "examples/": "Demo scripts + YAML workspace configs",
    "docs/": "Design documents, plans, research",
}


class RepoMapGenerator:
    """Generates a structural map of the codebase.

    Uses Python's ast module to extract class/function signatures.
    Ranks files by import frequency (most-imported = most important).
    Produces a token-budgeted markdown overview.
    """

    def __init__(self, project_dir: Path, token_budget: int = 1500):
        self._dir = project_dir
        self._budget = token_budget
        self._cache_dir = project_dir / ".agentos"

    @property
    def cache_path(self) -> Path:
        return self._cache_dir / "repo-map.md"

    def generate(self) -> str:
        """Generate or return cached repo map."""
        if self.cache_path.exists() and not self.is_stale():
            return self.cache_path.read_text()

        map_text = self._build()
        self._cache_dir.mkdir(exist_ok=True)
        self.cache_path.write_text(map_text)
        logger.info("Repo map generated: %d chars (~%d tokens)",
                     len(map_text), len(map_text) // 4)
        return map_text

    def is_stale(self) -> bool:
        """True if any source file is newer than the cached map."""
        if not self.cache_path.exists():
            return True
        cache_mtime = self.cache_path.stat().st_mtime
        for pattern in ("**/*.py", "**/*.tsx", "**/*.ts"):
            for f in self._dir.glob(pattern):
                if "__pycache__" in str(f) or "node_modules" in str(f):
                    continue
                if f.stat().st_mtime > cache_mtime:
                    return True
        return False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> str:
        """Build the complete repo map within token budget."""
        py_files = self._scan_python_files()
        import_ranks = self._rank_by_imports(py_files)
        frontend = self._scan_frontend()

        lines = ["# Repository Map", ""]

        # Directory tree
        lines.append("## Structure")
        for path, desc in _DIR_DESCRIPTIONS.items():
            if (self._dir / path.rstrip("/")).exists():
                lines.append(f"  {path:32s} {desc}")
        lines.append("")

        # Key Python modules with signatures
        lines.append("## Key Modules")
        chars_used = sum(len(l) + 1 for l in lines)
        budget_chars = self._budget * 4

        # Combine ranked imports with all files (ranked first, then unranked)
        seen = set()
        ordered = []
        for mod_path in import_ranks[:40]:
            if mod_path in py_files:
                ordered.append(mod_path)
                seen.add(mod_path)

        for sig_section in self._build_signature_sections(ordered, py_files, budget_chars - chars_used):
            lines.append(sig_section)

        # Frontend components
        if frontend:
            lines.append("")
            lines.append("## Frontend (React)")
            for comp in frontend[:20]:
                short_file = comp["file"].replace("agentos/dashboard/frontend/src/", "")
                lines.append(f"  {comp['name']:28s} {short_file}")

        # Final budget check
        result = "\n".join(lines) + "\n"
        if len(result) > budget_chars:
            # Truncate to budget
            result = result[:budget_chars - 20] + "\n...(truncated)\n"

        return result

    def _build_signature_sections(
        self, ordered_files: list[str], all_files: dict[str, Path],
        budget_chars: int,
    ) -> list[str]:
        """Build signature sections for ranked files within char budget."""
        sections = []
        chars = 0

        for mod_path in ordered_files:
            filepath = all_files.get(mod_path)
            if not filepath or not filepath.exists():
                continue

            sigs = self._extract_signatures(filepath)
            if not sigs:
                continue

            section_lines = [f"\n{mod_path}"]
            for sig in sigs[:6]:
                if sig["type"] == "class":
                    section_lines.append(f"  class {sig['name']}")
                    for m in sig["methods"][:6]:
                        section_lines.append(f"    {m}")
                else:
                    args = ", ".join(sig.get("args", []))
                    section_lines.append(f"  def {sig['name']}({args})")

            section_text = "\n".join(section_lines)
            if chars + len(section_text) > budget_chars:
                break
            sections.append(section_text)
            chars += len(section_text)

        return sections

    # ------------------------------------------------------------------
    # Python scanning
    # ------------------------------------------------------------------

    def _scan_python_files(self) -> dict[str, Path]:
        """Return {relative_path: filepath} for all Python files."""
        result = {}
        for f in self._dir.rglob("*.py"):
            rel = str(f.relative_to(self._dir))
            if any(skip in rel for skip in (
                "__pycache__", ".egg", "node_modules", "dist/", "build/",
                ".venv", "venv/",
            )):
                continue
            result[rel] = f
        return result

    def _extract_signatures(self, filepath: Path) -> list[dict]:
        """Extract class and function signatures using ast."""
        try:
            source = filepath.read_text()
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError, OSError):
            return []

        sigs = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not child.name.startswith("_"):
                            args = [a.arg for a in child.args.args if a.arg != "self"]
                            arg_str = ", ".join(args[:4])
                            prefix = "async " if isinstance(child, ast.AsyncFunctionDef) else ""
                            methods.append(f"{prefix}def {child.name}({arg_str})")
                sigs.append({
                    "type": "class",
                    "name": node.name,
                    "methods": methods,
                    "line": node.lineno,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args if a.arg != "self"][:4]
                    sigs.append({
                        "type": "function",
                        "name": node.name,
                        "args": args,
                        "line": node.lineno,
                    })
        return sigs

    def _rank_by_imports(self, files: dict[str, Path]) -> list[str]:
        """Rank files by how often they're imported (most-imported first)."""
        import_count: dict[str, int] = defaultdict(int)

        for filepath in files.values():
            try:
                tree = ast.parse(filepath.read_text())
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mod_path = node.module.replace(".", "/") + ".py"
                    import_count[mod_path] += 1

        return sorted(
            import_count.keys(),
            key=lambda k: import_count[k],
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Frontend scanning
    # ------------------------------------------------------------------

    def _scan_frontend(self) -> list[dict]:
        """Extract React component names from .tsx files."""
        components = []
        frontend_dir = self._dir / "agentos" / "dashboard" / "frontend" / "src"
        if not frontend_dir.exists():
            return []

        for f in sorted(frontend_dir.rglob("*.tsx")):
            try:
                content = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for m in re.finditer(
                r"export\s+(?:default\s+)?function\s+(\w+)", content
            ):
                components.append({
                    "name": m.group(1),
                    "file": str(f.relative_to(self._dir)),
                })
        return components


# ------------------------------------------------------------------
# Workspace CLAUDE.md
# ------------------------------------------------------------------

def write_workspace_claude_md(
    workspace_dir: Path,
    config,
    repo_map: str,
) -> None:
    """Write CLAUDE.md that Claude Code auto-loads for every agent.

    This gives agents project context without prompt injection —
    Claude Code reads CLAUDE.md automatically before any action.
    """
    team_lines = "\n".join(
        f"- {p.name} ({p.type}): {p.specialization or 'general'}"
        for p in config.team
    )

    content = f"""# AgentOS Workspace

## Goal
{config.goal.strip()[:400]}

## Team
{team_lines}

## Repository
{repo_map}

## Communication Protocol
- Call read_board at the START and every few steps
- Call check_messages FREQUENTLY — respond to human messages immediately
- Post findings to the board as you discover them
- Use send_message to reply to direct messages
- Do NOT explore the entire codebase — the map above shows what exists
- Only read files when you need specific implementation details
"""
    (workspace_dir / "CLAUDE.md").write_text(content)
