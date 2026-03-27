"""CLI commands for the AgentOS communication system.

Provides human-facing commands to interact with the workspace board
and direct messaging system during workflow execution.
"""

from __future__ import annotations

import json

import click

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType


def _load_event_log(db: str) -> SQLiteEventLog:
    return SQLiteEventLog(db)


# ======================================================================
# Board commands
# ======================================================================

@click.group()
def board() -> None:
    """View and interact with the workspace board."""


@board.command("show")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
def board_show(workflow_id: str, db: str) -> None:
    """Show the current board state for a workflow."""
    event_log = _load_event_log(db)
    seq = SeqCounter()

    from agentos.comms.board_manager import BoardManager

    bm = BoardManager(event_log, seq, workflow_id)

    # Replay board events to reconstruct state
    events = event_log.query(workflow_id=workflow_id)
    for event in events:
        if event.event_type == EventType.BOARD_POST_CREATED:
            from agentos.comms.schemas import BoardPost

            post = BoardPost(
                post_id=event.payload.get("post_id", ""),
                section=event.payload.get("section", "post"),
                author_type=event.payload.get("author_type", "system"),
                author_id=event.payload.get("author_id", "system"),
                content=event.payload.get("content_preview", ""),
                speech_act=event.payload.get("speech_act", "inform"),
            )
            bm.post(post)

    compact = bm.render_compact(max_tokens=500)
    click.echo(compact)


@board.command("post")
@click.argument("content")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
@click.option(
    "--section",
    type=click.Choice(["post", "question", "decision", "announcement"]),
    default="post",
)
def board_post(content: str, workflow_id: str, db: str, section: str) -> None:
    """Post a message to the board as the human manager."""
    event_log = _load_event_log(db)
    seq = SeqCounter()

    from agentos.comms.board_manager import BoardManager
    from agentos.comms.schemas import BoardPost, BoardSection, SpeechAct

    bm = BoardManager(event_log, seq, workflow_id)
    post = BoardPost(
        section=BoardSection(section),
        author_type="human",
        author_id="human",
        content=content,
        speech_act=SpeechAct.DIRECTIVE if section == "announcement" else SpeechAct.INFORM,
        pinned=section == "announcement",
    )
    post_id = bm.post(post)
    click.echo(f"Posted to board [{section}]: {post_id}")


@board.command("pin")
@click.argument("post_id")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
def board_pin(post_id: str, workflow_id: str, db: str) -> None:
    """Pin a post to announcements."""
    event_log = _load_event_log(db)
    seq = SeqCounter()

    from agentos.comms.board_manager import BoardManager

    bm = BoardManager(event_log, seq, workflow_id)
    try:
        bm.pin(post_id)
        click.echo(f"Pinned: {post_id}")
    except ValueError as e:
        click.echo(click.style(str(e), fg="red"))


@board.command("resolve")
@click.argument("post_id")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
def board_resolve(post_id: str, workflow_id: str, db: str) -> None:
    """Mark a question or proposal as resolved."""
    event_log = _load_event_log(db)
    seq = SeqCounter()

    from agentos.comms.board_manager import BoardManager

    bm = BoardManager(event_log, seq, workflow_id)
    try:
        bm.resolve(post_id, resolved_by="human")
        click.echo(f"Resolved: {post_id}")
    except ValueError as e:
        click.echo(click.style(str(e), fg="red"))


# ======================================================================
# Message commands
# ======================================================================

@click.group()
def message() -> None:
    """Send and view direct messages in a workspace."""


@message.command("send")
@click.argument("recipient")
@click.argument("content")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
@click.option(
    "--priority",
    type=click.Choice(["low", "normal", "high", "critical"]),
    default="normal",
)
@click.option(
    "--speech-act",
    type=click.Choice(["inform", "request", "directive"]),
    default="directive",
)
def message_send(
    recipient: str,
    content: str,
    workflow_id: str,
    db: str,
    priority: str,
    speech_act: str,
) -> None:
    """Send a direct message to an agent."""
    event_log = _load_event_log(db)
    seq = SeqCounter()

    from agentos.comms.message_bus import MessageBus
    from agentos.comms.schemas import DirectMessage, MessagePriority, SpeechAct

    bus = MessageBus(event_log, seq, workflow_id)
    msg = DirectMessage(
        sender_type="human",
        sender_id="human",
        recipient_type="agent",
        recipient_id=recipient,
        content=content,
        speech_act=SpeechAct(speech_act),
        priority=MessagePriority(priority),
        workflow_id=workflow_id,
    )
    mid = bus.send(msg)
    click.echo(f"Message sent to {recipient}: {mid}")


@message.command("list")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
def message_list(workflow_id: str, db: str) -> None:
    """Show recent messages in a workflow."""
    event_log = _load_event_log(db)

    events = event_log.query(
        workflow_id=workflow_id,
        event_type=EventType.DIRECT_MESSAGE_SENT,
    )
    if not events:
        click.echo("No messages found.")
        return

    for event in events[-20:]:
        p = event.payload
        sender = p.get("sender_id", "?")
        recipient = p.get("recipient_id", "?")
        act = p.get("speech_act", "inform")
        preview = p.get("content_preview", "")
        priority = p.get("priority", "normal")
        ts = str(event.timestamp)[:19]

        priority_mark = ""
        if priority in ("high", "critical"):
            priority_mark = click.style(f" [{priority.upper()}]", fg="red")

        click.echo(
            f"  {ts} | {sender} → {recipient} [{act}]{priority_mark}"
        )
        click.echo(f"    {preview}")


@message.command("thread")
@click.argument("thread_id")
@click.option("--workflow-id", "-w", required=True, help="Workflow ID")
@click.option("--db", default="agentos.db", help="Database path")
def message_thread(thread_id: str, workflow_id: str, db: str) -> None:
    """Show a full conversation thread."""
    event_log = _load_event_log(db)

    events = event_log.query(
        workflow_id=workflow_id,
        event_type=EventType.DIRECT_MESSAGE_SENT,
    )

    thread_events = [
        e for e in events
        if e.payload.get("thread_id") == thread_id
    ]

    if not thread_events:
        click.echo(f"No messages found in thread {thread_id}")
        return

    click.echo(f"Thread: {thread_id}")
    click.echo("-" * 60)
    for event in thread_events:
        p = event.payload
        sender = p.get("sender_id", "?")
        act = p.get("speech_act", "inform")
        preview = p.get("content_preview", "")
        ts = str(event.timestamp)[:19]
        click.echo(f"  {ts} | {sender} [{act}]: {preview}")
