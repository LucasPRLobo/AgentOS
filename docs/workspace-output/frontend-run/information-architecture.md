# AgentOS Web Frontend — Information Architecture & User Flows

## 1. Design Principles

- **Non-technical first**: No jargon. "Tasks" not "backlog items." "Team chat" not "coordinator." "Messages" not "DMs."
- **Agent status always visible**: Every screen shows a persistent sidebar with agent health at a glance.
- **One workspace at a time, easy switching**: Workspace switcher is always accessible but never intrusive.
- **Progressive disclosure**: Show summary first, details on demand.
- **Real-time by default**: WebSocket updates flow in without page refresh.

---

## 2. Page Hierarchy

```
/                           → Workspace Selector (landing page)
/workspace/:id              → Workspace Shell (layout with sidebar + main area)
  /workspace/:id/chat       → Team Chat (coordinator conversation) [DEFAULT]
  /workspace/:id/board      → Board (announcements, decisions, questions)
  /workspace/:id/tasks      → Task List (backlog with status pipeline)
  /workspace/:id/tasks/:tid → Task Detail (spec, assignment, review, output)
  /workspace/:id/agents/:aid→ Agent Conversation (DM thread with one agent)
```

### Landing: Workspace Selector (`/`)

| Element | Description |
|---------|-------------|
| Workspace cards | Each card shows: name, goal (truncated), agent count, status (active/paused/done), budget usage bar |
| "New Workspace" card | Opens creation flow |
| Recent activity badge | Shows unread count per workspace |

### Workspace Shell (persistent layout)

```
┌─────────────────────────────────────────────────────────┐
│ [Logo] Workspace Name          [Budget] [Pause] [⚙]    │  ← Top bar
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ Sidebar  │              Main Content Area               │
│          │                                              │
│ - Agents │   (changes based on selected tab/page)       │
│ - Status │                                              │
│          │                                              │
├──────────┴──────────────────────────────────────────────┤
│ [Team Chat] [Board] [Tasks]              Activity strip │  ← Bottom nav
└─────────────────────────────────────────────────────────┘
```

---

## 3. Navigation Model

### Primary Navigation: Bottom Tab Bar

Three main tabs, always visible at the bottom of the workspace shell:

| Tab | Icon | Label | Maps to TUI |
|-----|------|-------|-------------|
| 💬 | chat bubble | **Team Chat** | F1 Home (coordinator) |
| 📋 | clipboard | **Board** | F3 Board |
| ✅ | checklist | **Tasks** | F4 Tasks |

**Why bottom tabs (not sidebar tabs)?**
- Sidebar is reserved for the always-visible agent roster
- Bottom tabs match mobile mental models — accessible for non-technical users
- Clean separation: sidebar = "who", bottom tabs = "what"

### Secondary Navigation: Agent Sidebar → Click to DM

Clicking an agent in the sidebar opens their conversation thread in the main area (replaces F2 + arrow cycling from TUI). The bottom tab highlights none — it's contextual navigation.

### Tertiary: Workspace Switcher

- Accessible via the workspace name in the top bar (click to open dropdown/drawer)
- Shows all workspaces with quick status
- "New Workspace" option always at bottom

---

## 4. Sidebar: Agent Roster (Always Visible)

The sidebar is the primary differentiator from a generic chat app. It answers: "What is my team doing right now?"

```
┌──────────────┐
│ TEAM (4)     │
├──────────────┤
│ 🟢 researcher│ ← Green dot = active
│   Analyzing  │ ← Current activity (1 line)
│   competitor │
│   dashboards │
├──────────────┤
│ 🟢 designer  │
│   Reviewing  │
│   components │
├──────────────┤
│ ⏸ architect  │ ← Grey = waiting/blocked
│   Waiting on │
│   research   │
├──────────────┤
│ 👤 You       │ ← Human participant
│   Manager    │
└──────────────┘
```

**Status indicators:**
| Icon | Meaning |
|------|---------|
| 🟢 | Active — working on a task |
| 🟡 | Needs attention — waiting for your input (gate/question) |
| ⏸ | Waiting — blocked on dependencies |
| ⚪ | Idle — no assigned task |
| 🔴 | Error — task failed or budget exceeded |

Clicking an agent → opens their DM conversation in the main area.

---

## 5. User Flows

### 5.1 Creating a New Workspace

```
[Workspace Selector] 
    │
    ├─ Click "New Workspace" card
    │
    ▼
[New Workspace Dialog — Step 1: Describe]
    │  "What would you like your team to work on?"
    │  Free-text input area (like starting a chat)
    │  Optional: attach files, paste a URL
    │
    ├─ User types project description
    │
    ▼
[Coordinator responds in-dialog]
    │  Coordinator (AI) asks clarifying questions
    │  May explore codebase / web in background
    │  Shows activity indicators: "Reading package.json..."
    │
    ├─ Back-and-forth conversation (1-3 rounds)
    │
    ▼
[Coordinator proposes team]
    │  Shows structured card:
    │    - Project name & goal
    │    - Proposed agents (name, role, what they'll do)
    │    - Suggested budget ($X.XX)
    │    - "Approve" / "Adjust" buttons
    │
    ├─ User clicks "Approve"
    │
    ▼
[Workspace Created — redirects to /workspace/:id/chat]
    │  Sidebar populates with agents
    │  Agents begin working
    │  Chat shows: "Team is set up! Here's what's happening..."
```

