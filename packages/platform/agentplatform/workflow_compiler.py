"""Workflow compiler — converts WorkflowDefinition into an executable DAG."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from agentos.core.identifiers import RunId, generate_run_id
from agentos.governance.budget_manager import BudgetManager
from agentos.lm.agent_config import AgentConfig
from agentos.lm.agent_runner import AgentRunner
from agentos.lm.provider import BaseLMProvider
from agentos.runtime.dag import DAGWorkflow
from agentos.runtime.domain_registry import DomainRegistry
from agentos.runtime.event_log import EventLog
from agentos.runtime.task import TaskNode
from agentos.runtime.workspace import Workspace
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.workflow import WorkflowDefinition
from agentos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Default budget for nodes that don't specify one
_DEFAULT_BUDGET = BudgetSpec(
    max_tokens=100_000,
    max_tool_calls=50,
    max_time_seconds=300.0,
    max_recursion_depth=1,
)

_PERSONA_PROMPTS: dict[str, str] = {
    "analytical": "Be precise, data-driven, and methodical in your approach.",
    "creative": "Be creative, explore unconventional ideas, and think laterally.",
    "formal": "Use formal language, structured output, and professional tone.",
    "concise": "Be brief and direct. Minimize unnecessary explanation.",
    "friendly": "Be conversational, approachable, and explain things clearly.",
}


def compile_workflow(
    workflow: WorkflowDefinition,
    *,
    domain_registry: DomainRegistry,
    event_log: EventLog,
    workspace: Workspace,
    provider_factory: Callable[[str], BaseLMProvider],
    run_id: RunId | None = None,
    stop_event: threading.Event | None = None,
) -> DAGWorkflow:
    """Compile a visual workflow definition into an executable DAG.

    For each node in the workflow:
    1. Resolve model → provider via factory
    2. Resolve tools from domain registry
    3. Build AgentRunner with budget manager
    4. Create TaskNode with proper dependencies from edges

    Returns a DAGWorkflow ready for ``DAGExecutor.run()``.
    """
    rid = run_id or generate_run_id()

    # Build node lookup and tool registry per node
    node_map: dict[str, TaskNode] = {}

    # Resolve dependencies: target → [source node IDs]
    deps: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
    for edge in workflow.edges:
        if edge.target in deps:
            deps[edge.target].append(edge.source)

    # Create TaskNodes in dependency order (sources first)
    for wf_node in workflow.nodes:
        # Resolve the LM provider
        provider = provider_factory(wf_node.config.model)

        # Build tool registry for this node
        tool_registry = ToolRegistry()
        if workflow.domain_pack and domain_registry.has_pack(workflow.domain_pack):
            pack = domain_registry.get_pack(workflow.domain_pack)
            tool_entries = {t.name: t for t in pack.tools}
            for tool_name in wf_node.config.tools:
                if tool_name in tool_entries:
                    try:
                        tool = domain_registry.load_tool(
                            tool_entries[tool_name],
                            workspace=workspace,
                        )
                        tool_registry.register(tool)
                    except Exception as exc:
                        logger.warning(
                            "Failed to load tool '%s' for node '%s': %s",
                            tool_name, wf_node.display_name, exc,
                        )

        # Build system prompt
        system_prompt = _build_system_prompt(wf_node.config.system_prompt, wf_node.config.persona_preset)

        # Build agent config
        agent_config = AgentConfig(
            system_prompt=system_prompt,
            max_steps=wf_node.config.max_steps,
        )

        # Budget
        budget_spec = wf_node.config.budget or _DEFAULT_BUDGET
        budget_manager = BudgetManager(budget_spec, event_log, rid)

        # Create AgentRunner
        runner = AgentRunner(
            event_log=event_log,
            lm_provider=provider,
            tool_registry=tool_registry,
            budget_manager=budget_manager,
        )

        # Build the task description from the workflow context
        task_description = (
            f"You are the '{wf_node.display_name}' agent in a multi-agent workflow. "
            f"Your role: {wf_node.role}."
        )

        # Capture in closure for the callable
        _runner = runner
        _config = agent_config
        _rid = rid
        _desc = task_description

        def make_callable(
            r: AgentRunner = _runner,
            c: AgentConfig = _config,
            run: RunId = _rid,
            d: str = _desc,
        ) -> Callable[[], Any]:
            def run_agent() -> str | None:
                _, result = r.run(d, run_id=run, config=c)
                return result
            return run_agent

        # Resolve dependency TaskNodes
        dep_tasks = [
            node_map[dep_id]
            for dep_id in deps[wf_node.id]
            if dep_id in node_map
        ]

        task_node = TaskNode(
            name=wf_node.display_name,
            callable=make_callable(),
            depends_on=dep_tasks,
        )
        node_map[wf_node.id] = task_node

    dag = DAGWorkflow(
        name=workflow.name,
        tasks=list(node_map.values()),
    )
    return dag


def _build_system_prompt(user_prompt: str, persona_preset: str) -> str:
    """Combine user system prompt with persona preset and agent action format."""
    parts: list[str] = []

    # Agent action JSON protocol
    parts.append(
        "You are an AI agent with access to tools. "
        "Respond with a JSON object containing your action.\n"
        'For tool calls: '
        '{"action": "tool_call", "tool": "<name>", "input": {...}, "reasoning": "..."}\n'
        'When done: '
        '{"action": "finish", "result": "...", "reasoning": "..."}'
    )

    # Persona
    persona_text = _PERSONA_PROMPTS.get(persona_preset, "")
    if persona_text:
        parts.append(persona_text)

    # User-provided system prompt
    if user_prompt:
        parts.append(user_prompt)

    return "\n\n".join(parts)
