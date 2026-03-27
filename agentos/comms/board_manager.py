"""BoardManager — shared board state for workspace awareness.

Maintains the workspace board: a structured, living document visible to all
participants (agents and humans).  Based on the blackboard pattern from
LbMAS research, adapted for LLM agent workspaces.

See docs/COMMS_RESEARCH_AND_PLAN.md §5 for design rationale.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    BoardState,
    SpeechAct,
    _utc_now_iso,
)
from agentos.kernel.event_log import EventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import Event, EventType

logger = logging.getLogger(__name__)

# Maximum number of recent posts kept on the board.
MAX_RECENT_POSTS = 20


class BoardManager:
    """Maintains the shared board state for a workspace.

    Responsibilities:
    - Accept posts from agents, humans, and the system
    - Auto-update team status from agent state changes
    - Auto-generate system alerts (budget, errors)
    - Archive stale / resolved posts
    - Render compact summaries for agent context injection
    - Render full state for the dashboard API
    - Log all board mutations as events
    """

    def __init__(
        self,
        event_log: EventLog,
        seq: SeqCounter,
        workflow_id: str,
    ) -> None:
        self._event_log = event_log
        self._seq = seq
        self._workflow_id = workflow_id

        self._state = BoardState(workflow_id=workflow_id)
        # post_id → BoardPost  (master index, includes archived)
        self._posts: dict[str, BoardPost] = {}
        # Archived post IDs (removed from active board)
        self._archived: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def post(self, post: BoardPost) -> str:
        """Add a post to the board.  Returns *post_id*.

        The post is routed to the appropriate section based on
        ``post.section``.  Logs ``BOARD_POST_CREATED``.
        """
        with self._lock:
            self._posts[post.post_id] = post
            self._route_post(post)
            self._bump_version()

        self._event_log.append(
            Event(
                event_type=EventType.BOARD_POST_CREATED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "post_id": post.post_id,
                    "section": post.section,
                    "author_type": post.author_type,
                    "author_id": post.author_id,
                    "speech_act": post.speech_act,
                    "content_preview": post.content[:120],
                },
            )
        )
        return post.post_id

    def _route_post(self, post: BoardPost) -> None:
        """Route a post to the correct section list (caller holds lock)."""
        section = post.section
        if section == BoardSection.ANNOUNCEMENT or post.pinned:
            self._state.announcements.append(post)
        elif section == BoardSection.DECISION:
            self._state.decisions.append(post)
        elif section == BoardSection.QUESTION:
            self._state.open_questions.append(post)
        elif section == BoardSection.ALERT:
            self._state.alerts.append(post)
        else:
            # POST or STATUS — goes to recent_posts
            self._state.recent_posts.insert(0, post)
            if len(self._state.recent_posts) > MAX_RECENT_POSTS:
                self._state.recent_posts = self._state.recent_posts[:MAX_RECENT_POSTS]

    # ------------------------------------------------------------------
    # Pin / unpin
    # ------------------------------------------------------------------

    def pin(self, post_id: str) -> None:
        """Pin a post to announcements."""
        with self._lock:
            post = self._posts.get(post_id)
            if post is None:
                raise ValueError(f"Unknown post: {post_id}")
            if post.pinned:
                return
            post.pinned = True
            # Move to announcements if not already there
            self._remove_from_sections(post_id)
            self._state.announcements.append(post)
            self._bump_version()

        self._event_log.append(
            Event(
                event_type=EventType.BOARD_POST_PINNED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={"post_id": post_id},
            )
        )

    def unpin(self, post_id: str) -> None:
        """Unpin a post — moves it back to recent_posts."""
        with self._lock:
            post = self._posts.get(post_id)
            if post is None:
                raise ValueError(f"Unknown post: {post_id}")
            if not post.pinned:
                return
            post.pinned = False
            self._remove_from_sections(post_id)
            self._state.recent_posts.insert(0, post)
            self._bump_version()

    # ------------------------------------------------------------------
    # Resolve
    # ------------------------------------------------------------------

    def resolve(self, post_id: str, resolved_by: str) -> None:
        """Mark a question or proposal as resolved."""
        with self._lock:
            post = self._posts.get(post_id)
            if post is None:
                raise ValueError(f"Unknown post: {post_id}")
            post.resolved = True
            post.resolved_by = resolved_by
            self._bump_version()

        self._event_log.append(
            Event(
                event_type=EventType.BOARD_POST_RESOLVED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={
                    "post_id": post_id,
                    "resolved_by": resolved_by,
                },
            )
        )

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def archive(self, post_id: str) -> None:
        """Remove a post from the active board."""
        with self._lock:
            if post_id not in self._posts:
                raise ValueError(f"Unknown post: {post_id}")
            self._archived.add(post_id)
            self._remove_from_sections(post_id)
            self._bump_version()

        self._event_log.append(
            Event(
                event_type=EventType.BOARD_POST_ARCHIVED,
                workflow_id=self._workflow_id,
                seq=self._seq.next(),
                payload={"post_id": post_id},
            )
        )

    # ------------------------------------------------------------------
    # Team status
    # ------------------------------------------------------------------

    def update_agent_status(self, status: AgentStatus) -> None:
        """Update (or add) an agent's entry in the team roster."""
        with self._lock:
            existing = [
                i for i, s in enumerate(self._state.team_status)
                if s.agent_id == status.agent_id
            ]
            if existing:
                self._state.team_status[existing[0]] = status
            else:
                self._state.team_status.append(status)
            self._bump_version()

    # ------------------------------------------------------------------
    # System alerts
    # ------------------------------------------------------------------

    def add_system_alert(
        self,
        content: str,
        structured_data: dict | None = None,
        expires_minutes: int = 60,
    ) -> str:
        """Add a system-generated alert to the board.  Returns post_id."""
        now = datetime.now(UTC)
        expires = now.replace(minute=now.minute) if expires_minutes <= 0 else None
        if expires_minutes > 0:
            from datetime import timedelta
            expires = now + timedelta(minutes=expires_minutes)

        post = BoardPost(
            section=BoardSection.ALERT,
            author_type="system",
            author_id="system",
            content=content,
            speech_act=SpeechAct.ALERT,
            structured_data=structured_data,
            expires_at=expires.isoformat() if expires else None,
        )
        return self.post(post)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get_state(self) -> BoardState:
        """Return the current board state (snapshot)."""
        with self._lock:
            # Return a copy to prevent external mutation
            return self._state.model_copy(deep=True)

    def render_compact(self, max_tokens: int = 200) -> str:
        """Render a compact text summary for agent context injection.

        Stays within *max_tokens* (estimated at ~4 chars per token).
        Prioritises: pinned announcements > alerts > open questions >
        recent posts > team status.
        """
        max_chars = max_tokens * 4
        parts: list[str] = []
        used = 0

        with self._lock:
            state = self._state

            header = f"[WORKSPACE BOARD — v{state.version}]"
            parts.append(header)
            used += len(header)

            # Pinned announcements
            for post in state.announcements:
                line = f"PINNED: {post.content}"
                if used + len(line) + 1 > max_chars:
                    break
                parts.append(line)
                used += len(line) + 1

            # Alerts
            for post in state.alerts:
                line = f"ALERT: {post.content}"
                if used + len(line) + 1 > max_chars:
                    break
                parts.append(line)
                used += len(line) + 1

            # Open questions
            for post in state.open_questions:
                if post.resolved:
                    continue
                line = f"QUESTION ({post.author_id}): {post.content}"
                if used + len(line) + 1 > max_chars:
                    break
                parts.append(line)
                used += len(line) + 1

            # Recent posts (max 3)
            for post in state.recent_posts[:3]:
                line = f"[{post.author_id}] {post.content}"
                if used + len(line) + 1 > max_chars:
                    break
                parts.append(line)
                used += len(line) + 1

            # Team status
            status_lines: list[str] = []
            for agent in state.team_status:
                s = f"  {agent.agent_name or agent.agent_id}: {agent.state}"
                if agent.progress_summary:
                    s += f" ({agent.progress_summary})"
                status_lines.append(s)
            if status_lines:
                team_block = "Team:\n" + "\n".join(status_lines)
                if used + len(team_block) + 1 <= max_chars:
                    parts.append(team_block)

            parts.append("[END BOARD]")

        return "\n".join(parts)

    def render_full(self) -> dict:
        """Full board state as a dict (for dashboard API / JSON)."""
        with self._lock:
            return self._state.model_dump()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Archive posts that have passed their ``expires_at``."""
        now = datetime.now(UTC).isoformat()
        to_archive: list[str] = []

        with self._lock:
            for pid, post in self._posts.items():
                if (
                    pid not in self._archived
                    and post.expires_at is not None
                    and post.expires_at <= now
                ):
                    to_archive.append(pid)

        for pid in to_archive:
            self.archive(pid)
        return len(to_archive)

    def cleanup_resolved(self, older_than_minutes: int = 30) -> int:
        """Archive resolved questions/proposals older than threshold."""
        from datetime import timedelta

        cutoff = (
            datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        ).isoformat()
        to_archive: list[str] = []

        with self._lock:
            for pid, post in self._posts.items():
                if (
                    pid not in self._archived
                    and post.resolved
                    and post.timestamp <= cutoff
                ):
                    to_archive.append(pid)

        for pid in to_archive:
            self.archive(pid)
        return len(to_archive)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bump_version(self) -> None:
        """Increment board version and update timestamp (caller holds lock)."""
        self._state.version += 1
        self._state.last_updated = _utc_now_iso()

    def _remove_from_sections(self, post_id: str) -> None:
        """Remove a post from all section lists (caller holds lock)."""
        for section_list in (
            self._state.announcements,
            self._state.recent_posts,
            self._state.decisions,
            self._state.open_questions,
            self._state.alerts,
        ):
            section_list[:] = [p for p in section_list if p.post_id != post_id]
