# Technical Architecture Review

**Reviewer:** lucas  
**Document:** `api-integration-plan.md`  
**Author:** architect  
**Date:** 2026-04-02  

---

## Overall Assessment: CONDITIONAL APPROVAL

The architecture document is thorough, well-structured, and demonstrates strong frontend engineering judgment. The WebSocket strategy, optimistic update patterns, error handling, and polling fallback are all production-grade designs. However, there are **critical alignment issues with the existing codebase** that must be resolved before implementation begins.

---

## Critical Issues (Must Fix)

### 1. Wrong Backend — Document targets v0, but the real backend is v1

The document maps endpoints to `agentplatform/server.py` (the v0 platform server) and references `/api/sessions/{id}/...` URL patterns. **The actual dashboard backend lives at `agentos/dashboard/`** with a completely different architecture:

- **Actual REST routes:** `/api/workspaces/{workspace_id}/board`, `/api/workspaces/{workspace_id}/backlog`, etc. (see `agentos/dashboard/workspace_api.py`)
- **Actual WebSocket:** `/ws/workspace/{workspace_id}` (see `agentos/dashboard/app.py:403`)
- **Actual data source:** In-memory `WorkspaceRuntime` instances, NOT SQLite event log for workspace data

The entire endpoint map (Section 1) needs to be rewritten against the actual `workspace_api.py` routes. The "New Endpoints Required" table (Section 1.2) is misleading — **most of these endpoints already exist** in the current codebase.

**Existing endpoints in `workspace_api.py`:**
| What the doc says is "new" | Already exists at |
|---|---|
| Board — read | `GET /api/workspaces/{id}/board` |
| Board — post | `POST /api/workspaces/{id}/board` |
| Backlog — read | `GET /api/workspaces/{id}/backlog` |
| Backlog — create | `POST /api/workspaces/{id}/backlog` |
| Backlog — update | `PUT /api/workspaces/{id}/backlog/{task_id}` |
| Messages — list | `GET /api/workspaces/{id}/messages` |
| Messages — send | `POST /api/workspaces/{id}/messages` |
| Team — status | `GET /api/workspaces/{id}/team` |
| Control | `POST /api/workspaces/{id}/control` |

### 2. Type Definitions Don't Match Backend Schemas

The TypeScript interfaces in Section 1.3 were designed from scratch rather than derived from the actual Pydantic models. For example:

- `BacklogItem` in the doc uses `status: 'todo' | 'in_progress' | 'review' | 'done' | 'blocked'` — the actual `BacklogTask` schema in `agentos/workspace/schemas.py` likely has different status values and field names (e.g., `suggested_for` instead of `assignee`, action-based updates via `claim`/`complete`/`start`/`cancel` instead of direct status patching)
- `Message` in the doc has `to: string | null` — the actual `DirectMessage` schema has `sender_type`, `sender_id`, `recipient_type`, `recipient_id`, `workflow_id`, etc.
- `BoardPost` in the doc has `section: 'post' | 'question' | 'decision'` — the actual uses `BoardSection` enum and `BoardPost` with `author_type`, `author_id`, `pinned`, etc.

**Action required:** Generate TypeScript types directly from the backend Pydantic models (or manually align them).

### 3. WebSocket Protocol Mismatch

The document proposes extending the v0 `EventStreamClient` pattern (event-type-based dispatch via `EventResponse`). The actual workspace WebSocket in `workspace_api.py:316-395` uses a **different protocol**:

- Sends `{"type": "snapshot", "data": {...}}` on connect (already implemented!)
- Sends `{"type": "board_post", "data": ...}`, `{"type": "backlog_update", "data": ...}`, `{"type": "message", "data": ...}`, `{"type": "agent_status", "data": ...}` incrementally
- Uses polling-based change detection on the server side (checks board version, backlog count, message count every 500ms)
- Does NOT use the `EventType` enum or `EventResponse` schema

The `LiveWorkspaceClient` (Section 7) should be built on top of this actual protocol, not the v0 event stream protocol.

---

## Minor Issues (Should Fix)

### 4. Backlog Update API is Action-Based, Not Patch-Based

The doc proposes `PUT /api/sessions/{id}/backlog/{item_id}` with a `Partial<BacklogItem>` body. The actual API uses an **action-based pattern**: `{"action": "claim", "participant": "..."}`, `{"action": "complete", "summary": "..."}`, `{"action": "start"}`, `{"action": "cancel", "reason": "..."}`. The Kanban drag-and-drop UI needs to map column transitions to these actions, not send raw status patches.

### 5. Deduplication Strategy (Section 4.3)

The content-matching deduplication (`m.content === msg.content && m.from === msg.from`) is fragile. The doc itself acknowledges this and suggests a correlation ID approach. **Use the correlation ID approach from the start** — the server already returns the message object from POST, so we have the server ID immediately.

### 6. Implementation Priority Ordering (Section 10)

Phase 6 (backend changes) is listed last, but as noted above, **most backend work is already done**. The real Phase 1 should be:
1. Audit existing backend endpoints and generate accurate TypeScript types
2. Build the `LiveWorkspaceClient` against the actual WS protocol
3. Build `useLiveWorkspace` hook
4. Optimistic updates
5. Polling fallback

### 7. Missing: Thread Support

The backend has `GET /api/workspaces/{id}/messages/{thread_id}` for thread retrieval, but the architecture document doesn't mention threading in the chat interface. The UX research likely identified threading as important — this should be addressed.

### 8. Missing: Cost Tracking Gaps

The current `get_cost` endpoint in `workspace_api.py` returns hardcoded zeros (`total_usd: 0.0`). The architecture should note this gap and propose how real cost data will be surfaced (likely needs backend work to wire up budget tracking from the workspace runtime).

---

## What's Good (Keep As-Is)

- **Section 2.3-2.4 (Connection lifecycle + reconnection):** Exponential backoff with jitter, state machine transitions, and `Snapshot`-based resync are all solid. Adopt this pattern even though the WS protocol details differ.
- **Section 3 (Error handling):** The per-panel error boundary structure and loading state machine are well-designed. The 5-second snapshot timeout with REST fallback is a pragmatic choice.
- **Section 4 (Optimistic updates):** The generic `optimisticMutation` pattern and mutation-specific behavior table are production-ready.
- **Section 5 (Polling fallback):** The `PollingManager` class and WS→polling transition logic are clean.
- **Section 9 (Data flow diagram):** Accurate at the conceptual level.

---

## Recommendation

**Approve with required revisions.** The architecture is sound in its patterns and strategies, but it was designed against the wrong backend. Before implementation:

1. Re-map all endpoints to `agentos/dashboard/workspace_api.py` routes
2. Derive TypeScript types from actual Pydantic schemas
3. Rewrite `LiveWorkspaceClient` against the actual `/ws/workspace/{id}` protocol
4. Update the backlog mutation API to use the action-based pattern
5. Add threading support to the chat design
6. Note the cost tracking gap as a backend dependency

The reconnection logic, error handling, optimistic updates, and polling fallback sections can be kept largely as-is — they're pattern-level designs that apply regardless of the specific endpoint URLs.
