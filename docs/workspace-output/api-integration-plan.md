# API Integration Plan & WebSocket Real-Time Strategy

Technical architecture document for the AgentOS Dashboard frontend — mapping every view/action to backend endpoints, defining the WebSocket real-time layer, and specifying error handling, optimistic updates, and polling fallback strategies.

---

## 1. Endpoint Map: Frontend Views to Backend APIs

The dashboard introduces **workspace-level** concepts (board, backlog, messages, team, cost, control) that sit atop the existing session/event infrastructure. Some endpoints already exist in `server.py`; others must be added.

### 1.1 Existing Endpoints (in `agentplatform/server.py`)

| Frontend View / Action | Method | Endpoint | Response Type | Notes |
|---|---|---|---|---|
| Session list / picker | GET | `/api/sessions` | `SessionSummary[]` | Already exists. Used for workspace overview. |
| Session detail header | GET | `/api/sessions/{id}` | `SessionDetail` | State, agents, event_count, error. |
| Start session | POST | `/api/sessions/{id}/start` | `{status}` | Transitions CREATED → RUNNING. |
| Stop session | POST | `/api/sessions/{id}/stop` | `{status}` | Graceful stop via stop_event. |
| Event log (initial load) | GET | `/api/sessions/{id}/events?offset=N` | `EventResponse[]` | Offset-based pagination. |
| Cost panel | GET | `/api/sessions/{id}/cost` | `SessionCost` | Per-model breakdown. Polled every 5s in current `SessionDashboard`. |
| Artifacts browser | GET | `/api/sessions/{id}/files` | `FileListResponse` | File listing with agent attribution. |
| File content viewer | GET | `/api/sessions/{id}/files/{path}` | `text/plain \| file` | Path-traversal protected. |
| Real-time events | WS | `/ws/sessions/{id}/events` | `EventResponse` stream | Existing `EventStreamClient` in `client.ts`. |

### 1.2 New Endpoints Required for Dashboard

These endpoints expose the workspace communication layer (currently MCP tools only) as REST APIs for the dashboard frontend.

| Frontend View / Action | Method | Endpoint | Request Body | Response Type |
|---|---|---|---|---|
| **Board — read** | GET | `/api/sessions/{id}/board` | — | `BoardState` |
| **Board — post** | POST | `/api/sessions/{id}/board` | `{content, section, speech_act}` | `BoardPost` |
| **Backlog — read** | GET | `/api/sessions/{id}/backlog` | — | `BacklogItem[]` |
| **Backlog — update item** | PUT | `/api/sessions/{id}/backlog/{item_id}` | `{status, assignee, ...}` | `BacklogItem` |
| **Backlog — create item** | POST | `/api/sessions/{id}/backlog` | `{title, description, assignee}` | `BacklogItem` |
| **Messages — list** | GET | `/api/sessions/{id}/messages?after=ts` | — | `Message[]` |
| **Messages — send** | POST | `/api/sessions/{id}/messages` | `{to, content, priority}` | `Message` |
| **Team — status** | GET | `/api/sessions/{id}/team` | — | `AgentStatus[]` |
| **Control — directive** | POST | `/api/sessions/{id}/control` | `{action, target?, params?}` | `{status}` |

### 1.3 Type Definitions for New Endpoints

```typescript
// ── Board ──────────────────────────────────────────────────────

interface BoardPost {
  id: string;
  author: string;           // agent name or "human"
  content: string;
  section: 'post' | 'question' | 'decision';
  speech_act: 'inform' | 'request' | 'propose';
  timestamp: string;
}

interface BoardState {
  announcements: string[];
  posts: BoardPost[];
  decisions: BoardPost[];
  open_questions: BoardPost[];
  alerts: string[];
}

// ── Backlog (Kanban) ───────────────────────────────────────────

type BacklogStatus = 'todo' | 'in_progress' | 'review' | 'done' | 'blocked';

interface BacklogItem {
  id: string;
  title: string;
  description: string;
  status: BacklogStatus;
  assignee: string | null;   // agent name
  priority: 'low' | 'normal' | 'high' | 'critical';
  created_at: string;
  updated_at: string;
  created_by: string;
}

// ── Messages (Chat) ────────────────────────────────────────────

interface Message {
  id: string;
  from: string;              // agent name or "human"
  to: string | null;         // null = broadcast
  content: string;
  priority: 'low' | 'normal' | 'high';
  speech_act: 'inform' | 'request' | 'propose';
  timestamp: string;
}

// ── Team Status ────────────────────────────────────────────────

type AgentActivity = 'idle' | 'working' | 'waiting' | 'blocked' | 'finished' | 'error';

interface AgentStatus {
  name: string;
  role: string;
  model: string;
  activity: AgentActivity;
  current_task: string | null;
  summary: string;           // last reported progress
  token_usage: number;
  cost_usd: number;
}

// ── Control ────────────────────────────────────────────────────

interface ControlAction {
  action: 'stop' | 'pause' | 'resume' | 'reassign' | 'directive';
  target?: string;           // agent name for targeted actions
  params?: Record<string, unknown>;
}
```

