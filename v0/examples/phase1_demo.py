"""Phase 1 Demo — run a linear workflow with event logging.

Usage:
    python examples/phase1_demo.py
"""

from __future__ import annotations

from pydantic import BaseModel

from agentos.runtime.event_log import SQLiteEventLog
from agentos.runtime.task import TaskNode
from agentos.runtime.workflow import Workflow, WorkflowExecutor
from agentos.tools.base import BaseTool, SideEffect
from agentos.tools.registry import ToolRegistry


# --- Define a simple tool ---

class AddInput(BaseModel):
    a: int
    b: int

class AddOutput(BaseModel):
    result: int

class AddTool(BaseTool):
    @property
    def name(self) -> str:
        return "add"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AddInput

    @property
    def output_schema(self) -> type[BaseModel]:
        return AddOutput

    @property
    def side_effect(self) -> SideEffect:
        return SideEffect.PURE

    def execute(self, input_data: BaseModel) -> BaseModel:
        assert isinstance(input_data, AddInput)
        return AddOutput(result=input_data.a + input_data.b)


def main() -> None:
    # 1. Register a tool
    registry = ToolRegistry()
    add_tool = AddTool()
    registry.register(add_tool)
    print(f"Registered tools: {[t.name for t in registry.list_tools()]}")

    # 2. Use the tool
    validated_input = add_tool.validate_input({"a": 3, "b": 7})
    result = add_tool.execute(validated_input)
    print(f"Tool '{add_tool.name}' executed: 3 + 7 = {result.result}")

    # 3. Build a workflow
    event_log = SQLiteEventLog("phase1_demo.db")

    workflow = Workflow(name="demo-pipeline", tasks=[
        TaskNode(name="fetch-data", callable=lambda: {"rows": 42}),
        TaskNode(name="validate", callable=lambda: {"valid": True}),
        TaskNode(name="compute", callable=lambda: add_tool.execute(AddInput(a=10, b=32))),
    ])

    # 4. Execute it
    print("\n--- Running workflow ---")
    executor = WorkflowExecutor(event_log)
    run_id = executor.run(workflow)

    # 5. Print results
    print(f"\nRun ID: {run_id}")
    for task in workflow.tasks:
        print(f"  [{task.state.value}] {task.name} → {task.result}")

    # 6. Replay events from SQLite
    print("\n--- Event log replay ---")
    for event in event_log.replay(run_id):
        print(f"  seq={event.seq}  {event.event_type.value:20s}  {event.payload}")

    event_log.close()
    print(f"\nEvents persisted to phase1_demo.db")


if __name__ == "__main__":
    main()
