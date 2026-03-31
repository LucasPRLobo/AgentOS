"""AgentRunner — async agent activation with progress tracking.

Inspired by Claude Code's AgentTool pattern: agents launch asynchronously,
report progress (tool count, token count, recent activities), and the
coordinator can monitor/cancel them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentos.comms.board_manager import BoardManager
from agentos.comms.comms_state import write_comms_state
from agentos.comms.message_bus import MessageBus
from agentos.comms.schemas import AgentStatus, BoardPost, BoardSection, SpeechAct
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.schemas import ActivationContext, BacklogTask

logger = logging.getLogger(__name__)


@dataclass
class AgentProgress:
    """Live progress for a running agent."""
    agent_id: str
    task_id: str
    tool_use_count: int = 0
    token_count: int = 0
    recent_activities: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.monotonic)
    status: str = "running"  # running, completed, failed, cancelled

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def add_activity(self, activity: str) -> None:
        self.recent_activities.append(activity)
        if len(self.recent_activities) > 10:
            self.recent_activities = self.recent_activities[-10:]


class AgentRunner:
    """Manages async agent activation and progress tracking.

    Agents are launched asynchronously and tracked. The coordinator
    can check progress, cancel agents, or wait for completion.
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
        board: BoardManager,
        bus: MessageBus,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id
        self._board = board
        self._bus = bus
        self._progress: dict[str, AgentProgress] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    async def launch(
        self,
        agent_id: str,
        task: BacklogTask,
        context: ActivationContext,
        execute_fn: Callable,
        workspace: Path | None = None,
    ) -> str:
        """Launch an agent asynchronously. Returns task_id.

        *execute_fn* is an async callable(agent_id, task, context, workspace,
        progress_callback) → dict (output).
        """
        progress = AgentProgress(agent_id=agent_id, task_id=task.task_id)
        self._progress[task.task_id] = progress

        # Update board
        self._board.update_agent_status(AgentStatus(
            agent_id=agent_id, agent_name=agent_id,
            state="running", current_task=task.task_id,
        ))

        # Write comms state for the agent
        if workspace is not None:
            pending = self._bus.receive(agent_id)
            write_comms_state(workspace, self._board, pending, agent_id, self._workflow_id)

        # Launch async
        async_task = asyncio.create_task(
            self._run_agent(agent_id, task, context, execute_fn, workspace, progress)
        )
        self._running_tasks[task.task_id] = async_task

        logger.info("Agent %s launched for task %s", agent_id, task.task_id)
        return task.task_id

    async def _run_agent(
        self,
        agent_id: str,
        task: BacklogTask,
        context: ActivationContext,
        execute_fn: Callable,
        workspace: Path | None,
        progress: AgentProgress,
    ) -> dict:
        """Execute the agent and track progress."""
        try:
            def progress_callback(activity: str, tokens: int = 0, tools: int = 0):
                progress.add_activity(activity)
                progress.token_count += tokens
                progress.tool_use_count += tools

            output = await execute_fn(
                agent_id, task, context, workspace, progress_callback,
            )
            progress.status = "completed"

            self._board.update_agent_status(AgentStatus(
                agent_id=agent_id, agent_name=agent_id, state="idle",
            ))

            return output or {"summary": "Task completed.", "status": "succeeded"}

        except asyncio.CancelledError:
            progress.status = "cancelled"
            self._board.update_agent_status(AgentStatus(
                agent_id=agent_id, agent_name=agent_id, state="idle",
            ))
            return {"summary": "Task cancelled.", "status": "cancelled"}

        except Exception as exc:
            logger.error("Agent %s failed: %s", agent_id, exc, exc_info=True)
            progress.status = "failed"
            self._board.update_agent_status(AgentStatus(
                agent_id=agent_id, agent_name=agent_id, state="idle",
            ))
            self._board.add_system_alert(f"Agent {agent_id} failed: {exc}")
            return {"summary": f"Failed: {exc}", "status": "failed"}

        finally:
            self._running_tasks.pop(task.task_id, None)

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def get_progress(self, task_id: str) -> AgentProgress | None:
        return self._progress.get(task_id)

    def get_all_progress(self) -> dict[str, AgentProgress]:
        return dict(self._progress)

    def is_running(self, task_id: str) -> bool:
        return task_id in self._running_tasks

    def get_running_count(self) -> int:
        return len(self._running_tasks)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    async def cancel(self, task_id: str) -> None:
        """Cancel a running agent."""
        async_task = self._running_tasks.get(task_id)
        if async_task is not None:
            async_task.cancel()
            logger.info("Cancelled agent for task %s", task_id)

    async def wait_for(self, task_id: str, timeout: float | None = None) -> dict:
        """Wait for an agent to complete. Returns output dict."""
        async_task = self._running_tasks.get(task_id)
        if async_task is None:
            progress = self._progress.get(task_id)
            return {"status": progress.status if progress else "unknown"}
        return await asyncio.wait_for(async_task, timeout=timeout)

    async def wait_all(self, timeout: float | None = None) -> None:
        """Wait for all running agents to complete."""
        if self._running_tasks:
            await asyncio.wait(
                self._running_tasks.values(),
                timeout=timeout,
            )
