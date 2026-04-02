#!/usr/bin/env python3
"""Start the AgentOS dashboard with a demo workspace loaded.

Usage:
    python examples/start_dashboard.py [workspace.yaml]

Opens the dashboard at http://localhost:8420 with a workspace
pre-loaded so you can see the board, backlog, and chat.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile

from agentos.comms.schemas import (
    AgentStatus,
    BoardPost,
    BoardSection,
    DirectMessage,
    MessagePriority,
    SpeechAct,
)
from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.workspace.loader import load_workspace_config
from agentos.workspace.runtime import WorkspaceRuntime
from agentos.workspace.schemas import BacklogTask


def main():
    yaml_path = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).parent / "workspace_demo.yaml"
    )

    tmpdir = Path(tempfile.mkdtemp(prefix="agentos_dashboard_"))
    db_path = str(tmpdir / "dashboard.db")
    workspace = tmpdir / "workspace"
    workspace.mkdir()

    # Load config
    config = load_workspace_config(Path(yaml_path))
    event_log = SQLiteEventLog(db_path)
    seq = SeqCounter()
    wf_id = f"ws-{config.name.lower().replace(' ', '-')[:30]}"

    # Create and start runtime
    runtime = WorkspaceRuntime(config, event_log, seq, wf_id, workspace)
    runtime.start()

    # Add some demo data so the dashboard isn't empty
    t1 = runtime.add_task(BacklogTask(
        title="Research A2A Protocol",
        description="Research Google's Agent-to-Agent protocol. Write findings to a2a_research.md.",
        created_by="coordinator",
        suggested_for="researcher",
        priority="high",
    ))
    t2 = runtime.add_task(BacklogTask(
        title="Research MCP Protocol",
        description="Research Anthropic's MCP protocol. Write findings to mcp_research.md.",
        created_by="coordinator",
        suggested_for="researcher",
        priority="high",
    ))
    t3 = runtime.add_task(BacklogTask(
        title="Write Comparison Report",
        description="Compare A2A and MCP. Write report.md.",
        created_by="coordinator",
        suggested_for="writer",
        depends_on=[t1, t2],
        priority="normal",
    ))

    # Claim and start one task to show activity
    runtime.claim_task(t1, "researcher")
    runtime.backlog.start_task(t1)

    # Add a board post
    runtime.board.post(BoardPost(
        section=BoardSection.POST,
        author_type="agent",
        author_id="researcher",
        content="Starting research on A2A protocol. Will focus on architecture, discovery mechanism, and task lifecycle.",
        speech_act=SpeechAct.STATUS,
    ))

    # Add a message
    runtime.bus.send(DirectMessage(
        sender_type="agent",
        sender_id="researcher",
        recipient_type="human",
        recipient_id="human",
        content="I've started working on the A2A research. Any specific aspects you want me to focus on?",
        speech_act=SpeechAct.REQUEST,
        priority=MessagePriority.NORMAL,
        workflow_id=wf_id,
    ))

    # Register runtime with the dashboard
    from agentos.dashboard.workspace_api import register_runtime
    register_runtime(wf_id, runtime)

    print(f"AgentOS Dashboard")
    print(f"=" * 50)
    print(f"Workspace: {config.name}")
    print(f"ID: {wf_id}")
    print(f"Team: {', '.join(p.name for p in config.team)}")
    print(f"Tasks: {len(runtime.backlog.get_all_tasks())}")
    print(f"Database: {db_path}")
    print(f"")
    print(f"Dashboard: http://localhost:8420")
    print(f"Workspace: http://localhost:8420/workspace/{wf_id}")
    print(f"API: http://localhost:8420/api/workspaces")
    print(f"")
    print(f"Press Ctrl+C to stop.")
    print(f"=" * 50)

    import os
    os.environ["AGENTOS_DB"] = db_path

    import uvicorn
    from agentos.dashboard.app import create_app

    app = create_app(db_path)
    # Re-register after app creation (create_app makes a new module-level app)
    register_runtime(wf_id, runtime)

    uvicorn.run(app, host="127.0.0.1", port=8420, log_level="warning")


if __name__ == "__main__":
    main()
