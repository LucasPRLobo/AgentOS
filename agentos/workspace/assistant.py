"""AssistantSpawner — ephemeral sub-agents for workers.

Spawns lightweight agents scoped to a single sub-task.
Depth limited to 1 (assistants cannot spawn other assistants).
Budget deducted from the worker's task allocation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.budget import BudgetSpec
from agentos.schemas.events import Event, EventType
from agentos.workspace.schemas import _uuid

logger = logging.getLogger(__name__)

# Minimum tokens for spawning to make sense (below this, do it inline).
_MIN_SPAWN_TOKENS = 5000

# Overhead per spawn in tokens (session init, context assembly).
_SPAWN_OVERHEAD_TOKENS = 2500


class AssistantSpawner:
    """Spawns ephemeral assistant agents for workers."""

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._active: dict[str, dict] = {}  # assistant_id → metadata

    def should_spawn(self, estimated_tokens: int) -> bool:
        """Heuristic: only spawn if the sub-task is large enough to justify overhead."""
        return estimated_tokens > _MIN_SPAWN_TOKENS

    async def spawn(
        self,
        worker_id: str,
        task_description: str,
        tools: list[str] | None = None,
        model: str | None = None,
        budget: BudgetSpec | None = None,
        workspace: Path | None = None,
        adapter_factory=None,
    ) -> dict:
        """Spawn an assistant and return its output.

        *adapter_factory* is a callable(model, tools, budget) → adapter
        for testability. In production this creates a Tier 1 adapter.

        Returns a dict with at minimum {"summary": "...", "status": "succeeded"|"failed"}.
        """
        assistant_id = f"assistant-{_uuid()[:8]}"

        self._event_log.append(Event(
            event_type=EventType.ASSISTANT_SPAWNED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "assistant_id": assistant_id,
                "worker_id": worker_id,
                "task_description": task_description[:200],
                "model": model or "default",
            },
        ))

        self._active[assistant_id] = {
            "worker_id": worker_id,
            "task": task_description,
        }

        output = {"summary": "Assistant completed.", "status": "succeeded"}

        try:
            if adapter_factory is not None:
                adapter = adapter_factory(model, tools, budget)
                result = await adapter.execute_task(
                    task_description=task_description,
                    role="You are a helper assistant. Complete the sub-task and return results.",
                    workspace=workspace or Path("."),
                    predecessor_context=[],
                    allowed_tools=tools or ["Read", "Write", "Grep"],
                )
                output = {
                    "summary": result.summary,
                    "status": str(result.status),
                    "findings": [f.model_dump() for f in (result.key_findings or [])],
                    "open_questions": result.open_questions or [],
                }
        except Exception as exc:
            logger.error("Assistant %s failed: %s", assistant_id, exc, exc_info=True)
            output = {"summary": f"Assistant failed: {exc}", "status": "failed"}

        self._event_log.append(Event(
            event_type=EventType.ASSISTANT_COMPLETED,
            workflow_id=self._workflow_id,
            seq=self._seq.next(),
            payload={
                "assistant_id": assistant_id,
                "worker_id": worker_id,
                "status": output["status"],
            },
        ))

        self._active.pop(assistant_id, None)
        return output

    def get_active_count(self, worker_id: str) -> int:
        """How many assistants are currently active for a worker."""
        return sum(1 for a in self._active.values() if a["worker_id"] == worker_id)
