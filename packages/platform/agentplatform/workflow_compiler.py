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


def _validate_output_contract(
    result: str | None, output_schema: dict | None
) -> tuple[bool, str]:
    """Validate agent output against a JSON Schema contract.

    Returns (is_valid, error_message).
    Skips if output_schema is None or result is not JSON.
    """
    if output_schema is None or result is None:
        return True, ""

    # Try to parse result as JSON
    import json as _json

    try:
        data = _json.loads(result)
    except (ValueError, TypeError):
        # Not JSON — skip validation (most agent outputs are plain text)
        return True, ""

    # Try jsonschema first, fall back to basic structural check
    try:
        import jsonschema
        jsonschema.validate(instance=data, schema=output_schema)
        return True, ""
    except ImportError:
        # Basic fallback: check type and required keys
        expected_type = output_schema.get("type")
        if expected_type == "object" and not isinstance(data, dict):
            return False, f"Expected JSON object, got {type(data).__name__}"
        if expected_type == "array" and not isinstance(data, list):
            return False, f"Expected JSON array, got {type(data).__name__}"
        if expected_type == "object" and isinstance(data, dict):
            required = output_schema.get("required", [])
            missing = [k for k in required if k not in data]
            if missing:
                return False, f"Missing required keys: {missing}"
        return True, ""
    except jsonschema.ValidationError as e:
        return False, str(e.message)


def compile_workflow(
    workflow: WorkflowDefinition,
    *,
    domain_registry: DomainRegistry,
    event_log: EventLog,
    workspace: Workspace,
    provider_factory: Callable[[str], BaseLMProvider],
    run_id: RunId | None = None,
    stop_event: threading.Event | None = None,
    task_description: str = "",
    variable_values: dict[str, str] | None = None,
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

    # Build workflow-level context from variables and task_description
    workflow_context = _build_workflow_context(workflow, task_description, variable_values)

    # Build node lookup and tool registry per node
    node_map: dict[str, TaskNode] = {}
    # Map workflow node IDs → display names for context in output chaining
    node_names: dict[str, str] = {n.id: n.display_name for n in workflow.nodes}

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

        # Resolve dependency TaskNodes
        dep_tasks = [
            node_map[dep_id]
            for dep_id in deps[wf_node.id]
            if dep_id in node_map
        ]

        # Build the static portion of the task description
        static_desc = (
            f"You are the '{wf_node.display_name}' agent in a multi-agent workflow.\n\n"
            f"{workflow_context}\n\n"
            "IMPORTANT: Do NOT ask for clarification or additional information. "
            "Work with whatever context you have and produce your best output. "
            "Other agents downstream depend on your output."
        )

        # Collect output schemas from outgoing edges for this node
        node_output_schemas: list[dict] = []
        for edge in workflow.edges:
            if edge.source == wf_node.id:
                dc = edge.data_contract
                if dc and dc.output_schema:
                    node_output_schemas.append(dc.output_schema)

        # Capture in closure — dep_tasks gives runtime access to predecessor results
        _runner = runner
        _config = agent_config
        _static_desc = static_desc
        _dep_tasks = list(dep_tasks)  # snapshot
        _dep_names = {id(node_map[did]): node_names[did] for did in deps[wf_node.id] if did in node_map}
        _output_schemas = list(node_output_schemas)

        def make_callable(
            r: AgentRunner = _runner,
            c: AgentConfig = _config,
            sd: str = _static_desc,
            dt: list[TaskNode] = _dep_tasks,
            dn: dict[int, str] = _dep_names,
            schemas: list[dict] = _output_schemas,
        ) -> Callable[[], Any]:
            def run_agent() -> str | None:
                # Build full task description at runtime, including predecessor outputs
                parts = [sd]
                if dt:
                    parts.append(
                        "IMPORTANT: The output from the previous agent(s) is provided below. "
                        "Use this content directly as your input — do NOT ask for more "
                        "information or clarification. Work with what you have been given."
                    )
                    for dep in dt:
                        if dep.result:
                            dep_name = dn.get(id(dep), dep.name)
                            parts.append(
                                f"=== Output from '{dep_name}' ===\n"
                                f"{dep.result}\n"
                                f"=== End of '{dep_name}' output ==="
                            )
                full_desc = "\n\n".join(parts)

                max_retries = 2
                for attempt in range(max_retries + 1):
                    agent_run_id = generate_run_id()
                    task_desc = full_desc
                    if attempt > 0:
                        # Add feedback about schema violation
                        task_desc += f"\n\n{_contract_feedback}"
                    _, result = r.run(task_desc, run_id=agent_run_id, config=c)

                    # Validate against output schemas
                    if schemas:
                        all_valid = True
                        _contract_feedback_parts = []
                        for schema in schemas:
                            valid, err = _validate_output_contract(result, schema)
                            if not valid:
                                all_valid = False
                                _contract_feedback_parts.append(
                                    f"[CONTRACT VIOLATION] Your output did not match "
                                    f"the required schema: {err}\n"
                                    f"Expected schema: {schema}\n"
                                    f"Please fix your output to match the contract."
                                )
                        if not all_valid and attempt < max_retries:
                            _contract_feedback = "\n\n".join(_contract_feedback_parts)
                            logger.warning(
                                "Contract validation failed for node (attempt %d/%d): %s",
                                attempt + 1, max_retries + 1,
                                _contract_feedback_parts,
                            )
                            continue
                    # If valid or no schemas or out of retries, return result
                    return result
                return result
            return run_agent

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


def _build_workflow_context(
    workflow: WorkflowDefinition,
    task_description: str,
    variable_values: dict[str, str] | None = None,
) -> str:
    """Build workflow-level context string from variables and task description."""
    parts: list[str] = []
    vals = variable_values or {}

    if task_description:
        parts.append(f"Task: {task_description}")

    # Include workflow variables — user-provided values override defaults
    var_lines = []
    for var in workflow.variables:
        value = vals.get(var.name, var.default)
        if value:
            var_lines.append(f"- {var.name}: {value}")
    if var_lines:
        parts.append("Workflow parameters:\n" + "\n".join(var_lines))

    return "\n\n".join(parts)


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
