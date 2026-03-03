"""AgentAdapter abstract base class — interface for all adapter tiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agentos.schemas.task import TaskOutput


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
    ) -> TaskOutput:
        """Execute a task and return structured output.

        Tier 1: Output is enforced via JSON mode.
        Tier 2: Output is parsed from manifest.json in workspace.
        """

    @abstractmethod
    async def terminate(self) -> None:
        """Stop the agent cleanly."""
