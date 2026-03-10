"""Natural language workflow generation using Claude API."""

from __future__ import annotations

import logging

import yaml

logger = logging.getLogger(__name__)

from agentos.schemas.tool_mapping import VALID_TOOLS

# Every agent needs these to produce manifest.json and read predecessor context
REQUIRED_TOOLS = {"file_read", "file_write"}

SYSTEM_PROMPT = """\
You are an AgentOS workflow generator. Given a natural language description,
produce a valid AgentOS workflow YAML file.

IMPORTANT RULES — you MUST follow these exactly:

1. All agents MUST use adapter: tier2_claude_code. No exceptions.
2. All agents MUST have file_read and file_write in their tools list
   (they need these to produce mandatory manifest.json output).
3. Only use these tool names: file_read, file_write, web_search, shell_exec
4. Gate task types MUST be "approval_gate" or "input_gate" (not "approval" or "gate")
5. Gate tasks do NOT have an "agent" field.
6. Every agent MUST have a budget with max_tokens and max_cost_usd.
7. All agent tasks must have a workspace field set to "shared".

The YAML schema:
- name: string (kebab-case)
- version: "1.0"
- agents: mapping of agent_id -> {name, adapter, role, tools[], budget{max_tokens, max_cost_usd}}
- tasks: mapping of task_id -> {name, description, agent, depends_on[], type, workspace}

Task types:
- agent_task (default, omit type field): regular agent task
- approval_gate: human approval checkpoint (no agent field)
- input_gate: human input checkpoint (no agent field)

Example:
```yaml
name: research-pipeline
version: "1.0"
agents:
  researcher:
    name: Researcher
    adapter: tier2_claude_code
    role: Research the topic using web and file analysis
    tools: [web_search, file_read, file_write]
    budget: {max_tokens: 100000, max_cost_usd: 2.0}
  analyst:
    name: Analyst
    adapter: tier2_claude_code
    role: Analyze findings and write a report
    tools: [file_read, file_write]
    budget: {max_tokens: 80000, max_cost_usd: 1.5}
tasks:
  research:
    name: Research
    description: Research the topic thoroughly
    agent: researcher
    workspace: shared
  review_gate:
    name: Review Approval
    type: approval_gate
    depends_on: [research]
  analysis:
    name: Analysis
    description: Analyze findings and produce final report
    agent: analyst
    depends_on: [review_gate]
    workspace: shared
```

Return ONLY the YAML content, no markdown fences, no explanation."""


