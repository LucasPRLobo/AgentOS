"""Single source of truth for YAML-to-CLI tool name mapping."""

from __future__ import annotations

# Mapping from YAML tool names to Claude Code CLI tool names for Tier 2 adapters.
TIER2_TOOL_MAP: dict[str, str] = {
    "file_read": "Read",
    "file_write": "Write",
    "shell_exec": "Bash",
    "web_search": "WebSearch",
    "web_fetch": "WebFetch",
}

# Claude Code built-in tools that should always be available to agents that need
# file or web access. When a YAML workflow specifies tools like [web_search, file_read],
# we expand them to include the related CC tools the agent will need.
TIER2_TOOL_EXPANSIONS: dict[str, list[str]] = {
    "Read": ["Read", "Glob", "Grep"],
    "Write": ["Write", "Edit"],
    "Bash": ["Bash"],
    "WebSearch": ["WebSearch", "WebFetch"],
    "WebFetch": ["WebFetch"],
}

# All valid YAML tool names that can appear in workflow definitions.
VALID_TOOLS: set[str] = set(TIER2_TOOL_MAP.keys())