**Non-technical optimizations:**
- No YAML editing. Pure conversational setup.
- Budget shown as dollar amount, not tokens.
- Agent roles described in plain language ("Researches competitors", not "ui-researcher specialization").

---

### 5.2 Switching Workspaces

```
[Any workspace page]
    │
    ├─ Click workspace name in top bar
    │
    ▼
[Workspace Dropdown]
    │  Shows list of workspaces:
    │    ● Active Workspace Name (current)
    │    ○ Other Workspace — 2 agents working, 3 unread
    │    ○ Completed Project — Done ✓
    │    ─────────────
    │    + New Workspace
    │
    ├─ Click a workspace
    │
    ▼
[Navigate to /workspace/:id/chat]
    │  Context switches entirely
    │  Sidebar updates with that workspace's agents
```

---

### 5.3 Viewing & Posting to the Board

```
[Workspace Shell → Board tab]
    │
    ▼
[Board View]
    │  Sections displayed as collapsible groups:
    │
    │  📌 PINNED
    │    "Team set up. 3 tasks created..." — coordinator, 2h ago
    │
    │  📢 ANNOUNCEMENTS
    │    (system-level messages)
    │
    │  💬 POSTS
    │    "Found interesting pattern in Linear's..." — researcher, 1h ago
    │    "Component gap analysis complete" — designer, 30m ago
    │
    │  ❓ QUESTIONS (badge: 1 open)
    │    "Should we prioritize mobile?" — architect [Resolve]
    │
    │  📋 DECISIONS
    │    "Using bottom-tab navigation" — coordinator ✓
    │
    ├─ Compose area at bottom:
    │  [Post type: General / Question / Decision ▾]
    │  [Type your message...]
    │  [Post]
    │
    ├─ User types message and clicks Post
    │
    ▼
[Post appears in board, real-time for all agents]
```

**Key UX decisions:**
- Board sections map to `BoardSection` enum but use friendly labels
- Questions section has a badge count for unresolved items
- Posts show relative timestamps ("2h ago")
- Pinned posts stay at top across all sections

---

### 5.4 Managing Tasks

```
[Workspace Shell → Tasks tab]
    │
    ▼
[Task Pipeline View]
    │  Kanban-style columns OR list with status groups:
    │
    │  TO DO (2)          IN PROGRESS (1)       DONE (1)
    │  ┌──────────┐      ┌──────────────┐      ┌──────────┐
    │  │ Design   │      │ Research UX  │      │ Audit    │
    │  │ component│      │ patterns     │      │ existing │
    │  │ arch.    │      │              │      │ frontend │
    │  │          │      │ 🟢 researcher│      │          │
    │  │ ⏸ blocked│      │ 45min        │      │ ✓ designer│
    │  │ waiting  │      └──────────────┘      └──────────┘
    │  │ on 2     │
    │  └──────────┘
    │  ┌──────────┐
    │  │ Write    │
    │  │ tests    │
    │  │          │
    │  │ ⚪ open  │
    │  └──────────┘
    │
    ├─ Click a task card
    │
    ▼
[Task Detail Panel (slide-over or inline expand)]
    │
    │  Title: Research UX patterns
    │  Status: In Progress ──────●────── [progress indicator]
    │  Assigned to: 🟢 researcher
    │  Priority: High
    │  
    │  Description:
    │    Research Linear, Asana, Notion UX patterns for dashboards.
    │
    │  Spec: (if specifying phase completed)
    │    Approach: ...
    │    Expected output: ...
    │
    │  Dependencies:
    │    None
    │
    │  Blocks:
    │    → Design component architecture
    │
    │  Output: (when completed)
    │    [View output files]
    │
    │  Actions:
    │    [Reassign] [Change Priority] [Cancel]
```

**Status mapping for non-technical users:**

| Internal Status | Displayed As | Column |
|----------------|-------------|--------|
| proposed, specifying, open | **To Do** | To Do |
| claimed, in_progress | **In Progress** | In Progress |
| completed, in_review | **In Review** | In Review |
| revision_needed | **Needs Changes** | In Progress |
| done | **Done** | Done |
| blocked | **Blocked** (with reason) | To Do (flagged) |
| cancelled | **Cancelled** | Hidden (filter to show) |

---

### 5.5 Sending Messages to Agents (DMs)

