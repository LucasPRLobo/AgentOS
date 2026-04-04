# Codebase Indexing — Step-by-Step Implementation

---

## Overview

112 Python files, 24K lines. 80 frontend files. Agents currently re-read
the same files independently, wasting 50-70K tokens per run.

The fix: generate a **repo map** once, give it to every agent, and teach
agents to query files on-demand instead of exploring blindly.

---

## Step 1: Repo Map Generator

**New file:** `agentos/workspace/repo_map.py` (~200 lines)

### What it produces

A markdown file (~1500 tokens) with:
- Directory tree (1 line per directory, with purpose comment)
- Top 30 most-imported files with class/function signatures
- API surface summary (dashboard endpoints)

### How it works

```python
class RepoMapGenerator:
    def __init__(self, project_dir: Path, token_budget: int = 1500):
        self._dir = project_dir
        self._budget = token_budget
        self._cache_path = project_dir / ".agentos" / "repo-map.md"

    def generate(self) -> str:
        """Generate or return cached repo map."""
        if self._cache_path.exists() and not self._is_stale():
            return self._cache_path.read_text()
        map_text = self._build()
        self._cache_path.parent.mkdir(exist_ok=True)
        self._cache_path.write_text(map_text)
        return map_text
```

### Internal methods

**`_scan_python_files()`** — walk `agentos/` and collect all `.py` files:
```python
def _scan_python_files(self) -> dict[str, Path]:
    """Return {module_path: filepath} for all Python files."""
    result = {}
    for f in self._dir.rglob("*.py"):
        if any(skip in str(f) for skip in ("__pycache__", ".egg", "node_modules")):
            continue
        rel = f.relative_to(self._dir)
        result[str(rel)] = f
    return result
```

**`_extract_signatures(filepath)`** — use `ast.parse` to get class/function names:
```python
def _extract_signatures(self, filepath: Path) -> list[dict]:
    """Extract class and function signatures using ast."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return []

    sigs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not n.name.startswith("_")
            ]
            sigs.append({
                "type": "class", "name": node.name,
                "methods": methods[:8],  # Cap to avoid bloat
                "line": node.lineno,
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only top-level functions (not methods)
            if isinstance(node, ast.FunctionDef) and not hasattr(node, '_parent_class'):
                if not node.name.startswith("_"):
                    args = [a.arg for a in node.args.args if a.arg != "self"][:4]
                    sigs.append({
                        "type": "function", "name": node.name,
                        "args": args, "line": node.lineno,
                    })
    return sigs
```

**`_rank_by_imports(files)`** — count how often each module is imported:
```python
def _rank_by_imports(self, files: dict) -> list[str]:
    """Rank files by import frequency (most-imported first)."""
    import_count: dict[str, int] = defaultdict(int)
    for filepath in files.values():
        try:
            tree = ast.parse(filepath.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Normalize: "agentos.workspace.schemas" → "agentos/workspace/schemas.py"
                mod_path = node.module.replace(".", "/") + ".py"
                import_count[mod_path] += 1
    return sorted(import_count.keys(), key=lambda k: import_count[k], reverse=True)
```

**`_scan_frontend()`** — extract React component names from `.tsx` files:
```python
def _scan_frontend(self) -> list[dict]:
    """Extract component names from TSX files via regex."""
    import re
    components = []
    frontend_dir = self._dir / "agentos" / "dashboard" / "frontend" / "src"
    if not frontend_dir.exists():
        return []
    for f in frontend_dir.rglob("*.tsx"):
        content = f.read_text()
        # Match: export function ComponentName or export default function
        for m in re.finditer(r"export\s+(?:default\s+)?function\s+(\w+)", content):
            components.append({
                "name": m.group(1),
                "file": str(f.relative_to(self._dir)),
            })
    return components
```