---

## 2. WebSocket Integration Strategy

### 2.1 Architecture: Unified Event Stream

The existing `EventStreamClient` in `client.ts:275-313` connects to `/ws/sessions/{id}/events` and streams `EventResponse` objects. The dashboard extends this with **derived event types** that the backend synthesizes from the underlying event log.

**Key design decision**: Rather than creating multiple WebSocket connections, we use a **single WS connection per session** that carries all event types. The backend already streams all events via `EventStreamer.stream()` (polls every 100ms). We add new `EventType` variants for dashboard-specific data.

### 2.2 New WebSocket Event Types

Add to the existing `EventType` enum in `schemas/events.py`:

| WS Event Type | Trigger | Payload Shape | Frontend State Update |
|---|---|---|---|
| `Snapshot` | On WS connect (initial state) | Full `BoardState` + `BacklogItem[]` + `AgentStatus[]` + `Message[]` | Hydrate entire workspace store |
| `BoardPost` | Agent/human posts to board | `BoardPost` | Append to `board.posts` (or `decisions`/`questions`) |
| `BacklogUpdate` | Item status change / creation | `BacklogItem` | Upsert in `backlog` array by `id` |
| `MessageNew` | Agent or human sends message | `Message` | Append to `messages` array |
| `AgentStatusChange` | Agent progress report / state change | `AgentStatus` | Replace entry in `team` by `name` |
| `CostUpdate` | After each LMCallFinished | `SessionCost` (partial) | Merge into cost state |

### 2.3 Connection Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│  useLiveWorkspace(sessionId)                                │
│                                                             │
│  1. Mount: GET /api/sessions/{id}  →  validate session      │
│  2. Open WS: /ws/sessions/{id}/events                      │
│  3. Wait for "Snapshot" event  →  hydrate all stores        │
│  4. Process incremental events  →  update stores            │
│  5. Unmount: close WS, clear stores                         │
│                                                             │
│  On WS error/close:                                         │
│    → Enter reconnection loop (see §2.4)                     │
│    → Switch to polling fallback after max retries (see §5)  │
└─────────────────────────────────────────────────────────────┘
```

### 2.4 Reconnection Strategy

Exponential backoff with jitter, capped at 30 seconds:

```typescript
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const MAX_RECONNECT_ATTEMPTS = 10;

function reconnectDelay(attempt: number): number {
  const base = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
  const jitter = Math.random() * base * 0.3;  // ±30% jitter
  return base + jitter;
}
```

**State transitions:**

```
CONNECTED ──(ws.onclose)──→ RECONNECTING
                               │
                   attempt < MAX_RECONNECT_ATTEMPTS
                               │
                  ┌─────yes────┴────no──────┐
                  ▼                          ▼
            wait(delay)                 POLLING_FALLBACK
                  │
            new WebSocket()
                  │
          ┌───success───┐
          ▼              │
      CONNECTED     ──(error)──→ increment attempt, loop
