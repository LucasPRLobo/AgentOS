# Adapter Development Guide

This guide covers how AgentOS agent adapters work and how to build custom adapters.

## Overview

An adapter is the bridge between AgentOS and an AI agent. It translates AgentOS task assignments into agent-understandable instructions and returns structured output.

AgentOS uses a tiered adapter system:

| Tier | Control | AgentOS Role | Example |
|------|---------|--------------|---------|
| 1 | Full | Controls tool-calling loop | Anthropic/OpenAI API |
| 2 | Semi | Monitors from outside | Claude Code CLI |
| 3 | Best-effort | Minimal control | Other CLI tools |

## The AgentAdapter Interface

All adapters implement the abstract base class in `agentos/adapters/base.py`:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from agentos.schemas.task import TaskOutput

class AgentAdapter(ABC):

    @property
    @abstractmethod
    def tier(self) -> int:
        """Adapter tier (1, 2, or 3)."""

    @abstractmethod
    async def execute_task(
        self,
        task_description: str,
        role: str,
        workspace: Path,
        predecessor_context: list[TaskOutput],
        allowed_tools: list[str],
    ) -> TaskOutput:
        """Execute a task and return structured output."""

    @abstractmethod
    async def terminate(self) -> None:
        """Stop the agent cleanly."""
```

### Parameters

| Parameter | Description |
|-----------|-------------|
| `task_description` | What the agent should do |
| `role` | System prompt / persona |
| `workspace` | Scoped directory for file I/O |
| `predecessor_context` | Structured outputs from upstream tasks |
| `allowed_tools` | Tool allowlist for this execution |

### Return Value

Every adapter returns a `TaskOutput`:

```python
class TaskOutput(BaseModel):
    schema_version: str = "0.1"
    task_id: str
    agent_id: str
    status: TaskStatus       # succeeded | failed
    summary: str             # 1-3 sentence summary
    key_findings: list[Finding]
    files_produced: list[FileReference]
    open_questions: list[str]
    metrics: TaskMetrics | None
```

## Tier 1 Adapter (API-Controlled)

Tier 1 provides full control: AgentOS manages the tool-calling loop, enforces capabilities at each tool call, and extracts structured output via JSON mode.

### How It Works

1. AgentOS sends the task prompt + role to the LLM API
2. The LLM responds with tool calls
3. AgentOS intercepts each tool call through `CapabilityEnforcer`
4. AgentOS executes allowed tool calls and returns results
5. Loop continues until the LLM produces final output
6. Output is parsed as `TaskOutput` via JSON mode

### Implementation: `agentos/adapters/tier1.py`

```python
class Tier1Adapter(AgentAdapter):
    def __init__(self, client, model, budget_manager, agent_id):
        self._client = client          # Anthropic/OpenAI client
        self._model = model
        self._budget_manager = budget_manager
        self._agent_id = agent_id

    @property
    def tier(self) -> int:
        return 1

    async def execute_task(self, task_description, role, workspace,
                           predecessor_context, allowed_tools) -> TaskOutput:
        # Build messages with task context
        # Call LLM API in a tool-calling loop
        # Track budget via budget_manager.apply()
        # Return structured TaskOutput
        ...
```

### Security

Tier 1 has the strongest security guarantees:
- **Tool allowlist**: Only listed tools can be called
- **Path scoping**: File operations restricted to allowed paths
- **Domain whitelisting**: Network requests restricted to allowed domains
- **Path traversal protection**: `../` patterns always blocked

All checks happen via `CapabilityEnforcer.check_tool_call()` before execution.

## Tier 2 Adapter (Claude Code CLI)

Tier 2 monitors an external process. AgentOS can't intercept individual tool calls, but it can:

- Scope the workspace directory
- Set budget limits
- Validate output post-hoc
- Track resource consumption

### How It Works

1. AgentOS prepares a task prompt with structured output instructions
2. Launches Claude Code as a subprocess with the workspace as CWD
3. Claude Code executes autonomously
4. AgentOS reads `manifest.json` from the workspace
5. Validates and parses as `TaskOutput`
6. Tracks resource usage from Claude Code's usage output

### Implementation: `agentos/adapters/tier2_claude_code.py`

```python
class ClaudeCodeAdapter(AgentAdapter):
    def __init__(self, budget_manager, agent_id, run_subprocess=None):
        self._budget_manager = budget_manager
        self._agent_id = agent_id
        self._run_subprocess = run_subprocess or subprocess.run

    @property
    def tier(self) -> int:
        return 2

    async def execute_task(self, task_description, role, workspace,
                           predecessor_context, allowed_tools) -> TaskOutput:
        # Build prompt with manifest.json instructions
        # Launch claude CLI subprocess
        # Parse manifest.json from workspace
        # Track budget from usage output
        # Return TaskOutput
        ...
