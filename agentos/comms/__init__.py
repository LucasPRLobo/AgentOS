"""AgentOS Communication System — Board + Direct Messaging.

Provides the communication infrastructure for the collaborative workspace:
- BoardManager: shared board state visible to all participants
- MessageBus: direct messaging between agents and humans
- AmbientContextInjector: board state injection into agent context
"""

from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    BoardState,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)

__all__ = [
    "AgentStatus",
    "BoardPost",
    "BoardSection",
    "BoardState",
    "DirectMessage",
    "MessagePriority",
    "SpeechAct",
]