**`_build()`** — assemble the map within token budget:
```python
def _build(self) -> str:
    """Build the repo map markdown."""
    files = self._scan_python_files()
    ranked = self._rank_by_imports(files)
    frontend = self._scan_frontend()

    lines = ["# Repository Map", ""]

    # Directory structure (compact)
    lines.append("## Structure")
    lines.append("```")
    lines.extend(self._build_tree())
    lines.append("```")
    lines.append("")

    # Key Python files with signatures
    lines.append("## Key Modules")
    chars_used = sum(len(l) for l in lines)
    budget_chars = self._budget * 4  # ~4 chars per token

    for mod_path in ranked[:30]:
        filepath = files.get(mod_path)
        if not filepath or not filepath.exists():
            continue
        sigs = self._extract_signatures(filepath)
        if not sigs:
            continue

        section = [f"\n### {mod_path}"]
        for sig in sigs[:5]:
            if sig["type"] == "class":
                section.append(f"  class {sig['name']}")
                for m in sig["methods"][:5]:
                    section.append(f"    def {m}()")
            else:
                args = ", ".join(sig.get("args", []))
                section.append(f"  def {sig['name']}({args})")

        section_text = "\n".join(section)
        if chars_used + len(section_text) > budget_chars:
            break
        lines.extend(section)
        chars_used += len(section_text)

    # Frontend components (compact list)
    if frontend:
        lines.append("\n## Frontend Components")
        for comp in frontend[:15]:
            lines.append(f"  {comp['name']} — {comp['file']}")

    return "\n".join(lines) + "\n"
```

**`_build_tree()`** — compact directory tree:
```python
def _build_tree(self) -> list[str]:
    """Build a compact directory tree with purpose comments."""
    tree_map = {
        "agentos/kernel/": "Core: event log, state machine, DAG, budget",
        "agentos/adapters/": "Agent adapters (Tier 1/2/3)",
        "agentos/comms/": "Board, messaging, MCP server, discussions",
        "agentos/workspace/": "Runtime, supervisor, backlog, coordinator",
        "agentos/dashboard/": "FastAPI backend + React frontend",
        "agentos/schemas/": "Pydantic v2 models",
        "agentos/security/": "Capabilities, secrets, enforcer",
        "agentos/cli/": "Click CLI commands",
        "agentos/intelligence/": "Knowledge graph, specialization",
        "agentos/validation/": "Workflow verification",
        "tests/": "Unit, integration, e2e tests",
        "examples/": "Demo scripts + YAML configs",
        "docs/": "Design documents + plans",
    }
    return [f"{path:30s} # {desc}" for path, desc in tree_map.items()]
```

**`_is_stale()`** — check if cache needs refresh:
```python
def _is_stale(self) -> bool:
    """True if any .py file is newer than the cached map."""
    if not self._cache_path.exists():
        return True
    cache_mtime = self._cache_path.stat().st_mtime
    for f in self._dir.rglob("*.py"):
        if f.stat().st_mtime > cache_mtime:
            return True
    return False
```

### Tests: `tests/unit/test_repo_map.py`

- Generate map for AgentOS codebase
- Map contains key classes (WorkspaceRuntime, BacklogManager, BoardManager)
- Map is within token budget
- Cache works (second call returns cached)
- Stale detection works
- Handles syntax errors in files gracefully
- Frontend components extracted

**~100 lines tests**

---

## Step 2: Inject Repo Map into Supervisor

**Modify:** `agentos/workspace/supervisor.py`

### Add repo map loading to `__init__`:

```python
# In __init__, after self._agents setup:
self._repo_map: str = ""
if runtime._project_dir:
    from agentos.workspace.repo_map import RepoMapGenerator
    gen = RepoMapGenerator(runtime._project_dir)
    self._repo_map = gen.generate()
    logger.info("Repo map: %d chars", len(self._repo_map))
```

### Inject into first-turn agent prompt:

```python
# In _spawn_agent, replace the first-turn prompt:
if not agent.session_started:
    prompt = (
        f"You are {agent_id}, a team member in an AgentOS workspace.\n"
        f"You are part of a team working on: {self._rt.config.goal.strip()[:200]}\n\n"
        f"## Codebase Overview\n"
        f"The repository map below shows the project structure and key APIs.\n"
        f"Use this to know WHERE things are. Only read files you need.\n"
        f"Do NOT explore the codebase blindly — the map tells you what exists.\n\n"
        f"{self._repo_map}\n\n"
        f"## Team Communication\n"
        ...
    )
```

### Inject into coordinator prompt:

Also pass the repo map to the coordinator so it doesn't need to
read the entire codebase for decomposition:

```python
# In coordinator_runner.py, run_decomposition():
# Add repo_map parameter, inject into the coordinator prompt
prompt = f"""...
## Codebase Structure
{repo_map}

Based on this structure, decompose the goal into tasks...
"""
```

**~40 lines changes across supervisor.py and coordinator_runner.py**

---

## Step 3: Workspace CLAUDE.md

**New function in:** `agentos/workspace/repo_map.py`

Write a `CLAUDE.md` into the workspace directory. Claude Code auto-loads
this before any agent action — free context injection.

```python
def write_workspace_claude_md(
    workspace_dir: Path,
    config,   # WorkspaceConfig
    repo_map: str,
) -> None:
    """Write CLAUDE.md that Claude Code auto-loads for every agent."""
    team = "\n".join(
        f"- {p.name} ({p.type}): {p.specialization}"
        for p in config.team
    )
    content = f"""# AgentOS Workspace

## Goal
{config.goal.strip()[:300]}

## Team
{team}

## Repository
{repo_map}

## Communication Protocol
- Call read_board at the START and every few steps
- Call check_messages FREQUENTLY — respond to human messages immediately
- Post findings to the board as you discover them
- Use send_message to reply to direct messages
- Do NOT explore the entire codebase — the map above shows what exists
"""
    (workspace_dir / "CLAUDE.md").write_text(content)