```

### Structured Output Protocol

Tier 2 agents are instructed to write a `manifest.json` file:

```json
{
  "summary": "Completed the analysis",
  "findings": [
    {"finding": "Revenue grew 15%", "confidence": "high"}
  ],
  "files_produced": [
    {"path": "report.md", "description": "Final report"}
  ],
  "open_questions": ["Need clarification on Q3 data"]
}
```

AgentOS validates this post-hoc. If the manifest is missing or malformed, the task fails.

## Building a Custom Adapter

### Step 1: Implement the Interface

```python
from agentos.adapters.base import AgentAdapter
from agentos.schemas.task import TaskOutput, TaskStatus

class MyCustomAdapter(AgentAdapter):

    def __init__(self, budget_manager, agent_id):
        self._budget_manager = budget_manager
        self._agent_id = agent_id

    @property
    def tier(self) -> int:
        return 3  # Best-effort for custom adapters

    async def execute_task(self, task_description, role, workspace,
                           predecessor_context, allowed_tools) -> TaskOutput:
        # Your implementation here
        # 1. Send task to your agent
        # 2. Collect results
        # 3. Track budget
        # 4. Return structured output

        return TaskOutput(
            task_id="",  # Set by caller
            agent_id=self._agent_id,
            status=TaskStatus.SUCCEEDED,
            summary="Completed the task",
            key_findings=[],
        )

    async def terminate(self) -> None:
        # Clean shutdown logic
        pass
```

### Step 2: Handle Predecessor Context

Downstream tasks receive structured outputs from upstream tasks:

```python
async def execute_task(self, task_description, role, workspace,
                       predecessor_context, allowed_tools) -> TaskOutput:
    # Include predecessor findings in the prompt
    context_parts = []
    for pred in predecessor_context:
        context_parts.append(f"Previous task ({pred.task_id}):")
        context_parts.append(f"  Summary: {pred.summary}")
        for f in pred.key_findings:
            context_parts.append(f"  Finding ({f.confidence}): {f.finding}")

    full_prompt = task_description + "\n\nContext:\n" + "\n".join(context_parts)
    # ... execute with full_prompt
```

### Step 3: Track Budget

Always report resource consumption:

```python
from agentos.schemas.budget import BudgetDelta

# After each API call or significant operation
self._budget_manager.apply(self._agent_id, BudgetDelta(
    tokens=response.usage.total_tokens,
    api_calls=1,
    time_seconds=elapsed,
    cost_usd=estimated_cost,
))
```

### Step 4: Test Your Adapter

```python
import pytest
from agentos.kernel.budget_manager import BudgetManager
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec

@pytest.fixture
def adapter():
    event_log = SQLiteEventLog()
    seq = SeqCounter()
    budget_mgr = BudgetManager(
        workflow_spec=BudgetSpec(), event_log=event_log,
        seq=seq, workflow_id="test",
    )
    return MyCustomAdapter(budget_mgr, "test-agent")

@pytest.mark.asyncio
async def test_execute_task(adapter, tmp_path):
    output = await adapter.execute_task(
        task_description="Test task",
        role="Test role",
        workspace=tmp_path,
        predecessor_context=[],
        allowed_tools=[],
    )
    assert output.status == TaskStatus.SUCCEEDED
    assert output.summary
```

## Key Design Principles

1. **Structured output is mandatory**: Every task must produce a `TaskOutput`. No unstructured file passing.

2. **Budget tracking is required**: Adapters must report resource consumption via `BudgetManager.apply()`.

3. **Tier determines enforcement level**:
   - Tier 1: Real-time capability enforcement per tool call
   - Tier 2: Workspace scoping + post-hoc output validation
   - Tier 3: Best-effort — minimal guarantees

4. **Async from the start**: `execute_task` is async. Use `asyncio.run()` if calling from sync code.

5. **Clean termination**: `terminate()` must handle graceful shutdown. Resources should be released.
