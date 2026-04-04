# AgentOS Dashboard API Reference

> Base URL: `http://localhost:8420`
> Authentication: Optional (opt-in via `AGENTOS_AUTH_ENABLED=1`). When enabled, mutating requests (POST/PUT/DELETE) require `Authorization: Bearer <token>`. GET and WebSocket are unauthenticated.
> CORS: Configurable via `AGENTOS_CORS_ORIGINS` env var (default: `http://localhost:5173,http://localhost:8420`).

---

## Workflow Endpoints

### `GET /api/workflows`
List all workflows with summary info.

**Response:** `WorkflowSummary[]`
```json
[
  {
    "workflow_id": "string",
    "name": "string",
    "status": "string",        // e.g. "running", "completed", "failed"
    "task_count": 0,
    "started_at": "ISO8601 | null",
    "completed_at": "ISO8601 | null",
    "total_cost": 0.0,
    "event_count": 0,
    "task_definitions": {}
  }
]
```

---

### `GET /api/workflows/{workflow_id}`
Get full workflow detail (snapshot).

**Path params:** `workflow_id` (string)

**Response (200):** `WorkflowSnapshot`
```json
{
  "workflow_id": "string",
  "workflow_name": "string",
  "status": "string",
  "task_count": 0,
  "started_at": "ISO8601 | null",
  "completed_at": "ISO8601 | null",
  "total_cost": 0.0,
  "total_tokens": 0,
  "event_count": 0,
  "tasks": {
    "<task_name>": {
      "name": "string",
      "state": "string",       // TaskStatus enum value
      "agent_id": "string | null",
      "transitions": [
        { "from": "string", "to": "string", "timestamp": "ISO8601 | null" }
      ],
      "output": {}             // optional, TaskOutput model
    }
  },
  "agents": {
    "<agent_id>": {
      "agent_id": "string",
      "agent_name": "string",
      "adapter_tier": "string",
      "spawned_at": "ISO8601 | null",
      "terminated_at": "ISO8601 | null",
      "termination_reason": "string | null",
      "metrics": {}
    }
  },
  "gates": {
    "<gate_id>": {
      "gate_id": "string",
      "task_id": "string",
      "gate_type": "string",
      "resolution": "string",
      "resolved_by": "string | null",
      "pending": true
    }
  },
  "budgets": {
    "<agent_id>": {
      "agent_id": "string",
      "usage": { "tokens": 0, "cost": 0.0 },
      "exceeded": false,
      "exceeded_resource": "string | null"
    }
  },
  "events": [ /* Event[] */ ],
  "errors": [],
  "task_definitions": {}
}
```

**Response (404):** `{ "detail": "Workflow '<id>' not found" }`

---

### `GET /api/workflows/{workflow_id}/events`
Get events for a workflow with optional filters.

**Path params:** `workflow_id` (string)

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | null | Filter by EventType value |
| `since_seq` | int | null | Only events with seq >= this value |
| `limit` | int (1-1000) | 100 | Max events to return |

**Response:**
```json
{
  "events": [
    {
      "event_id": "string",
      "event_type": "string",
      "workflow_id": "string",
      "seq": 0,
      "timestamp": "ISO8601",
      "schema_version": 1,
      "payload": {},
      "metadata": {}
    }
  ],
  "last_seq": 0
}
```

---

### `GET /api/workflows/{workflow_id}/budget`
Get budget usage for a workflow.

**Response:**
```json
{
  "agents": {
    "<agent_id>": {
      "agent_id": "string",
      "usage": { "tokens": 0, "cost": 0.0 },
      "exceeded": false,
      "exceeded_resource": "string | null"
    }
  },
  "total": {
    "tokens": 0,
    "cost": 0.0
  }
}
```

---

### `GET /api/workflows/{workflow_id}/gates`
Get gate statuses for a workflow.

**Response:** `GateSnapshot[]`
```json
[
  {
    "gate_id": "string",
    "task_id": "string",
    "gate_type": "string",
    "resolution": "string",
    "resolved_by": "string | null",
    "pending": true
  }
]
```

---

### `POST /api/workflows/{workflow_id}/gates/{gate_id}/resolve`
Resolve a pending gate from the UI.

**Request body:**
```json
{
  "resolution": "approved",        // "approved" | "rejected" | "edited"
  "feedback": "optional string",
  "resolved_by": "dashboard_user"  // optional, defaults to "dashboard_user"
}
```

**Response (200):** `{ "gate_id": "string", "resolution": "string" }`
**Response (400):** `{ "detail": "Invalid resolution: ..." }` or `{ "detail": "Failed to resolve gate..." }`

---

## Template Endpoints

### `GET /api/templates`
List all workflow templates.

**Response:** `Template[]` (array of template dicts via `template.to_dict()`)

---

### `GET /api/templates/{template_id}`
Get a specific template.

**Response (200):** `Template`
**Response (404):** `{ "detail": "Template '<id>' not found" }`

---