```

On successful reconnect, request a `Snapshot` event to resync state (send `{"action": "resync"}` on the WS).

### 2.5 Event-to-State Mapping (useLiveWorkspace hook)

```typescript
// Hook signature — references existing EventStreamClient pattern
function useLiveWorkspace(sessionId: string) {
  // Returns:
  return {
    // State
    session: SessionDetail | null,
    board: BoardState,
    backlog: BacklogItem[],
    messages: Message[],
    team: AgentStatus[],
    cost: SessionCost | null,
    events: EventResponse[],

    // Connection status
    connectionState: 'connecting' | 'connected' | 'reconnecting' | 'polling' | 'disconnected',

    // Mutations (see §4 for optimistic update details)
    sendMessage: (msg: Omit<Message, 'id' | 'timestamp'>) => Promise<Message>,
    postToBoard: (post: Omit<BoardPost, 'id' | 'timestamp'>) => Promise<BoardPost>,
    updateBacklogItem: (id: string, patch: Partial<BacklogItem>) => Promise<BacklogItem>,
    createBacklogItem: (item: Omit<BacklogItem, 'id' | 'created_at' | 'updated_at'>) => Promise<BacklogItem>,
    sendControl: (action: ControlAction) => Promise<void>,
  };
}
```

**Event dispatch table inside the hook:**

```typescript
function handleEvent(event: EventResponse, dispatch: Dispatch) {
  switch (event.event_type) {
    // ── Snapshot (initial hydration + resync) ──
    case 'Snapshot':
      dispatch({ type: 'HYDRATE', payload: event.payload });
      break;

    // ── Board ──
    case 'BoardPost':
      dispatch({ type: 'BOARD_POST', payload: event.payload as BoardPost });
      break;

    // ── Backlog ──
    case 'BacklogUpdate':
      dispatch({ type: 'BACKLOG_UPSERT', payload: event.payload as BacklogItem });
      break;

    // ── Messages ──
    case 'MessageNew':
    case 'AgentMessage':  // existing event type — agents communicating
      dispatch({ type: 'MESSAGE_APPEND', payload: event.payload as Message });
      break;

    // ── Team status ──
    case 'AgentStatusChange':
    case 'AgentStepStarted':
    case 'AgentStepFinished':
    case 'TaskStarted':
    case 'TaskFinished':
      dispatch({ type: 'TEAM_UPDATE', payload: deriveAgentStatus(event) });
      break;

    // ── Cost ──
    case 'LMCallFinished':
    case 'CostUpdate':
      dispatch({ type: 'COST_UPDATE', payload: event.payload });
      break;

    // ── Session lifecycle ──
    case 'SessionStarted':
    case 'SessionFinished':
      dispatch({ type: 'SESSION_STATE', payload: event.payload });
      break;

    // ── All events go to the event log ──
    default:
      break;
  }

  // Every event appends to the raw event log
  dispatch({ type: 'EVENT_APPEND', payload: event });
}
```

---

## 3. Error Handling & Loading States

### 3.1 Loading State Machine

Each data domain has its own loading state, following this pattern:

```typescript
type LoadState = 'idle' | 'loading' | 'loaded' | 'error';

interface AsyncState<T> {
  data: T;
  loadState: LoadState;
  error: string | null;
  lastUpdated: number | null;  // timestamp
}
```

**Initial load sequence:**

```
Page Mount
  ├── GET /api/sessions/{id}          → session: loading → loaded
  ├── Open WebSocket
  │     └── Wait for Snapshot event   → board, backlog, messages, team: loading → loaded
  └── GET /api/sessions/{id}/cost     → cost: loading → loaded
```

If the WebSocket connects but no Snapshot arrives within 5 seconds, fall back to parallel REST fetches:

```
Snapshot timeout (5s)
  ├── GET /api/sessions/{id}/board     → board: loaded
  ├── GET /api/sessions/{id}/backlog   → backlog: loaded
  ├── GET /api/sessions/{id}/messages  → messages: loaded
  └── GET /api/sessions/{id}/team      → team: loaded