def _postfix_workflow(yaml_str: str) -> str:
    """Programmatically fix common LLM generation errors.

    Parses the YAML, enforces invariants, and re-serializes.
    Returns the corrected YAML string.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        return yaml_str  # Can't fix unparseable YAML

    if not isinstance(data, dict):
        return yaml_str

    # Ensure top-level keys
    data.setdefault("name", "generated-workflow")
    data.setdefault("version", "1.0")

    # Fix agents
    agents = data.get("agents", {})
    if isinstance(agents, dict):
        for agent_id, agent_cfg in agents.items():
            if not isinstance(agent_cfg, dict):
                continue

            # Force tier2_claude_code adapter
            agent_cfg["adapter"] = "tier2_claude_code"

            # Remove model field (not used by tier2)
            agent_cfg.pop("model", None)

            # Ensure tools is a list and includes required tools
            tools = agent_cfg.get("tools", [])
            if not isinstance(tools, list):
                tools = []
            tool_set = set(tools)
            tool_set |= REQUIRED_TOOLS
            # Remove any invalid tool names
            tool_set &= VALID_TOOLS | REQUIRED_TOOLS
            agent_cfg["tools"] = sorted(tool_set)

            # Ensure budget exists with defaults
            budget = agent_cfg.get("budget", {})
            if not isinstance(budget, dict):
                budget = {}
            budget.setdefault("max_tokens", 100000)
            budget.setdefault("max_cost_usd", 2.0)
            agent_cfg["budget"] = budget

    # Fix tasks
    tasks = data.get("tasks", {})
    if isinstance(tasks, dict):
        for task_id, task_cfg in tasks.items():
            if not isinstance(task_cfg, dict):
                continue

            # Fix gate type names
            task_type = task_cfg.get("type", "")
            if task_type in ("approval", "gate", "approval-gate"):
                task_cfg["type"] = "approval_gate"
            elif task_type in ("input", "input-gate"):
                task_cfg["type"] = "input_gate"

            # Gate tasks should not have an agent
            if task_cfg.get("type") in ("approval_gate", "input_gate"):
                task_cfg.pop("agent", None)
                task_cfg.pop("workspace", None)
            else:
                # Agent tasks need a workspace
                task_cfg.setdefault("workspace", "shared")

                # Verify agent exists
                agent_ref = task_cfg.get("agent", "")
                if agent_ref and agent_ref not in agents:
                    # Try to find closest match
                    for aid in agents:
                        if aid in agent_ref or agent_ref in aid:
                            task_cfg["agent"] = aid
                            break

            # Ensure depends_on is a list
            deps = task_cfg.get("depends_on", [])
            if not isinstance(deps, list):
                task_cfg["depends_on"] = []

    data["agents"] = agents
    data["tasks"] = tasks

    return yaml.dump(data, sort_keys=False, default_flow_style=False, width=120)


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # Remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing fence
        text = "\n".join(lines)
    return text.strip()


def _generate_via_cli(prompt: str) -> str:
    """Generate using Claude Code CLI (uses plan credits, not API key)."""
    import json
    import os
    import subprocess

    full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\nUser request: {prompt}"

    # Whitelist: only pass safe env vars + ANTHROPIC_API_KEY to subprocess
    _nl_env_whitelist = {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
        "TERM", "TMPDIR", "TMP", "TEMP", "XDG_RUNTIME_DIR", "XDG_DATA_HOME",
        "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
        "ANTHROPIC_API_KEY",
        "NODE_PATH", "NODE_OPTIONS", "npm_config_prefix",
    }
    env = {k: v for k, v in os.environ.items() if k in _nl_env_whitelist}
    env.pop("CLAUDECODE", None)  # Anti-nesting guard

    cmd = [
        "claude",
        "--print",
        "--output-format", "json",
        "--max-turns", "1",
        "-p", full_prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Claude Code CLI not found. Install it or set AGENTOS_NL_USE_API=1 "
            "to fall back to the Anthropic API."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude Code CLI timed out after 120s")

    if result.returncode != 0:
        raise RuntimeError(f"Claude Code CLI exited with code {result.returncode}")

    # Parse JSON output to extract the text
    try:
        output = json.loads(result.stdout)
        # Real CLI: result text is in "result" field
        text = output.get("result", "")
        if not text:
            # Fallback: try content blocks
            for block in output.get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    break
        if not text:
            text = result.stdout
    except json.JSONDecodeError:
        text = result.stdout

    return text


def _generate_via_api(prompt: str) -> str:
    """Generate using the Anthropic API directly (costs API credits)."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package required for API-based NL generation. "
            "Install with: pip install anthropic"
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )
    return response.content[0].text


def generate_workflow_yaml(description: str) -> str:
    """Generate workflow YAML from a natural language description.

    By default uses Claude Code CLI (plan credits, no API cost).
    Set AGENTOS_NL_USE_API=1 to use the Anthropic API instead.

    Args:
        description: Natural language description of the desired workflow.

    Returns:
        Generated and post-fixed YAML string.

    Raises:
        RuntimeError: If generation fails.
    """
    import os

    use_api = os.environ.get("AGENTOS_NL_USE_API", "").strip() in ("1", "true", "yes")

    try:
        if use_api:
            text = _generate_via_api(description)
        else:
            text = _generate_via_cli(description)

        text = _strip_fences(text)
        text = _postfix_workflow(text)

        return text.strip()
    except Exception as e:
        logger.error("NL generation failed: %s", e)
        raise RuntimeError(f"Workflow generation failed: {e}") from e
