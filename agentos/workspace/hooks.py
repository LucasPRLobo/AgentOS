"""Workspace hooks — event-driven extension points for workspace behavior.

Inspired by Claude Code's 11-event hook system. Hooks fire at lifecycle
boundaries and allow the coordinator, plugins, and user code to react
to workspace events.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WorkspaceEvent(StrEnum):
    """Events that can trigger hooks."""
    WORKSPACE_STARTED = "workspace_started"
    WORKSPACE_PAUSED = "workspace_paused"
    WORKSPACE_COMPLETED = "workspace_completed"
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_UNBLOCKED = "task_unblocked"
    AGENT_ACTIVATED = "agent_activated"
    AGENT_DEACTIVATED = "agent_deactivated"
    BOARD_POST_CREATED = "board_post_created"
    MESSAGE_RECEIVED = "message_received"
    BUDGET_THRESHOLD = "budget_threshold"
    TEAM_CHANGED = "team_changed"
    STALL_DETECTED = "stall_detected"
    COMPLETION_CHECK = "completion_check"


# Hook callback type: (event, payload) → optional dict with actions
HookCallback = Callable[[WorkspaceEvent, dict[str, Any]], dict[str, Any] | None]


class WorkspaceHookManager:
    """Manages workspace event hooks.

    Hooks are registered per-event. When an event fires, all registered
    hooks run in order. Hooks can return actions (post to board, send
    message, create task, etc.) that the runtime processes.
    """

    def __init__(self) -> None:
        self._hooks: dict[WorkspaceEvent, list[HookCallback]] = {}

    def register(self, event: WorkspaceEvent, callback: HookCallback) -> None:
        """Register a hook for an event."""
        self._hooks.setdefault(event, []).append(callback)

    def unregister(self, event: WorkspaceEvent, callback: HookCallback) -> None:
        """Remove a specific hook."""
        hooks = self._hooks.get(event, [])
        self._hooks[event] = [h for h in hooks if h is not callback]

    def fire(self, event: WorkspaceEvent, payload: dict[str, Any] | None = None) -> list[dict]:
        """Fire an event and collect all hook responses.

        Returns a list of action dicts from hooks that returned non-None.
        """
        hooks = self._hooks.get(event, [])
        if not hooks:
            return []

        results: list[dict] = []
        for hook in hooks:
            try:
                result = hook(event, payload or {})
                if result is not None:
                    results.append(result)
            except Exception as exc:
                logger.error(
                    "Hook failed for %s: %s", event, exc, exc_info=True
                )
        return results

    def has_hooks(self, event: WorkspaceEvent) -> bool:
        return bool(self._hooks.get(event))

    def hook_count(self, event: WorkspaceEvent) -> int:
        return len(self._hooks.get(event, []))

    def clear(self, event: WorkspaceEvent | None = None) -> None:
        """Clear hooks for a specific event, or all hooks."""
        if event is not None:
            self._hooks.pop(event, None)
        else:
            self._hooks.clear()


# ---------------------------------------------------------------------------
# Built-in hooks
# ---------------------------------------------------------------------------

def auto_post_task_to_board(event: WorkspaceEvent, payload: dict) -> dict | None:
    """Auto-post task creation/completion to the board."""
    if event == WorkspaceEvent.TASK_COMPLETED:
        return {
            "action": "board_post",
            "content": f"Completed: {payload.get('title', 'task')}",
            "section": "post",
        }
    if event == WorkspaceEvent.TASK_FAILED:
        return {
            "action": "board_alert",
            "content": f"Failed: {payload.get('title', 'task')} — {payload.get('error', 'unknown')}",
        }
    return None


def auto_check_completion(event: WorkspaceEvent, payload: dict) -> dict | None:
    """Trigger completion check after task completion."""
    if event == WorkspaceEvent.TASK_COMPLETED:
        return {"action": "check_completion"}
    return None


def auto_detect_stall(event: WorkspaceEvent, payload: dict) -> dict | None:
    """Flag stalled tasks to the coordinator."""
    if event == WorkspaceEvent.STALL_DETECTED:
        return {
            "action": "coordinator_alert",
            "content": f"Task stalled: {payload.get('task_id', '?')} "
                       f"({payload.get('stall_count', 0)} cycles)",
        }
    return None


def register_default_hooks(manager: WorkspaceHookManager) -> None:
    """Register the standard set of workspace hooks."""
    manager.register(WorkspaceEvent.TASK_COMPLETED, auto_post_task_to_board)
    manager.register(WorkspaceEvent.TASK_FAILED, auto_post_task_to_board)
    manager.register(WorkspaceEvent.TASK_COMPLETED, auto_check_completion)
    manager.register(WorkspaceEvent.STALL_DETECTED, auto_detect_stall)
