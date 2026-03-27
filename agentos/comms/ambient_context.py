"""AmbientContextInjector — board state + message rendering for agents.

Formats board state and direct messages into compact text that can be
injected into an agent's context at tool-call or turn boundaries.
This is the mechanism by which agents "glance at the board" — inspired
by Google ADK's yield/resume pattern.

See docs/COMMS_RESEARCH_AND_PLAN.md §5.4 for design rationale.
"""

from __future__ import annotations

from agentos.comms.board_manager import BoardManager
from agentos.comms.schemas import DirectMessage, MessagePriority


class AmbientContextInjector:
    """Formats board state and messages for injection into agent context.

    Design principles:
    - **Compact**: ~100-200 tokens by default.
    - **Differential**: returns ``None`` if nothing changed since last check.
    - **Prioritised**: pinned > alerts > high-priority messages > posts.
    - **Agent-specific**: highlights content addressed to the target agent.
    """

    def __init__(self, board_manager: BoardManager) -> None:
        self._board = board_manager

    # ------------------------------------------------------------------
    # Board rendering
    # ------------------------------------------------------------------

    def render_for_agent(
        self,
        agent_id: str,
        last_seen_version: int | None = None,
        token_budget: int = 200,
    ) -> str | None:
        """Render the board state for injection into *agent_id*'s context.

        Returns ``None`` if the board hasn't changed since
        *last_seen_version*, avoiding redundant injections.
        """
        state = self._board.get_state()
        if last_seen_version is not None and state.version <= last_seen_version:
            return None
        return self._board.render_compact(max_tokens=token_budget)

    # ------------------------------------------------------------------
    # Message formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_message_injection(messages: list[DirectMessage]) -> str:
        """Format direct messages for injection into an LLM conversation.

        Produces a clearly delineated block that agents can parse and
        respond to.  High-priority and directive messages are highlighted.
        """
        if not messages:
            return ""

        parts: list[str] = [
            "[TEAM COMMUNICATION — Messages from your workspace]",
        ]

        for msg in messages:
            header = f"From: {msg.sender_id} ({msg.sender_type})"
            if msg.priority in (MessagePriority.HIGH, MessagePriority.CRITICAL):
                header += f" [PRIORITY: {msg.priority.value.upper()}]"
            if msg.speech_act == "directive":
                header += " [DIRECTIVE — you must follow this instruction]"

            parts.append(f"\n{header}")
            parts.append(msg.content)

            if msg.speech_act == "request":
                parts.append(
                    "(Response expected — address this in your output "
                    "or use the send_message tool to reply.)"
                )

        parts.append(
            "\n[END TEAM COMMUNICATION — "
            "Continue your work, incorporating the above as needed]"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Combined injection
    # ------------------------------------------------------------------

    def build_injection(
        self,
        agent_id: str,
        pending_messages: list[DirectMessage] | None = None,
        last_seen_board_version: int | None = None,
        board_token_budget: int = 200,
    ) -> str | None:
        """Build a single injection string combining board + messages.

        Returns ``None`` if there is nothing to inject (board unchanged
        and no pending messages).
        """
        board_text = self.render_for_agent(
            agent_id,
            last_seen_version=last_seen_board_version,
            token_budget=board_token_budget,
        )
        msg_text = (
            self.format_message_injection(pending_messages)
            if pending_messages
            else None
        )

        if board_text is None and not msg_text:
            return None

        sections: list[str] = []
        if board_text:
            sections.append(board_text)
        if msg_text:
            sections.append(msg_text)
        return "\n\n".join(sections)