```

Called once at workspace start, before any agents launch.

**~30 lines**

---

## Step 4: Smart Prompting (reduce exploration)

**Modify:** Agent prompt in `supervisor.py`

The key behavioral change: agents should **look up, not explore**.

Current behavior:
```
Agent launches → reads 30 files to understand the codebase → does task
```

New behavior:
```
Agent launches → reads repo map (already in prompt) → reads 3-5 specific files → does task
```

Change the agent prompt from:
```
You are {agent_id}. Your task: ...
```

To:
```
You are {agent_id}. Your task: ...

EFFICIENCY RULES:
- The Codebase Overview above already shows the project structure
- Do NOT read files to "understand the project" — the map covers that
- Only Read files when you need specific implementation details
- Prefer Grep to find specific code over reading whole files
- Keep file reads under 10 for this task
```

**~10 lines**

---

## Step 5: Coordinator Repo Map

**Modify:** `agentos/workspace/coordinator_runner.py`

The coordinator currently reads 15-20 files during decomposition. With
the repo map, it only needs the map + task context.

Pass `repo_map` to `run_decomposition()` and inject into the prompt:

```python
def run_decomposition(
    config, workspace, board, bus, backlog, workflow_id,
    project_dir=None, status_fn=None, repo_map: str = "",
) -> list[BacklogTask]:
    # ... existing code ...

    prompt = f"""You are the project coordinator...

## Codebase Structure
{repo_map}

Based on this structure, decompose the goal into tasks.
You already have the full project map — do NOT read files
to understand the codebase. Focus on creating the task plan.
"""
```

This should reduce coordinator decomposition from ~50K tokens
to ~10K tokens (map is ~1.5K + task planning output).

**~20 lines changes**

---

## Step 6: Cache Management

**In:** `agentos/workspace/repo_map.py`

The repo map should be:
- Generated once at workspace start
- Cached to `.agentos/repo-map.md`
- Regenerated only if Python files changed (mtime check)
- Shared across ALL agents (same string injected into every prompt)

The `_is_stale()` method handles this. The supervisor calls
`generate()` once in `__init__` and stores the result.

**Already covered in Step 1.**

---

## Summary

| Step | File | Lines | What |
|---|---|---|---|
| 1 | `workspace/repo_map.py` (new) | ~200 | Generator: ast extraction, import ranking, tree, cache |
| 2 | `workspace/supervisor.py` | ~40 | Inject map into agent + coordinator prompts |
| 3 | `workspace/repo_map.py` | ~30 | Write CLAUDE.md to workspace dir |
| 4 | `workspace/supervisor.py` | ~10 | Efficiency rules in agent prompt |
| 5 | `workspace/coordinator_runner.py` | ~20 | Pass map to coordinator, skip file reads |
| 6 | (covered in step 1) | — | Cache with mtime staleness check |
| Tests | `tests/unit/test_repo_map.py` | ~100 | Generation, caching, budget, error handling |
| **Total** | | **~400** | |

### Dependency Order

```
Step 1 (generator) ──→ Step 2 (inject into supervisor)
                   ──→ Step 3 (workspace CLAUDE.md)
                   ──→ Step 5 (coordinator map)
Step 4 (prompting) ──→ independent, do anytime
Tests ─────────────→ after Step 1
```

Steps 2, 3, 4, 5 are all independent once Step 1 exists.

### Expected Token Savings

| Component | Before | After | Savings |
|---|---|---|---|
| Agent file reads (per agent) | ~24K tokens | ~5K tokens | 79% |
| Agent file reads (3 agents) | ~72K tokens | ~15K tokens | 79% |
| Coordinator decomposition | ~50K tokens | ~10K tokens | 80% |
| Coordinator responses | ~5K tokens | ~3K tokens | 40% |
| DM responses | ~10K tokens | ~5K tokens | 50% |
| **Total per workspace run** | **~140K** | **~35K** | **75%** |