```

### 3.2 Error Handling by Category

| Error Category | Example | UI Treatment | Recovery |
|---|---|---|---|
| **Network error** | WS disconnect, fetch timeout | Banner: "Connection lost, reconnecting..." | Auto-reconnect (§2.4) |
| **404 Session** | Session deleted/expired | Full-page error: "Session not found" | Link back to session list |
| **409 Conflict** | Stop already-stopped session | Toast: "Session already stopped" | Refresh session state |
| **422 Validation** | Invalid backlog item | Inline field errors | User corrects and retries |
| **500 Server** | Backend crash | Banner: "Server error" + retry button | Manual retry, check server |
| **WS 4004** | Session not found on WS connect | Same as 404 | Redirect to session list |

### 3.3 Error Boundary Structure

```
<WorkspaceErrorBoundary>          ← catches render errors, shows full-page fallback
  <ConnectionStatusBar />         ← shows reconnecting/polling/disconnected banner
  <DashboardLayout>
    <BoardPanel>
      <PanelErrorBoundary />      ← isolated: board error doesn't crash messages
    </BoardPanel>
    <BacklogPanel>
      <PanelErrorBoundary />
    </BacklogPanel>
    <ChatPanel>
      <PanelErrorBoundary />
    </ChatPanel>
  </DashboardLayout>
</WorkspaceErrorBoundary>
```

---

## 4. Optimistic Updates

For user-initiated mutations, apply the change to local state immediately, then confirm or roll back when the server responds.

### 4.1 Pattern

```typescript
async function optimisticMutation<T>(
  // Apply optimistic state
  applyOptimistic: () => string,  // returns temp ID
  // Server request
  serverRequest: () => Promise<T>,
  // Confirm with server response (replace temp with real data)
  confirmUpdate: (tempId: string, serverData: T) => void,
  // Rollback on failure
  rollback: (tempId: string) => void,
) {
  const tempId = applyOptimistic();
  try {
    const result = await serverRequest();
    confirmUpdate(tempId, result);
  } catch (err) {
    rollback(tempId);
    throw err;  // re-throw for UI error handling
  }
}
```

### 4.2 Mutation-Specific Behavior

| Mutation | Optimistic Behavior | Confirm | Rollback |
|---|---|---|---|
| **Send message** | Append message with `_pending: true` flag, temp ID | Replace temp ID with server ID, remove `_pending` | Remove message, show toast "Failed to send" |
| **Post to board** | Append post with `_pending: true` | Replace with server version | Remove post, show toast |
| **Create backlog item** | Add item to 'todo' column with `_pending` | Replace with server version | Remove item, show toast |
| **Update backlog item** (drag to new column) | Move item to new column immediately | Confirm position | Move back to original column, show toast |
| **Send control** (stop/pause) | Disable button, show spinner | Update session state | Re-enable button, show error toast |

### 4.3 Deduplication with WebSocket

When the server broadcasts the mutation back over the WebSocket (e.g., the message we just sent appears as a `MessageNew` event), we must not duplicate it:

```typescript
// In the event handler:
case 'MessageNew': {
  const msg = event.payload as Message;
  // Check if this is a confirmation of our optimistic message
  const existing = state.messages.find(m => m._tempId && m.content === msg.content && m.from === msg.from);
  if (existing) {
    // Replace optimistic version with server version
    dispatch({ type: 'MESSAGE_CONFIRM', tempId: existing._tempId, serverMessage: msg });
  } else {
    dispatch({ type: 'MESSAGE_APPEND', payload: msg });
  }
  break;
}
```

**Better approach**: The server response from POST returns the real `id`. Tag optimistic entries with a `_correlationId`. When the WS event arrives with a matching server ID, skip the append and just clear the pending flag.

---

## 5. Polling Fallback

When WebSocket is unavailable (after `MAX_RECONNECT_ATTEMPTS` exhausted, or in environments that block WS), degrade to REST polling.

### 5.1 Polling Intervals

| Data | Interval | Endpoint | Strategy |
|---|---|---|---|
| Session state | 3s | `GET /api/sessions/{id}` | Always poll (matches current `SessionDashboard` behavior) |
| Board | 5s | `GET /api/sessions/{id}/board` | Full replace |
| Backlog | 5s | `GET /api/sessions/{id}/backlog` | Full replace |
| Messages | 2s | `GET /api/sessions/{id}/messages?after={lastTs}` | Incremental (append new) |
| Team status | 3s | `GET /api/sessions/{id}/team` | Full replace |
| Cost | 10s | `GET /api/sessions/{id}/cost` | Full replace |
| Events | 2s | `GET /api/sessions/{id}/events?offset={lastSeq}` | Incremental (append new) |

### 5.2 Polling Manager

```typescript
class PollingManager {
  private intervals: Map<string, ReturnType<typeof setInterval>> = new Map();

