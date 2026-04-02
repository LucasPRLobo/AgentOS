# AgentOS Dashboard Frontend — Implementation Plan

**Date:** March 2026
**Status:** Planning
**Branch:** `feature/agent-comunitaion`

---

## Design Direction: "Operations Theater"

The AgentOS dashboard is a **living collaboration environment** — not a static monitoring tool. It shows a team of humans and AI agents working together in real-time. The design language is **dark, information-dense, precision-engineered** — think mission control meets Linear meets a modern trading desk.

### Aesthetic Principles

- **Dark theme only** — deep charcoal base (#08090e), reduces eye strain for sustained use, makes status colors vivid
- **Typography**: "Commit Mono" for data/code/labels, "Instrument Sans" for body text and headings — distinctive, not generic. Loaded from Google Fonts.
- **Color system**: Emerald (#10b981) for active/success, Amber (#f59e0b) for warnings/attention, Rose (#f43f5e) for errors/critical, Sky (#38bdf8) for info/messages, Violet (#8b5cf6) for coordinator actions. All against dark backgrounds for maximum contrast.
- **Layout**: Fixed three-panel — left sidebar (280px), center main area (fluid), right panel (360px collapsible). No page-level scrolling — panels scroll independently.
- **Motion**: Subtle pulse on active agents, smooth slide for new board posts and messages, kanban card transitions. CSS transitions preferred; no heavy animation library.
- **Density**: High information density with clear visual hierarchy. Small font sizes (11-13px body), compact spacing. Professional users prefer density over whitespace.
- **Atmosphere**: Subtle noise texture overlay, faint grid lines in the board area, soft glow on active elements. The dashboard should feel *alive*.

### What Makes It Unforgettable

The **board as a living feed** — the center of the screen shows board posts appearing in real-time as agents work, with smooth animations. You see agents thinking, discovering, posting findings, asking questions. It feels like watching a team collaborate through a glass wall.

---

## Current State

### What Exists (old DAG-focused dashboard)

| Component | Status | Keep/Replace/Modify |
|---|---|---|
| Layout.tsx | Basic header + content | **Replace** — new three-panel layout |
| DashboardPage | Workflow list | **Modify** — becomes workspace list |
| MonitorPage | DAG + timeline + logs | **Replace** — becomes workspace view |
| BuilderPage | Visual workflow builder | **Keep** (modify later) |
| ComparePage | Workflow comparison | **Keep** (low priority) |
| SettingsPage | Settings | **Keep** |
| MarketplacePage | Marketplace | **Keep** |
| DagVisualization | DAG graph | **Remove** from workspace view |
| GanttView | Timeline | **Remove** from workspace view |
| ActivityFeed | Tool call feed | **Modify** — integrate into board feed |
| TaskListPanel | Task states | **Replace** — becomes kanban backlog |
| AgentPanel | Agent info | **Modify** — becomes team roster |
| GatePanel | Gate approval | **Modify** — integrate into chat |
| CostChart | Cost display | **Modify** — integrate into sidebar |
| LogTable | Event log | **Keep** as secondary tab |
| dashboard.css | 877 lines | **Replace** — new design system |
| global.css | 800 lines | **Modify** — keep utilities, update tokens |
| API client | 16 endpoints | **Extend** — add workspace endpoints |
| Types | DAG-focused | **Extend** — add workspace types |

### What's Missing

| Feature | Priority | Description |
|---|---|---|
| **Workspace page** | P0 | The core three-panel view: board + backlog + chat |
| **Board feed** | P0 | Real-time board posts (announcements, findings, decisions, alerts) |
| **Kanban backlog** | P0 | Tasks flowing through columns (open → claimed → in-progress → review → done) |
| **Chat panel** | P0 | Send/receive messages to agents and team |
| **Team roster** | P0 | Agent states with live indicators (active, idle, dormant) |
| **Budget bar** | P1 | Compact budget display in sidebar |
| **Workspace creation** | P1 | Create from YAML or conversational |
| **Workspace API routes** | P0 | Backend endpoints for board, backlog, messaging |
| **WebSocket for workspace** | P0 | Real-time board + backlog + message updates |

---

## Architecture

### Page Structure

```
/                       → WorkspaceListPage (list of workspaces)
/workspace/:id          → WorkspacePage (the main three-panel view)
/workspace/:id/logs     → WorkspaceLogsPage (full event log)
/builder                → BuilderPage (existing, modified later)
/settings               → SettingsPage (existing)
```

### WorkspacePage Layout (the core view)

```
┌──────────────────────────────────────────────────────────────┐
│  Header: workspace name, status badge, budget bar, actions   │
├────────────┬─────────────────────────────────┬───────────────┤
│            │                                 │               │
│  Sidebar   │         Main Panel              │  Right Panel  │
│  (280px)   │         (fluid)                 │  (360px)      │
│            │                                 │               │
│  Team      │  Tab: Board | Backlog | Files   │  Chat         │
│  roster    │                                 │  messages     │
│            │  Board tab:                     │               │
│  Agent 1   │    Live feed of board posts     │  Thread view  │
│  ● active  │    Pinned announcements         │               │
│            │    Findings, decisions           │  Message      │
│  Agent 2   │    Questions, alerts            │  input        │
│  ○ idle    │                                 │               │
│            │  Backlog tab:                   │               │
│  Human     │    Kanban columns               │               │
│  ◉ online  │    Open → Claimed → Active      │               │
│            │    → Review → Done              │               │
│  Budget    │                                 │               │
│  ████░░    │  Files tab:                    │               │
│  $3.20/$8  │    Workspace file browser       │               │
│            │                                 │               │
├────────────┴─────────────────────────────────┴───────────────┤
│  Status bar: event count, last activity, connection status   │
└──────────────────────────────────────────────────────────────┘
```

### Component Tree

```
App
├── WorkspaceListPage
│   ├── WorkspaceCard (per workspace)
│   └── CreateWorkspaceButton
│
├── WorkspacePage
│   ├── WorkspaceHeader
│   │   ├── WorkspaceName + StatusBadge
│   │   ├── BudgetBar (compact)
│   │   └── ActionButtons (pause, complete, settings)
│   │
│   ├── Sidebar (left)
│   │   ├── TeamRoster
│   │   │   └── AgentCard (per agent, shows state + pulse)
│   │   ├── BudgetPanel
│   │   │   ├── TotalBudget
│   │   │   └── PerAgentBreakdown
│   │   └── WorkspaceInfo (goal, criteria, mode)
│   │
│   ├── MainPanel (center, tabbed)
│   │   ├── BoardFeed (default tab)
│   │   │   ├── PinnedSection (announcements)
│   │   │   ├── BoardPostList (real-time feed)
│   │   │   │   └── BoardPost (per post — finding, decision, question, alert)
│   │   │   └── PostComposer (human can post to board)
│   │   │
│   │   ├── KanbanBacklog (tab)
│   │   │   ├── KanbanColumn (per status: open, claimed, active, review, done)
│   │   │   │   └── TaskCard (per task, draggable for claim)
│   │   │   └── AddTaskButton
│   │   │
│   │   └── FileBrowser (tab)
│   │       └── FileList (workspace files with preview)
│   │
│   ├── RightPanel (chat, collapsible)
│   │   ├── ChatHeader (recipient selector)
│   │   ├── MessageList
│   │   │   └── ChatMessage (per message, shows speech act)
│   │   └── MessageInput (with speech act selector)
│   │
│   └── StatusBar (bottom)
│       ├── EventCount
│       ├── LastActivity
│       └── ConnectionStatus (WebSocket indicator)
│
└── Shared
    ├── StatusBadge (active/paused/completed/idle)
    ├── AgentAvatar (icon + status dot)
    ├── SpeechActBadge (inform/request/propose/directive)
    ├── PriorityBadge (low/normal/high/critical)
    └── RelativeTime (2m ago, 1h ago)
```

---

## Task-by-Task Implementation Plan

### Phase F1: Foundation — Design System + Types + API

---

#### Task F1.1 — New Design System (CSS)

**File:** `src/styles/workspace.css` (new, replaces dashboard.css as primary)

Create the complete design token system and base styles:
- CSS variables: colors, typography, spacing, borders, shadows, animations
- Font loading: Commit Mono + Instrument Sans from Google Fonts
- Base element styles: body, links, buttons, inputs, scrollbars
- Utility classes: flex helpers, text helpers, spacing
- Animations: pulse-glow, fade-in, slide-up, slide-right
- Noise texture overlay
- Three-panel layout grid
- Responsive breakpoints (collapse right panel on <1200px, sidebar on <900px)

**Estimated: ~400 lines**

---

#### Task F1.2 — TypeScript Types for Workspace

**File:** `src/types/workspace.ts` (new)

Add all workspace-specific types:
```typescript
// Board
BoardPost, BoardState, AgentStatus, BoardSection, SpeechAct

// Backlog
BacklogTask, BacklogTaskStatus

// Messaging
DirectMessage, MessagePriority, MessageThread

// Workspace
WorkspaceConfig, WorkspaceState, WorkspaceStatus, WorkspaceParticipant

// Coordinator
CoordinatorStatus, TaskPlan

// Cost
CostBreakdown, BudgetAllocation
```

**Estimated: ~150 lines**

---

#### Task F1.3 — Backend API Routes for Workspace

**File:** `agentos/dashboard/app.py` (modify) + `agentos/dashboard/workspace_api.py` (new)

New endpoints:
```
GET  /api/workspaces                      → list all workspaces
GET  /api/workspaces/:id                  → workspace state + config
GET  /api/workspaces/:id/board            → current board state
POST /api/workspaces/:id/board            → post to board (human)
GET  /api/workspaces/:id/backlog          → all backlog tasks
POST /api/workspaces/:id/backlog          → create task
PUT  /api/workspaces/:id/backlog/:taskId  → update task (claim, complete)
GET  /api/workspaces/:id/messages         → messages for participant
POST /api/workspaces/:id/messages         → send message
GET  /api/workspaces/:id/messages/:threadId → thread messages
GET  /api/workspaces/:id/team             → team roster with live states
GET  /api/workspaces/:id/cost             → cost breakdown
POST /api/workspaces/:id/control          → pause/resume/complete
```

WebSocket extension:
```
WS /ws/workspace/:id → board events, backlog changes, messages, agent status
```

**Estimated: ~300 lines backend**

---

#### Task F1.4 — API Client Extension

**File:** `src/api/client.ts` (extend) + `src/api/workspace.ts` (new)

Frontend API client for all workspace endpoints:
```typescript
// Workspace
listWorkspaces(): Promise<WorkspaceSummary[]>
getWorkspace(id: string): Promise<WorkspaceState>

// Board
getBoard(id: string): Promise<BoardState>
postToBoard(id: string, content: string, section: string): Promise<BoardPost>

// Backlog
getBacklog(id: string): Promise<BacklogTask[]>
createTask(id: string, task: CreateTaskInput): Promise<BacklogTask>
claimTask(id: string, taskId: string): Promise<void>
completeTask(id: string, taskId: string): Promise<void>

// Messages
getMessages(id: string, participant?: string): Promise<DirectMessage[]>
sendMessage(id: string, msg: SendMessageInput): Promise<DirectMessage>
getThread(id: string, threadId: string): Promise<DirectMessage[]>

// Team + Cost
getTeam(id: string): Promise<AgentStatus[]>
getCost(id: string): Promise<CostBreakdown>

// Control
pauseWorkspace(id: string): Promise<void>
resumeWorkspace(id: string): Promise<void>
completeWorkspace(id: string): Promise<void>

// WebSocket
createWorkspaceSocket(id: string, onEvent: (event) => void): WebSocket
```

**Estimated: ~200 lines**

---

#### Task F1.5 — Workspace Hook (Real-Time State)

**File:** `src/hooks/useWorkspace.ts` (new)

React hook that:
- Fetches initial workspace state (config, board, backlog, team, messages)
- Opens WebSocket for real-time updates
- Merges incoming events into local state
- Provides typed accessors for all workspace data
- Handles reconnection and error states
- Tracks connection status (connected, reconnecting, disconnected)

```typescript
function useWorkspace(workspaceId: string): {
  // State
  config: WorkspaceConfig | null
  status: WorkspaceStatus
  board: BoardState
  backlog: BacklogTask[]
  team: AgentStatus[]
  messages: DirectMessage[]
  cost: CostBreakdown
  connected: boolean
  loading: boolean

  // Actions
  postToBoard(content: string, section: string): Promise<void>
  sendMessage(to: string, content: string, speechAct: string): Promise<void>
  claimTask(taskId: string): Promise<void>
  completeTask(taskId: string): Promise<void>
  createTask(title: string, description: string): Promise<void>
  pauseWorkspace(): Promise<void>
  resumeWorkspace(): Promise<void>
}
```

**Estimated: ~250 lines**

---

### Phase F2: Core Workspace Page

---

#### Task F2.1 — App Layout + Routing

**File:** `src/App.tsx` (rewrite) + `src/components/AppLayout.tsx` (new)

- New three-panel layout component
- Updated routing with workspace routes
- Sidebar navigation: Workspaces, Builder, Settings
- Responsive collapse behavior

**Estimated: ~150 lines**

---

#### Task F2.2 — Workspace List Page

**File:** `src/pages/WorkspaceListPage.tsx` (new)

- Grid of workspace cards
- Each card shows: name, goal, status, team size, budget usage, last activity
- Create workspace button (opens YAML upload or wizard)
- Status filter (active, paused, completed)
- Empty state with getting started guide

**Estimated: ~200 lines**

---

#### Task F2.3 — Workspace Header

**File:** `src/components/workspace/WorkspaceHeader.tsx` (new)

Top bar of the workspace page:
- Workspace name (large, prominent)
- Status badge (active with pulse, paused, completed)
- Budget bar (horizontal progress with $spent/$total)
- Action buttons: pause/resume, complete, settings, logs
- Team mode indicator (locked/suggest/auto with icon)

**Estimated: ~120 lines**

---

#### Task F2.4 — Sidebar: Team Roster

**File:** `src/components/workspace/TeamRoster.tsx` (new)

Left sidebar showing all team members:
- Agent cards with: name, role, state (active/idle/dormant/suspended)
- Active agents: green pulse dot, current task shown
- Idle agents: gray dot
- Human participants: distinct icon, "online" indicator
- Click agent → opens chat in right panel
- Coordinator shown separately at top with plan status
- Compact budget per-agent (small bar under each card)

**Estimated: ~180 lines**

---

#### Task F2.5 — Sidebar: Budget Panel

**File:** `src/components/workspace/BudgetPanel.tsx` (new)

Budget display below team roster:
- Total workspace budget bar (large, color-coded: green → amber → red)
- Dollar amount ($3.20 / $8.00)
- Per-agent breakdown (small bars)
- Reserve indicator (unallocated budget)
- Budget alerts highlighted

**Estimated: ~100 lines**

---

### Phase F3: Main Panel — Board + Backlog + Files

---

#### Task F3.1 — Board Feed

**File:** `src/components/workspace/BoardFeed.tsx` (new)

The central board view — a real-time feed:
- Pinned announcements at top (highlighted, distinct style)
- Feed of posts in reverse chronological order
- Each post shows: author, timestamp, speech act badge, content
- Post types visually distinct:
  - Announcements: amber border, pinned icon
  - Findings/posts: default style
  - Decisions: green check icon
  - Questions: blue question mark, shows resolved/open state
  - Alerts: red border, warning icon
- New posts animate in (slide down from top)
- Human can compose a post (text input + section selector at bottom)

**Estimated: ~250 lines**

---

#### Task F3.2 — Board Post Component

**File:** `src/components/workspace/BoardPost.tsx` (new)

Individual board post card:
- Author avatar + name (with agent/human/system indicator)
- Timestamp (relative)
- Speech act badge (inform, request, propose, directive)
- Content (markdown rendering for code blocks, lists)
- Pin button (for announcements)
- Resolve button (for questions)
- Promote button (if from a message)
- Post actions (reply, escalate)

**Estimated: ~150 lines**

---

#### Task F3.3 — Kanban Backlog

**File:** `src/components/workspace/KanbanBacklog.tsx` (new)

Kanban board with columns:
- Columns: Open, Claimed, In Progress, In Review, Done (+ Blocked as overlay)
- Task cards show: title, assigned agent, priority badge, dependency count
- Click card → detail panel slides in from right
- Claim button on open tasks (for human)
- Add task button in Open column
- Column headers show count
- Blocked tasks shown with lock icon overlay
- Cards animate when moving between columns

**Estimated: ~250 lines**

---

#### Task F3.4 — Task Card

**File:** `src/components/workspace/TaskCard.tsx` (new)

Individual task card in the kanban:
- Title (prominent)
- Assigned agent avatar
- Priority badge (color-coded)
- Dependency indicator (lock icon + count if blocked)
- Estimated time (if set)
- Model tier indicator (haiku/sonnet/opus icon)
- Acceptance criteria count
- Click for detail expansion

**Estimated: ~120 lines**

---

#### Task F3.5 — File Browser

**File:** `src/components/workspace/FileBrowser.tsx` (new)

Simple workspace file list:
- Tree or flat list of workspace files
- File size, last modified
- Click to preview (for .md, .txt, .json)
- Preview pane with syntax highlighting (basic)
- Files produced by agents tagged with agent name

**Estimated: ~150 lines**

---

### Phase F4: Chat Panel + Messaging

---

#### Task F4.1 — Chat Panel

**File:** `src/components/workspace/ChatPanel.tsx` (new)

Right panel for messaging:
- Recipient selector at top (dropdown of all team members + "Board")
- Message list (scrollable, newest at bottom)
- Messages grouped by thread
- Each message shows: sender, timestamp, speech act, content
- Directive messages highlighted (amber background)
- Request messages show "response expected" indicator
- Auto-scroll on new messages
- Unread badge per conversation

**Estimated: ~200 lines**

---

#### Task F4.2 — Chat Message Component

**File:** `src/components/workspace/ChatMessage.tsx` (new)

Individual message in the chat:
- Sender avatar + name
- Speech act badge
- Priority indicator (for high/critical)
- Message content
- Timestamp (relative)
- Reply button (starts thread)
- Thread indicator (shows thread count if part of a thread)

**Estimated: ~100 lines**

---

#### Task F4.3 — Message Input

**File:** `src/components/workspace/MessageInput.tsx` (new)

Compose area at bottom of chat panel:
- Text input (multiline, auto-expand)
- Speech act selector (dropdown: inform, request, propose, directive)
- Priority selector (default: normal, option for high)
- Send button
- Keyboard shortcut: Enter to send, Shift+Enter for newline
- Attachment support (future, stub)

**Estimated: ~120 lines**

---

### Phase F5: Shared Components + Polish

---

#### Task F5.1 — Status Components

**File:** `src/components/shared/StatusBadge.tsx` (new)

Reusable status indicators:
- WorkspaceStatusBadge (active/paused/completed)
- AgentStatusDot (active with pulse, idle, dormant, suspended)
- TaskStatusBadge (open/claimed/in-progress/review/done/blocked)
- SpeechActBadge (inform/request/propose/directive/alert)
- PriorityBadge (low/normal/high/critical)
- ConnectionIndicator (connected/reconnecting/disconnected)

**Estimated: ~150 lines**

---

#### Task F5.2 — Agent Avatar

**File:** `src/components/shared/AgentAvatar.tsx` (new)

Distinctive agent/human avatars:
- Agent: circuit-board style icon with tier indicator
- Human: standard user icon
- System/coordinator: star/command icon
- Color-coded border matching agent state
- Size variants (sm, md, lg)

**Estimated: ~80 lines**

---

#### Task F5.3 — Relative Time

**File:** `src/utils/time.ts` (new)

Time formatting utilities:
- `formatRelative(isoString)` → "2m ago", "1h ago", "yesterday"
- `formatDuration(seconds)` → "2m 30s", "1h 15m"
- `formatCost(usd)` → "$3.20", "$0.05"
- Auto-updating (re-render every 30s for "ago" times)

**Estimated: ~60 lines**

---

#### Task F5.4 — Status Bar

**File:** `src/components/workspace/StatusBar.tsx` (new)

Bottom bar of workspace page:
- Total events count
- Last activity timestamp
- WebSocket connection status (green dot = connected)
- Active agent count
- Keyboard shortcut hints

**Estimated: ~80 lines**

---

#### Task F5.5 — Create Workspace Modal

**File:** `src/components/workspace/CreateWorkspaceModal.tsx` (new)

Modal for creating a new workspace:
- Tab 1: Upload YAML (drag-and-drop or file picker)
- Tab 2: Quick create (name, goal, team size → auto-generates config)
- Preview of parsed config before creation
- Validation feedback

**Estimated: ~200 lines**

---

### Phase F6: Integration + Real-Time

---

#### Task F6.1 — WebSocket Integration

**Modify:** `src/hooks/useWorkspace.ts`

Wire WebSocket events to update local state:
- `board.post_created` → add to board feed (with animation)
- `backlog.task_*` → update kanban (move cards between columns)
- `direct_message.sent` → add to chat (with notification)
- `workspace.team_changed` → update roster
- Agent status events → update roster dots
- Budget events → update budget bar
- Connection lost → show reconnecting indicator

**Estimated: ~150 lines**

---

#### Task F6.2 — WebSocket Backend Extension

**Modify:** `agentos/dashboard/websocket.py` + `agentos/dashboard/workspace_api.py`

Extend WebSocket to support workspace events:
- Subscribe to workspace (not just workflow)
- Stream: board posts, backlog changes, messages, agent status, budget
- Initial snapshot on subscribe
- Heartbeat/keep-alive

**Estimated: ~150 lines backend**

---

#### Task F6.3 — End-to-End Testing

Manual testing flow:
1. Start dashboard (`agentos dashboard`)
2. Create a workspace via YAML upload
3. Watch coordinator decompose goal (board updates in real-time)
4. See tasks appear on kanban
5. Watch agents claim and execute tasks
6. Send a message to an agent via chat
7. Post to the board as human
8. Watch completion detection
9. Review produced files

---

## Implementation Order + Dependencies

```
F1.1 (CSS) ──────────────┐
F1.2 (Types) ────────────┤
F1.3 (Backend API) ──────┤──→ F1.4 (API Client) ──→ F1.5 (Hook)
                          │
                          ├──→ F2.1 (Layout + Routing)
                          │       │
                          │       ├──→ F2.2 (Workspace List)
                          │       ├──→ F2.3 (Header)
                          │       ├──→ F2.4 (Team Roster)
                          │       └──→ F2.5 (Budget Panel)
                          │
                          ├──→ F3.1 (Board Feed)
                          │       └── F3.2 (Board Post)
                          ├──→ F3.3 (Kanban)
                          │       └── F3.4 (Task Card)
                          └──→ F3.5 (File Browser)

F4.1 (Chat Panel) ───────── F4.2 (Message) + F4.3 (Input)

F5.1-F5.5 (Shared) ──────── Can be built anytime, used by F2-F4

F6.1 (WS Frontend) ──────── After F1.5 + F2-F4
F6.2 (WS Backend) ───────── After F1.3
F6.3 (E2E Testing) ──────── After everything
```

**Parallel tracks:**
- Track A: F1.1 + F1.2 + F5.1-F5.4 (design system + shared components)
- Track B: F1.3 + F6.2 (backend API + WebSocket)
- Track C: F1.4 + F1.5 (frontend API + hook) — needs Track B
- Track D: F2.1-F2.5 + F3.1-F3.5 + F4.1-F4.3 (UI components) — needs Track A + C

---

## Estimated Scope

| Phase | Files | Lines (est.) | Description |
|---|---|---|---|
| **F1: Foundation** | 5 | ~1,300 | CSS + types + API routes + client + hook |
| **F2: Workspace Page** | 5 | ~750 | Layout + header + sidebar + roster + budget |
| **F3: Main Panel** | 5 | ~920 | Board feed + post + kanban + card + files |
| **F4: Chat Panel** | 3 | ~420 | Chat panel + message + input |
| **F5: Shared** | 5 | ~570 | Status badges + avatar + time + statusbar + create modal |
| **F6: Integration** | 3 | ~300 | WebSocket frontend + backend + testing |
| **Total** | **26** | **~4,260** | |

### New frontend files (19):
```
src/styles/workspace.css
src/types/workspace.ts
src/api/workspace.ts
src/hooks/useWorkspace.ts
src/components/AppLayout.tsx
src/pages/WorkspaceListPage.tsx
src/pages/WorkspacePage.tsx
src/components/workspace/WorkspaceHeader.tsx
src/components/workspace/TeamRoster.tsx
src/components/workspace/BudgetPanel.tsx
src/components/workspace/BoardFeed.tsx
src/components/workspace/BoardPost.tsx
src/components/workspace/KanbanBacklog.tsx
src/components/workspace/TaskCard.tsx
src/components/workspace/FileBrowser.tsx
src/components/workspace/ChatPanel.tsx
src/components/workspace/ChatMessage.tsx
src/components/workspace/MessageInput.tsx
src/components/workspace/StatusBar.tsx
src/components/workspace/CreateWorkspaceModal.tsx
src/components/shared/StatusBadge.tsx
src/components/shared/AgentAvatar.tsx
src/utils/time.ts
```

### Modified files:
```
src/App.tsx                              (routing update)
src/api/client.ts                        (workspace endpoints)
agentos/dashboard/app.py                 (workspace API routes)
agentos/dashboard/websocket.py           (workspace event streaming)
```

### New backend file:
```
agentos/dashboard/workspace_api.py       (workspace REST endpoints)
```
