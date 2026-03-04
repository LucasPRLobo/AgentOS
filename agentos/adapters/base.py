"""AgentAdapter abstract base class — interface for all adapter tiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


from agentos.schemas.task import TaskOutput


@runtime_checkable
class ProgressCallback(Protocol):
    """Protocol for adapter progress reporting.

    Adapters call this during task execution to report incremental progress.
    The dashboard uses this to push real-time updates via WebSocket.
    """

    def __call__(self, agent_id: str, progress: dict[str, Any]) -> None:
        """Report progress during task execution.

        progress dict keys:
        - type: "tokens" | "tool_call" | "partial_output" | "status"
        - detail: type-specific data
        """
        ...


class AgentAdapter(ABC):
    """Abstract base for all agent adapters.

    Tier 1: AgentOS controls the tool-calling loop.
    Tier 2: AgentOS monitors from outside the loop.
    Tier 3: Best-effort wrappers (not production-grade in V1).
    """

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
        progress_callback: ProgressCallback | None = None,
    ) -> TaskOutput:
        """Execute a task and return structured output.

        Tier 1: Output is enforced via JSON mode.
        Tier 2: Output is parsed from manifest.json in workspace.

        If progress_callback is provided, the adapter should call it
        periodically to report incremental progress.
        """

    @abstractmethod
    async def terminate(self) -> None:
        """Stop the agent cleanly."""
