"""Progressive context delivery — inject only what's changed since last activation.

Tracks what each agent has already seen (board version, summary version)
and only injects new/changed content. Achieves ~50% token reduction.
"""

from __future__ import annotations

from agentos.comms.ambient_context import AmbientContextInjector
from agentos.comms.board_manager import BoardManager
from agentos.comms.message_bus import MessageBus
from agentos.workspace.context_summary import ContextSummaryManager
from agentos.workspace.schemas import ActivationContext, BacklogTask


class ProgressiveContextDelivery:
    """Tracks delivery state per agent, injects only changes."""

    def __init__(
        self,
        board: BoardManager,
        summary_mgr: ContextSummaryManager,
        bus: MessageBus,
    ) -> None:
        self._board = board
        self._summary_mgr = summary_mgr
        self._bus = bus
        self._injector = AmbientContextInjector(board)

        # Per-agent watermarks: agent_id → {board_version, summary_version}
        self._watermarks: dict[str, dict[str, int]] = {}

    def build_activation_context(
        self,
        agent_id: str,
        task: BacklogTask,
        predecessor_outputs: list[dict] | None = None,
        allowed_tools: list[str] | None = None,
        budget=None,
        role: str = "",
        specialization: str = "",
    ) -> ActivationContext:
        """Build full activation context for an agent, using progressive delivery."""
        wm = self._watermarks.get(agent_id, {})
        last_board = wm.get("board_version")
        last_summary = wm.get("summary_version")

        # Board state
        board_state = self._board.get_state()
        board_compact = self._board.render_compact(max_tokens=200)

        # Messages
        pending = self._bus.receive(agent_id)

        # Summaries
        agent_summary = self._summary_mgr.get_agent_summary(agent_id)
        workspace_summary = self._summary_mgr.get_workspace_summary()

        ctx = ActivationContext(
            agent_id=agent_id,
            role=role,
            specialization=specialization,
            task=task,
            predecessor_outputs=predecessor_outputs or [],
            board_state_compact=board_compact,
            pending_messages=[m.model_dump() for m in pending] if pending else [],
            agent_summary=agent_summary,
            workspace_summary=workspace_summary,
            allowed_tools=allowed_tools or [],
            budget=budget or task.budget,
            last_seen_board_version=last_board,
            last_seen_summary_version=last_summary,
        )

        # Update watermarks
        self._watermarks[agent_id] = {
            "board_version": board_state.version,
            "summary_version": agent_summary.summary_version if agent_summary else 0,
        }

        return ctx

    def build_mid_task_injection(self, agent_id: str) -> str | None:
        """Build injection for Tier 1 tool boundaries. Returns None if nothing changed."""
        wm = self._watermarks.get(agent_id, {})
        last_board = wm.get("board_version")

        pending = self._bus.receive(agent_id, mark_delivered=False)
        has_messages = bool(pending)

        # Check board changes
        board_state = self._board.get_state()
        board_changed = last_board is None or board_state.version > last_board

        if not board_changed and not has_messages:
            return None

        # Actually receive (mark delivered) and build injection
        delivered = self._bus.receive(agent_id) if has_messages else []

        injection = self._injector.build_injection(
            agent_id,
            pending_messages=delivered or None,
            last_seen_board_version=last_board,
        )

        if injection:
            self._watermarks.setdefault(agent_id, {})["board_version"] = board_state.version

        return injection

    def mark_delivered(self, agent_id: str, board_version: int, summary_version: int) -> None:
        """Manually update watermarks."""
        self._watermarks[agent_id] = {
            "board_version": board_version,
            "summary_version": summary_version,
        }