  start(key: string, fn: () => Promise<void>, intervalMs: number) {
    this.stop(key);
    fn();  // immediate first fetch
    this.intervals.set(key, setInterval(fn, intervalMs));
  }

  stop(key: string) {
    const id = this.intervals.get(key);
    if (id) { clearInterval(id); this.intervals.delete(key); }
  }

  stopAll() {
    this.intervals.forEach((id) => clearInterval(id));
    this.intervals.clear();
  }
}
```

### 5.3 Transition Between WS and Polling

```typescript
// Inside useLiveWorkspace:
useEffect(() => {
  if (connectionState === 'polling') {
    polling.start('session', () => fetchSession(sessionId), 3000);
    polling.start('board', () => fetchBoard(sessionId), 5000);
    polling.start('messages', () => fetchMessages(sessionId, lastMessageTs), 2000);
    polling.start('backlog', () => fetchBacklog(sessionId), 5000);
    polling.start('team', () => fetchTeam(sessionId), 3000);
    polling.start('cost', () => fetchCost(sessionId), 10000);
    polling.start('events', () => fetchEvents(sessionId, lastEventOffset), 2000);
  } else {
    polling.stopAll();
  }

  return () => polling.stopAll();
}, [connectionState, sessionId]);
```

When a WebSocket reconnects successfully, the polling manager is stopped and the WS `Snapshot` event resyncs all state.

---

## 6. API Client Extensions

Extend the existing `client.ts` with new functions, following the established `fetchJSON` / `fetchVoid` pattern:

```typescript
// ── Board ──────────────────────────────────────────────────────
export async function getBoard(sessionId: string): Promise<BoardState> {
  return fetchJSON(`/api/sessions/${sessionId}/board`);
}

export async function postToBoard(
  sessionId: string,
  post: { content: string; section: string; speech_act: string },
): Promise<BoardPost> {
  return fetchJSON(`/api/sessions/${sessionId}/board`, {
    method: 'POST',
    body: JSON.stringify(post),
  });
}

// ── Backlog ────────────────────────────────────────────────────
export async function getBacklog(sessionId: string): Promise<BacklogItem[]> {
  return fetchJSON(`/api/sessions/${sessionId}/backlog`);
}

export async function createBacklogItem(
  sessionId: string,
  item: { title: string; description: string; assignee?: string; priority?: string },
): Promise<BacklogItem> {
  return fetchJSON(`/api/sessions/${sessionId}/backlog`, {
    method: 'POST',
    body: JSON.stringify(item),
  });
}

export async function updateBacklogItem(
  sessionId: string,
  itemId: string,
  patch: Partial<BacklogItem>,
): Promise<BacklogItem> {
  return fetchJSON(`/api/sessions/${sessionId}/backlog/${itemId}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  });
}

// ── Messages ───────────────────────────────────────────────────
export async function getMessages(
  sessionId: string,
  after?: string,
): Promise<Message[]> {
  const qs = after ? `?after=${encodeURIComponent(after)}` : '';
  return fetchJSON(`/api/sessions/${sessionId}/messages${qs}`);
}

export async function sendMessage(
  sessionId: string,
  msg: { to: string; content: string; priority?: string },
): Promise<Message> {
  return fetchJSON(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify(msg),
  });
}

// ── Team ───────────────────────────────────────────────────────
export async function getTeam(sessionId: string): Promise<AgentStatus[]> {
  return fetchJSON(`/api/sessions/${sessionId}/team`);
}

// ── Control ────────────────────────────────────────────────────
export async function sendControl(
  sessionId: string,
  action: ControlAction,
): Promise<{ status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/control`, {
    method: 'POST',
    body: JSON.stringify(action),
  });
}
```

---

## 7. Enhanced EventStreamClient

Extend the existing `EventStreamClient` (client.ts:275-313) with reconnection, connection state, and snapshot request:

```typescript
export type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'polling' | 'disconnected';

export class LiveWorkspaceClient extends EventStreamClient {
  private sessionId: string = '';
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connectionState: ConnectionState = 'disconnected';
  private onConnectionStateChange?: (state: ConnectionState) => void;