### `POST /api/templates`
Create a new workflow template.

**Request body:**
```json
{
  "name": "string",            // default: "Untitled"
  "workflow_yaml": "string",   // YAML content
  "description": "string"      // default: ""
}
```

**Response:** `Template`

---

### `PUT /api/templates/{template_id}`
Update an existing template. All fields optional (partial update).

**Request body:**
```json
{
  "name": "string | null",
  "workflow_yaml": "string | null",
  "description": "string | null"
}
```

**Response (200):** `Template`
**Response (404):** `{ "detail": "Template '<id>' not found" }`

---

### `DELETE /api/templates/{template_id}`
Delete a template.

**Response (200):** `{ "deleted": true }`
**Response (404):** `{ "detail": "Template '<id>' not found" }`

---

### `POST /api/templates/validate`
Validate a workflow YAML string.

**Request body:**
```json
{
  "workflow_yaml": "string"
}
```

**Response:** Validation result (via `result.to_dict()`)

---

## Run Management

### `GET /api/run`
List active workflow runs.

**Response:** `RunInfo[]`

---

### `POST /api/run`
Start a new workflow run.

**Request body:**
```json
{
  "workflow_yaml": "string",   // required
  "live": false,               // optional
  "interactive": false         // optional
}
```

**Response (200):** `{ "run_id": "string" }`
**Response (400):** `{ "detail": "workflow_yaml required" }`

---

### `DELETE /api/run/{run_id}`
Cancel a running workflow.

**Response (200):** `{ "cancelled": true }`
**Response (404):** `{ "detail": "Run '<id>' not found" }`

---

## NL Workflow Generation

### `POST /api/builder/generate`
Generate workflow YAML from natural language description.

**Request body:**
```json
{
  "description": "string"  // required
}
```

**Response (200):** `{ "workflow_yaml": "string" }`
**Response (400):** `{ "detail": "description required" }`
**Response (500):** `{ "detail": "Workflow generation failed..." }`

---

## Workspace Endpoints (V2)

All workspace routes are prefixed with `/api/workspaces`.

### `GET /api/workspaces`
List all registered workspaces.

**Response:** `WorkspaceSummary[]`
```json
[
  {
    "workspace_id": "string",
    "name": "string",
    "goal": "string",
    "status": "string",
    "team_mode": "string",
    "team_size": 0,
    "tasks_total": 0,
    "tasks_done": 0,
    "budget_used_pct": 0.0,
    "last_active": "ISO8601",
    "created_at": "ISO8601"
  }
]
```

---

### `GET /api/workspaces/{workspace_id}`
Get full workspace state.

**Response (200):**
```json
{
  "workspace_id": "string",
  "config": {},                // WorkspaceConfig (Pydantic model dump)
  "status": "string",
  "board": {},                 // BoardState model
  "backlog": [],               // BacklogTask[]
  "team": [],                  // AgentStatus[]
  "messages": [],              // DirectMessage[]
  "cost": {
    "total_usd": 0.0,
    "total_tokens": 0,
    "budget_usd": 0.0,
    "budget_tokens": 0,
    "consumed_pct": 0.0,
    "per_agent": {},
    "per_task": {}
  },
  "created_at": "ISO8601",
  "last_active": "ISO8601"
}
```

**Response (404):** `{ "detail": "Workspace not found" }`

---

### `POST /api/workspaces/{workspace_id}/control`
Control workspace lifecycle: pause, resume, complete.

**Request body:**
```json
{
  "action": "pause"  // "pause" | "resume" | "complete"
}
```

**Response (200):** `{ "status": "string" }`
**Response (400):** `{ "detail": "Unknown action: ..." }`
**Response (404):** `{ "detail": "Workspace not found" }`

---

### `GET /api/workspaces/{workspace_id}/board`
Get current board state.

**Response:** `BoardState` (Pydantic model dump — includes posts, announcements, questions, decisions, team_status, etc.)

---

### `POST /api/workspaces/{workspace_id}/board`
Post to the board as the human lead.

**Request body:**
```json
{
  "content": "string",               // required
  "section": "post",                 // "post" | "question" | "decision" | "announcement"
  "speech_act": "inform"             // "inform" | "request" | "propose"
}
```

**Response (200):** `BoardPost` model dump
**Response (400):** `{ "detail": "content required" }`

---

### `GET /api/workspaces/{workspace_id}/backlog`
Get all backlog tasks.

**Response:** `BacklogTask[]`

---

### `POST /api/workspaces/{workspace_id}/backlog`
Create a new backlog task.

**Request body:**
```json
{
  "title": "string",               // required
  "description": "string",         // optional
  "suggested_for": "string | null", // optional — agent to assign
  "priority": "normal"             // optional — priority level
}
```

**Response (200):** `BacklogTask` model dump
**Response (400):** `{ "detail": "title required" }`

---

### `PUT /api/workspaces/{workspace_id}/backlog/{task_id}`
Update a backlog task (claim, start, complete, cancel).