```
[Sidebar → Click on agent "researcher"]
    │
    ▼
[Agent Conversation View]
    │  Main area becomes a chat thread:
    │
    │  Header: "researcher — Researching UX patterns"
    │          [Status: 🟢 Active] [Current task: Research UX patterns]
    │
    │  Chat:
    │    researcher: I've started looking at Linear's kanban...
    │    researcher: Found some interesting patterns with...
    │    You: Focus on how they handle real-time updates
    │    researcher: Good point. I'll prioritize that aspect.
    │
    │  [Type a message...]  [Send]
    │
    │  Bottom tabs still visible — click any tab to return
    │  Agent stays highlighted in sidebar to show active conversation
```

**UX details:**
- Agent's current task shown in the header for context
- Messages from the human are styled as "You" (not "human")
- System messages (task assignments, status changes) appear inline but dimmed
- Unread message badge on agent in sidebar when new messages arrive

---

### 5.6 Using Team Chat (Coordinator)

```
[Workspace Shell → Team Chat tab (default)]
    │
    ▼
[Team Chat View]
    │  Header: "Team Chat"
    │  Subtitle: "Talk to your team coordinator"
    │
    │  Chat history:
    │    coordinator: Team is set up! Here's the plan...
    │    coordinator: Research and audit running in parallel.
    │    You: What aspects should we prioritize?
    │    coordinator: Good question. I'd suggest we focus on...
    │    
    │    [Activity indicators inline:]
    │    ── researcher started "Research UX patterns" ──
    │    ── designer completed "Audit existing frontend" ──
    │
    │  [Type a message or command...]  [Send]
    │
    │  Supported actions (via natural language, no slash commands needed):
    │    "Pause the workspace" → confirms, then pauses
    │    "Add a task to research accessibility" → creates task
    │    "What's the budget usage?" → shows budget summary
```

**Key difference from TUI:**
- No slash commands required. Natural language works.
- Slash commands still work as shortcuts for power users (auto-complete menu appears on `/`)
- Activity events (agent started task, completed task) appear inline in the chat as system messages, replacing the TUI's separate "activity strip"

---

## 6. Responsive Behavior

| Breakpoint | Layout |
|-----------|--------|
| Desktop (>1024px) | Sidebar (280px) + Main area, bottom tab bar |
| Tablet (768-1024px) | Collapsible sidebar (toggle icon), bottom tab bar |
| Mobile (<768px) | Sidebar becomes a sheet (swipe from left), bottom tab bar, full-width main area |

---

## 7. Real-Time Update Strategy

All views subscribe to the workspace WebSocket for live updates:

| Event | UI Update |
|-------|-----------|
| Agent status change | Sidebar agent indicator + activity text updates |
| New board post | Board view appends post, badge increments on tab |
| Task status change | Task card moves columns, sidebar activity updates |
| New DM from agent | Badge on agent in sidebar, message appends if viewing that conversation |
| Budget update | Top bar budget indicator updates |
| Workspace paused/resumed | Top bar status changes, agents show paused state |

---

## 8. Terminology Translation (TUI → Web)

| TUI Concept | Web Frontend Label | Why |
|-------------|-------------------|-----|
| Coordinator chat / Home | **Team Chat** | "Coordinator" is jargon; users chat with their team |
| Agent DMs | **Messages** (per agent) | Clicking agent in sidebar is intuitive |
| Board sections | **Board** with grouped sections | Same concept, better visual grouping |
| Backlog / Tasks view | **Tasks** | "Backlog" is Agile jargon |
| `/msg agent-name` | Click agent → type message | Direct manipulation > commands |
| `/board`, `/tasks` | Click tab | Visual navigation > text commands |
| `/claim`, `/task` | Button actions on task cards | Discoverable UI > memorized commands |
| `/pause`, `/resume` | Top bar toggle button | Always visible, one click |
| F1-F4 keybindings | Bottom tabs + sidebar clicks | Mouse-first, keyboard shortcuts available |
| Activity strip | Inline in Team Chat | Context where it matters |
| `speech_act` types | Post type selector (General/Question/Decision) | Users don't need to know FIPA ACL |

---

## 9. Keyboard Shortcuts (Power Users)

For users who prefer keyboard navigation (preserved from TUI):

| Shortcut | Action |
|----------|--------|
| `1` / `2` / `3` | Switch to Team Chat / Board / Tasks |
| `↑` / `↓` | Navigate agent list in sidebar |
| `Enter` | Open selected agent's conversation |
| `Esc` | Return to current tab from agent conversation |
| `/` | Focus input, show command menu |
| `Ctrl+P` | Pause/Resume workspace |
| `Ctrl+K` | Command palette (search anything) |

---

## 10. Information Density Levels

Users should be able to control how much they see:

| Level | What's Shown | For Whom |
|-------|-------------|----------|
| **Minimal** | Agent names + status dots, task counts, chat | Non-technical managers who want oversight |
| **Standard** (default) | Above + agent activity text, task details, board sections | Active workspace managers |
| **Detailed** | Above + token usage, dependency graph, event log | Technical users debugging agent behavior |

Toggle via settings gear (⚙) in top bar.