  connect(sessionId: string): void {
    this.sessionId = sessionId;
    this.reconnectAttempt = 0;
    this._setConnectionState('connecting');
    this._doConnect();
  }

  private _doConnect(): void {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(
      `${protocol}//${location.host}/ws/sessions/${this.sessionId}/events`,
    );

    ws.onopen = () => {
      this.reconnectAttempt = 0;
      this._setConnectionState('connected');
      // Request full snapshot for state hydration
      ws.send(JSON.stringify({ action: 'resync' }));
    };

    ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as EventResponse;
      this.notify(event);
    };

    ws.onclose = (ev) => {
      if (ev.code === 4004) {
        // Session not found — don't reconnect
        this._setConnectionState('disconnected');
        return;
      }
      this._scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will fire after onerror
    };

    this.ws = ws;
  }

  private _scheduleReconnect(): void {
    if (this.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      this._setConnectionState('polling');
      return;
    }

    this._setConnectionState('reconnecting');
    const delay = reconnectDelay(this.reconnectAttempt);
    this.reconnectAttempt++;

    this.reconnectTimer = setTimeout(() => this._doConnect(), delay);
  }

  private _setConnectionState(state: ConnectionState): void {
    this._connectionState = state;
    this.onConnectionStateChange?.(state);
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    super.disconnect();
    this._setConnectionState('disconnected');
  }
}
```

---

## 8. Backend Changes Required

### 8.1 New API Routes (add to `server.py`)

Seven new route handlers (board CRUD, backlog CRUD, messages, team, control) following the existing patterns in `server.py`. These read/write to a new `WorkspaceCommunication` layer that wraps the `EventLog`.

### 8.2 New Event Types (add to `schemas/events.py`)

```python
# Add to EventType enum:
SNAPSHOT = "Snapshot"
BOARD_POST = "BoardPost"
BACKLOG_UPDATE = "BacklogUpdate"
MESSAGE_NEW = "MessageNew"
AGENT_STATUS_CHANGE = "AgentStatusChange"
COST_UPDATE = "CostUpdate"
```

### 8.3 EventStreamer Enhancement

The `EventStreamer` in `event_stream.py` needs to:
1. Send a `Snapshot` event on new WS connection (aggregate current board/backlog/messages/team state)
2. Handle `{"action": "resync"}` client messages to re-send the snapshot
3. Continue streaming incremental events as today

### 8.4 WorkspaceCommunication Service

New module: `agentplatform/workspace_comms.py` — manages board state, backlog, and messages for a session. Backed by the existing `EventLog` (events are the source of truth; board/backlog state is derived by replaying relevant events).

---

## 9. Data Flow Summary

```
                    ┌─────────────────────────┐
                    │   React Dashboard App   │
                    │                         │
                    │  useLiveWorkspace()     │
                    │    ├── board state      │
                    │    ├── backlog state    │
                    │    ├── messages state   │
                    │    ├── team state       │
                    │    ├── cost state       │
                    │    └── events state     │
                    └────┬───────────┬────────┘
                         │           │
              mutations  │           │  real-time updates
              (REST)     │           │  (WebSocket / poll)
                         ▼           ▼
                    ┌─────────────────────────┐
                    │   FastAPI Server        │
                    │                         │
                    │  REST endpoints         │
                    │  WebSocket endpoint     │
                    │  EventStreamer          │
                    │  WorkspaceCommunication │
                    └────┬───────────┬────────┘
                         │           │
                         ▼           ▼
                    ┌─────────────────────────┐
                    │  EventLog (SQLite)      │
                    │  (append-only, single   │
                    │   source of truth)      │
                    └─────────────────────────┘
```

---

## 10. Implementation Priority

1. **Phase 1**: New REST endpoints (board, backlog, messages, team, control) + API client functions
2. **Phase 2**: `LiveWorkspaceClient` with reconnection logic, replacing basic `EventStreamClient`
3. **Phase 3**: `useLiveWorkspace` hook with `useReducer`-based state management
4. **Phase 4**: Optimistic updates for mutations
5. **Phase 5**: Polling fallback manager
6. **Phase 6**: Backend `WorkspaceCommunication` service + new event types + enhanced `EventStreamer`

Phases 1 and 6 can be developed in parallel (frontend client stubs + backend implementation).