**Request body:**
```json
{
  "action": "claim",              // "claim" | "start" | "complete" | "cancel"
  "participant": "human",         // for "claim" — who claims it
  "summary": "string",            // for "complete" — completion summary
  "reason": "string"              // for "cancel" — cancellation reason
}
```

**Response (200):** updated `BacklogTask` model dump
**Response (400):** `{ "detail": "Unknown action: ..." }` or validation error

---

### `GET /api/workspaces/{workspace_id}/messages`
Get messages, optionally filtered by participant.

**Query params:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `participant` | string | null | Filter messages by participant ID |

**Response:** `DirectMessage[]`

---

### `POST /api/workspaces/{workspace_id}/messages`
Send a direct message.

**Request body:**
```json
{
  "to": "string",                    // required — recipient ID
  "content": "string",              // required
  "speech_act": "inform",           // "inform" | "request" | "propose"
  "priority": "normal"              // "low" | "normal" | "high"
}
```

**Response (200):** `DirectMessage` model dump
**Response (400):** `{ "detail": "to and content required" }`

---

### `GET /api/workspaces/{workspace_id}/messages/{thread_id}`
Get messages in a thread.

**Response:** `DirectMessage[]`

---

### `GET /api/workspaces/{workspace_id}/team`
Get team roster with live agent statuses.

**Response:** `AgentStatus[]`

---

### `GET /api/workspaces/{workspace_id}/cost`
Get cost breakdown.

**Response:**
```json
{
  "total_usd": 0.0,
  "total_tokens": 0,
  "budget_usd": 0.0,
  "budget_tokens": 0,
  "consumed_pct": 0.0,
  "per_agent": {},
  "per_task": {}
}
```

---

## WebSocket Endpoints

### `ws://localhost:8420/ws` — Workflow Event Stream

**Connection lifecycle:**
1. Client connects
2. Server accepts
3. Client sends subscribe message
4. Server sends initial snapshot
5. Server polls every 500ms and pushes new events
6. Connection closed on disconnect or error

**Client -> Server:**
```json
{
  "type": "subscribe",
  "workflow_id": "string",   // required
  "since_seq": 0             // optional, default 0
}
```

**Server -> Client (initial):**
```json
{
  "type": "snapshot",
  "data": { /* full WorkflowSnapshot (same shape as GET /api/workflows/{id}) */ }
}
```

**Server -> Client (ongoing):**
```json
{
  "type": "event",
  "event_id": "string",
  "event_type": "string",
  "workflow_id": "string",
  "seq": 0,
  "timestamp": "ISO8601",
  "schema_version": 1,
  "payload": {},
  "metadata": {}
}
```

**Server -> Client (error):**
```json
{ "type": "error", "message": "Expected subscribe message" }
{ "type": "error", "message": "workflow_id required" }
```

---

### `ws://localhost:8420/ws/workspace/{workspace_id}` — Workspace Live Updates

**Connection lifecycle:**
1. Client connects with workspace_id in URL
2. Server accepts
3. Server sends initial snapshot (board + backlog + team)
4. Server polls every 500ms and pushes deltas
5. Connection closed on disconnect or error

**Server -> Client (error on bad workspace):**
```json
{ "type": "error", "data": { "detail": "Workspace not found" } }
```

**Server -> Client (initial):**
```json
{
  "type": "snapshot",
  "data": {
    "board": {},       // BoardState model dump
    "backlog": [],     // BacklogTask[]
    "team": []         // AgentStatus[]
  }
}
```

**Server -> Client (board post):**
```json
{
  "type": "board_post",
  "data": {}           // BoardPost model dump
}
```

**Server -> Client (agent status update):**
```json
{
  "type": "agent_status",
  "data": []           // AgentStatus[] — full list
}
```

**Server -> Client (backlog update):**
```json
{
  "type": "backlog_update",
  "data": []           // BacklogTask[] — full list
}
```

**Server -> Client (new message):**
```json
{
  "type": "message",
  "data": {}           // DirectMessage model dump
}
```

---

## Key Enum Values

**EventType** — values used in event filtering and payloads:
- `WORKFLOW_STARTED`, `WORKFLOW_COMPLETED`, `WORKFLOW_FAILED`
- `TASK_QUEUED`, `TASK_STARTED`, `TASK_COMPLETED`, `TASK_FAILED`
- `AGENT_SPAWNED`, `AGENT_TERMINATED`
- `GATE_CREATED`, `GATE_RESOLVED`
- `BUDGET_APPLIED`, `BUDGET_EXCEEDED`

**GateResolution:** `approved`, `rejected`, `edited`

**BoardSection:** `post`, `question`, `decision`, `announcement`

**SpeechAct:** `inform`, `request`, `propose`

**MessagePriority:** `low`, `normal`, `high`

**BacklogTask actions (PUT):** `claim`, `start`, `complete`, `cancel`

**Workspace control actions:** `pause`, `resume`, `complete`
