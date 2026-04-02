# AgentOS Dashboard: Layout Design & Information Architecture Spec

**Author:** designer  
**Date:** 2026-04-02  
**Status:** Draft for review  
**Inputs:** UX research reports (ux-research-dashboard-patterns.md, research_ai_agent_dashboards.md, ux-research-ai-agent-patterns.md), existing component code

---

## 1. Design Principles

These six principles (derived from the UX research) govern every decision in this spec:

1. **Oversight-first** — The human's primary job is monitoring agents and intervening when needed. Surface problems and decisions; don't bury them.
2. **Progressive disclosure** — Overview by default, detail on demand. Summary cards expand to full panels; don't show everything at once.
3. **Real-time as baseline** — Every view is live via WebSocket. No manual refresh, no polling spinners. The UI should feel like a control room, not a report.
4. **Cost is a core dimension** — Budget appears in the header, on agent cards, on task cards, and has its own detailed view. It's never hidden.
5. **Minimize context switching** — Three-panel layout keeps navigation, content, and context visible simultaneously. No full-page navigations for routine tasks.
6. **Human-readable agent actions** — Every agent state change shows a brief "why." This builds trust and supports oversight.

---

## 2. Information Architecture

### 2.1 Site Map

```
/                           WorkspaceListPage (home)
/workspace/:id              WorkspacePage (detail)
  ├─ Board tab              BoardFeed (default)
  ├─ Backlog tab            KanbanBacklog
  └─ Files tab              (placeholder, future)
/workspace/:id/settings     (future)
/builder                    BuilderPage (legacy)
/settings                   SettingsPage (legacy)
```

The application has two primary views: the **workspace list** and the **workspace detail**. There is no global sidebar navigation — the list page IS the top-level navigation. This keeps the workspace detail view maximally focused.

### 2.2 Navigation Model

**Decision: No persistent global sidebar.** Rationale:

- The workspace detail view already has a sidebar (team roster + budget). Adding a global nav sidebar would create a double-sidebar that wastes horizontal space.
- Users typically work within a single workspace for extended periods. Workspace switching is infrequent — a header breadcrumb is sufficient.
- This matches Linear's model: workspace switcher in header, not a persistent sidebar.

**Navigation flow:**

```
WorkspaceListPage  ──click card──>  WorkspacePage
                   <──breadcrumb──
```

Within WorkspacePage, navigation is tab-based (Board / Backlog / Files) in the main content area, not in the sidebar. The sidebar is reserved for team context (roster + budget).

### 2.3 Information Hierarchy (Priority Order)

| Priority | Information | Location | Always Visible? |
|----------|------------|----------|-----------------|
| P0 | Workspace status + alerts | WorkspaceHeader | Yes |
| P1 | Agent activity (who's doing what) | Sidebar TeamRoster | Yes |
| P2 | Recent board activity | Main panel (Board tab) | Default tab |
| P3 | Task progress | Main panel (Backlog tab) | On tab switch |
| P4 | Budget consumption | Header bar + Sidebar BudgetPanel | Yes (summary) |
| P5 | Chat / direct messages | Right panel ChatPanel | Yes (collapsible) |
| P6 | Detailed cost breakdown | BudgetPanel expanded | On demand |

---

## 3. View Specifications

### 3.1 Workspace List View (`WorkspaceListPage`)

**Purpose:** Landing page. Shows all workspaces with summary metrics for quick triage.

**Existing component:** `src/pages/WorkspaceListPage.tsx` — already implemented as a card grid.

#### Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [AgentOS]                    Workspaces                 [+ New Workspace] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────────┐│
│  │ Dashboard Sprint   ●│  │ API Refactor       ●│  │ Docs Update    ● ││
│  │ ACTIVE              │  │ PAUSED              │  │ COMPLETED        ││
│  │                     │  │                     │  │                  ││
│  │ Research & design   │  │ Restructuring the   │  │ Updated all API  ││
│  │ the AgentOS dash... │  │ REST API endpoin... │  │ documentation... ││
│  │                     │  │                     │  │                  ││
│  │ 👥 4  📋 5/9  💰24% │  │ 👥 3  📋 2/6  💰41% │  │ 👥 2  📋 8/8     ││
│  │ 2 min ago           │  │ 15 min ago          │  │ 1h ago           ││
│  └─────────────────────┘  └─────────────────────┘  └──────────────────┘│
│                                                                         │
│  ┌─────────────────────┐                                               │
│  │ Security Audit     ●│                                               │
│  │ ACTIVE              │                                               │
│  │ ...                 │                                               │
│  └─────────────────────┘                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Card Design

Each workspace card shows:
- **Name** (bold, 15px) + **status dot** (green=active, amber=paused, checkmark=completed)
- **Status badge** (`StatusBadge` component, already exists)
- **Goal** (truncated to 2 lines, muted text)
- **Footer metrics:** team size, tasks done/total, budget %, last active time

#### Layout Details
- **Grid:** CSS grid, `repeat(auto-fill, minmax(280px, 1fr))`, gap 16px
- **Card hover:** Subtle border highlight + pointer cursor (already in `.ws-list-card`)
- **Empty state:** Diamond icon + "No workspaces yet" + description (already implemented)
- **Responsive:** Cards reflow naturally via auto-fill grid. Single column at <600px.

#### Interaction
- Click card → navigate to `/workspace/:id`
- `+ New Workspace` button → (future: creation dialog or wizard)
- No filtering/sorting needed initially (workspaces are few). Add later if >20 workspaces becomes common.

---

### 3.2 Workspace Detail View (`WorkspacePage`)

**Purpose:** The main operational view. Where humans spend most of their time monitoring and interacting with agent teams.

**Existing component:** `src/pages/WorkspacePage.tsx` — already implements the three-panel layout.

#### Master Wireframe

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [AgentOS] │ Dashboard Sprint           ● ACTIVE   ████░░░ $12/$50 24%  │
│           │                                                [Pause][Done]│
├───────────┼──────────────────────────────────────┬──────────────────────┤
│           │  [Board]  [Backlog]  [Files]  5/9 ✓  │  MESSAGES            │
│  TEAM     │                                      │  · designer          │
│           │ ┌──────────────────────────────────┐  │                      │
│ ● desig.. │ │ architect · decision · 2m ago    │  │  ┌────────────────┐  │
│   Creati..│ │ Using React Query for server     │  │  │ architect:     │  │
│ ● archi.. │ │ state, Zustand for local UI.     │  │  │ WebSocket API  │  │
│   Design..│ │ 💬 2 replies                      │  │  │ supports per-  │  │
│ ○ resea.. │ ├──────────────────────────────────┤  │  │ workspace...   │  │
│   Analyz..│ │ ui-researcher · post · 5m ago    │  │  └────────────────┘  │
│           │ │ Completed analysis of Linear,    │  │  ┌────────────────┐  │
│           │ │ Asana, and Notion patterns.      │  │  │ You:           │  │
│  ──────── │ │ Key finding: compact cards...    │  │  │ Thanks, go     │  │
│  BUDGET   │ ├──────────────────────────────────┤  │  │ ahead with     │  │
│  $12/$50  │ │ designer · question · 8m ago     │  │  │ that approach. │  │
│  ████░ 24%│ │ Should we use tabs or a sidebar  │  │  └────────────────┘  │
│           │ │ for main content navigation?     │  │                      │
│  designer │ │ ❓ open question                  │  │                      │
│    $3.42  │ ├──────────────────────────────────┤  │                      │
│  architect│ │                                  │  │  ┌──────────────────┐│
│    $5.10  │ │           ...more posts          │  │  │ Message designer │││
│  researc..│ │                                  │  │  │ [inform▾] [Send] │││
│    $3.93  │ └──────────────────────────────────┘  │  └──────────────────┘│
│           │ ┌──────────────────────────────────┐  │                      │
│  ──────── │ │ Post to the board...       [Post]│  │                      │
│  goal...  │ │ [post▾]                          │  │                      │
│           │ └──────────────────────────────────┘  │                      │
├───────────┴──────────────────────────────────────┴──────────────────────┤
│ ● Connected │ board v14 │ 2 active agents │ 3 team members    AgentOS  │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Panel Structure

The workspace view has **four zones** arranged in a fixed layout:

| Zone | Component | Width | Visibility | Purpose |
|------|-----------|-------|------------|---------|
| **Header** | `WorkspaceHeader` | full width, 48px height | Always visible | Status, budget bar, workspace controls |
| **Left Sidebar** | `TeamRoster` + `BudgetPanel` | 220px fixed | Always visible | Team context + budget |
| **Main Content** | Tab-switched: `BoardFeed` / `KanbanBacklog` / Files | Fluid (fills remaining) | Always visible | Primary work area |
| **Right Panel** | `ChatPanel` | 280px fixed | Always visible, collapsible | Direct messaging |
| **Status Bar** | `StatusBar` | full width, 28px height | Always visible | Connection state, metadata |

#### 3.2.1 Header (`WorkspaceHeader`)

**Existing component:** Already implemented with status badge, budget bar, and Pause/Resume/Complete buttons.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [AgentOS] │ {workspace name}  [●STATUS]    ████░░░ $X/$Y  Z%   [Pause]│
└─────────────────────────────────────────────────────────────────────────┘
```

**Layout:** Flexbox row, `align-items: center`, 48px height.
- Left: AgentOS brand + separator + workspace name + status badge
- Center/Right: Budget progress bar (180px) with cost labels
- Far Right: Action buttons (Pause/Resume/Complete)

**Additions needed:**
- **Breadcrumb back-link:** Add `← Workspaces` link before workspace name to navigate back to list
- **Escalation alert banner:** When any agent has state `blocked` or `failed`, show an amber/red banner below the header:
  ```
  ┌─────────────────────────────────────────────────────────────────────┐
  │ ⚠ agent-3 is blocked: "Cannot access API key"   [View] [Respond]  │
  └─────────────────────────────────────────────────────────────────────┘
  ```
  This banner is persistent until the escalation is resolved. Multiple escalations stack.

#### 3.2.2 Left Sidebar (TeamRoster + BudgetPanel)

**Existing components:** `TeamRoster` and `BudgetPanel`, both implemented.

```
┌──────────────┐
│  TEAM        │  ← section label (ws-section-label)
│              │
│ ● designer   │  ← AgentAvatar + name + status dot
│   Creating..│  ← current task or role (truncated)
│              │
│ ● architect  │
│   Designing.│
│              │
│ ○ researcher │  ← red dot = blocked/failed
│   Blocked    │
│              │
│ ──────────── │
│  BUDGET      │  ← section label
│  $12 / $50   │
│  ████░░ 24%  │  ← progress bar with color thresholds
│              │
│  designer    │  ← per-agent cost breakdown
│    $3.42     │
│  architect   │
│    $5.10     │
│              │
│ ──────────── │
│  goal text.. │  ← workspace goal (truncated)
└──────────────┘
```

**Width:** 220px fixed.  
**Scroll:** The team roster section scrolls independently if many agents.  
**Selection:** Clicking an agent highlights them (`.ws-agent-row--selected`) AND sets the ChatPanel to show that agent's conversation.

**No changes needed** to existing components — they cover the required functionality.

**Future enhancement (P2):** Collapsible sidebar to icon-only rail (48px) for more main content space. Not required for initial release.

#### 3.2.3 Main Content Area (Tab-Switched)

**Existing implementation:** Tab bar at top with Board / Backlog / Files tabs.

```
┌──────────────────────────────────────────────────┐
│  [Board]  [Backlog]  [Files]           5/9 done  │  ← tab bar
├──────────────────────────────────────────────────┤
│                                                  │
│           (tab content area)                     │
│                                                  │
│                                                  │
│                                                  │
│                                                  │
│                                                  │
└──────────────────────────────────────────────────┘
```

**Tab bar layout:** Flexbox row. Tabs left-aligned, task progress counter right-aligned.
- Active tab: bottom border accent + bold text
- Inactive tab: muted text, hover highlight

##### Board Tab (`BoardFeed`)

The default/home tab. Shows the workspace board as a reverse-chronological feed.

```
┌──────────────────────────────────────────────────┐
│  ┌─ NEEDS YOUR INPUT ──────────────────────────┐ │  ← pinned section for open discussions
│  │ designer asks: Should we use tabs or...     │ │
│  │ [Options]  [Reply]  [Resolve]               │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────────────────────────────────┐    │  ← board post card
│  │ ● architect · decision · 2m ago          │    │
│  │                                          │    │
│  │ Using React Query for server state,      │    │
│  │ Zustand for local UI state.              │    │
│  │                                          │    │
│  │ 💬 2 replies                              │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │ ● ui-researcher · post · 5m ago          │    │
│  │ Completed analysis of Linear, Asana...   │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │ Post to the board...                     │    │  ← compose area (bottom-fixed)
│  │ [post ▾]                          [Post] │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

**Post card anatomy:**
- **Header row:** Author avatar/dot + author name + section badge + relative timestamp
- **Content:** Markdown-rendered text, up to ~200 chars before truncation with "Show more"
- **Footer:** Reply count, pinned indicator, section tag
- **Visual differentiation by section:**
  - `announcement`: Blue left border
  - `decision`: Green left border
  - `question`: Amber left border, highlighted background
  - `alert`: Red left border, red-tinted background
  - `post`: Default (no accent border)

**Compose area:** Fixed to bottom of feed area. Textarea + section selector dropdown + Post button. Enter to submit, Shift+Enter for newline. Already implemented in `BoardFeed`.

**Feed ordering:** Pinned posts first, then reverse-chronological. Already implemented.

**Open discussions section:** "Needs your input" banner at top when open `DiscussionThread` items exist. Uses `DiscussionCard` component. Already implemented.

##### Backlog Tab (`KanbanBacklog`)

Shows tasks in a horizontal kanban board.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Proposed (2)│ Ready (1)  │ In Progress(3)│ Review (1) │ Done (5)    │
│             │            │               │            │             │
│ ┌─────────┐ │ ┌────────┐ │ ┌───────────┐ │ ┌────────┐ │ ┌─────────┐│
│ │Research │ │ │Impl.   │ │ │Design     │ │ │Tech    │ │ │UX pat- ││
│ │compet-  │ │ │board   │ │ │dashboard  │ │ │arch    │ │ │terns   ││
│ │itors   │ │ │feed    │ │ │layout     │ │ │doc     │ │ │research││
│ │         │ │ │        │ │ │           │ │ │        │ │ │        ││
│ │→ none   │ │ │→ none  │ │ │→ designer │ │ │→ archi.│ │ │→ ui-re.││
│ │🔴 high  │ │ │🟡 norm │ │ │🔴 high    │ │ │🟡 norm │ │ │✓      ││
│ └─────────┘ │ └────────┘ │ ├───────────┤ │ └────────┘ │ └─────────┘│
│ ┌─────────┐ │            │ │Write      │ │            │ ┌─────────┐│
│ │Review   │ │            │ │tests      │ │            │ │Chat UI ││
│ │spec     │ │            │ │→ architect│ │            │ │patterns ││
│ └─────────┘ │            │ └───────────┘ │            │ └─────────┘│
│             │            │               │            │             │
│             │            │     ...       │            │             │
└──────────────────────────────────────────────────────────────────────┘
  + Blocked (1) column shown if any blocked tasks exist
```

**Column definitions** (already in KanbanBacklog.tsx):

| Column | Statuses included |
|--------|-------------------|
| Proposed | `proposed`, `specifying` |
| Ready | `open` |
| In Progress | `claimed`, `in_progress` |
| Review | `completed`, `in_review`, `revision_needed` |
| Done | `done` |
| Blocked | `blocked` (shown only when non-empty, reduced opacity) |

**Task card anatomy** (existing `TaskCard`):
- **Title** (bold, 12px)
- **Assignee** with arrow prefix: `→ designer`
- **Priority indicator:** Colored dot + label (critical=red, high=orange, normal=yellow, low=gray)
- **Cost badge** (if available): Small mono text showing `$X.XX`
- **Dependency indicator:** Small chain icon if `depends_on` is non-empty

**Layout:** Horizontal flexbox, each column fixed min-width 180px, horizontal scroll on overflow. Column cards stack vertically with 8px gap.

**No drag-drop in v1.** Cards are read-only. Agents move their own tasks. Humans can claim/complete via button on card (already implemented). Drag-drop is a P2 enhancement.

##### Files Tab (Placeholder)

```
┌──────────────────────────────────┐
│          📁                       │
│          Files                    │
│   Workspace file browser —       │
│   coming soon.                   │
└──────────────────────────────────┘
```

Empty state already implemented. Future feature — not designed in this spec.

#### 3.2.4 Right Panel (`ChatPanel`)

**Existing component:** `ChatPanel` — already implemented with agent selection, message list, and compose input.

```
┌──────────────────────┐
│  MESSAGES · designer │  ← header with selected agent
├──────────────────────┤
│                      │
│  ┌────────────────┐  │
│  │ designer:      │  │  ← agent message (left-aligned)
│  │ inform         │  │
│  │ "Research done │  │
│  │  for kanban    │  │
│  │  patterns."    │  │
│  │         3m ago │  │
│  └────────────────┘  │
│                      │
│  ┌────────────────┐  │
│  │ You:           │  │  ← human message (highlighted bg)
│  │ directive      │  │
│  │ "Focus on      │  │
│  │  Linear and    │  │
│  │  Notion."      │  │
│  │         2m ago │  │
│  └────────────────┘  │
│                      │
│  ┌────────────────┐  │
│  │ designer:      │  │
│  │ request        │  │
│  │ "Should I      │  │
│  │  include Jira  │  │
│  │  in scope?"    │  │
│  │         1m ago │  │
│  └────────────────┘  │
│                      │
├──────────────────────┤
│ Message designer...  │  ← compose area
│ [inform▾]    [Send]  │
└──────────────────────┘
```

**Width:** 280px fixed.  
**Agent selection:** Tied to sidebar TeamRoster selection. Clicking an agent in the sidebar filters the chat to that conversation.  
**Empty state:** "Select a team member" prompt when no agent is selected.

**Message visual differentiation:**
- Human messages: `.ws-chat-msg--human` — slightly different background
- Agent messages: `.ws-chat-msg--agent` — default
- Directive messages: `.ws-chat-msg--directive` — accent border (already implemented)
- Speech act badge: Shown inline after sender name (`SpeechActBadge`)
- Priority badge: Shown for `high`/`critical` priority (`PriorityBadge`)

**Compose area:** Textarea + speech act selector (inform/request/directive/propose) + Send button. Enter to send, Shift+Enter for newline. Already implemented.

**Future enhancements (P2):**
- Threading support (reply to specific messages)
- "Send to All" option
- Message search
- Unread message count badge on sidebar agent rows

#### 3.2.5 Status Bar (`StatusBar`)

**Existing component:** Already implemented.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ● Connected │ board v14 │ 2 active agents │ 3 team members    AgentOS  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Height:** 28px.  
**Content:** Connection status dot + board version + active agent count + total team count + brand.

---

## 4. Panel Visibility & Behavior

### 4.1 Always Visible Panels

| Panel | Rationale |
|-------|-----------|
| WorkspaceHeader | Status/budget/controls are always needed for oversight |
| TeamRoster (sidebar) | Knowing agent states is the #1 oversight need |
| BudgetPanel (sidebar) | Cost awareness must be constant |
| Main content tabs | The primary work area |
| StatusBar | Connection state is critical for a real-time app |

### 4.2 Conditionally Visible Panels

| Panel | Condition | Behavior |
|-------|-----------|----------|
| ChatPanel | Always rendered, but content depends on agent selection | Shows empty state when no agent selected |
| Escalation banner | Shown when any agent is `blocked` or `failed` | Persistent banner below header |
| "Needs your input" section | Shown when open DiscussionThread items exist | Pinned to top of Board feed |
| Blocked column (kanban) | Shown only when blocked tasks exist | Appended after Done column, reduced opacity |

### 4.3 Collapsibility (Future)

For v1, all panels are fixed. For v2:

| Panel | Collapse behavior |
|-------|-------------------|
| Left sidebar | Collapse to 48px icon rail (team avatars only, no text) |
| Right chat panel | Collapse to 48px rail showing unread badge count |
| Status bar | Already minimal, no collapse needed |

---

## 5. Responsive Behavior

### 5.1 Breakpoints

| Breakpoint | Layout Change |
|------------|---------------|
| >= 1280px (desktop) | Full three-panel layout: sidebar (220px) + main (fluid) + chat (280px) |
| 1024–1279px (small desktop) | Chat panel narrows to 240px. Sidebar stays 220px. |
| 768–1023px (tablet) | Chat panel becomes a slide-over drawer (triggered by button in header). Sidebar stays visible at 200px. |
| < 768px (mobile) | Single-column layout. Sidebar becomes a hamburger-triggered drawer. Chat becomes a full-screen overlay. Tabs become a horizontal scroll. Not a primary target but should be usable. |

### 5.2 CSS Strategy

The existing layout uses flexbox with fixed widths. Responsive behavior should use CSS custom properties and media queries:

```css
/* Existing approach — extend with responsive overrides */
.ws-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.ws-sidebar { width: 220px; flex-shrink: 0; }
.ws-main { flex: 1; min-width: 0; }
.ws-chat { width: 280px; flex-shrink: 0; }

@media (max-width: 1279px) {
  .ws-chat { width: 240px; }
}

@media (max-width: 1023px) {
  .ws-chat {
    position: fixed;
    right: 0; top: 48px; bottom: 28px;
    width: 320px;
    transform: translateX(100%);
    transition: transform 0.2s ease;
    z-index: 100;
    box-shadow: -4px 0 20px rgba(0,0,0,0.3);
  }
  .ws-chat--open { transform: translateX(0); }
  .ws-sidebar { width: 200px; }
}

@media (max-width: 767px) {
  .ws-sidebar {
    position: fixed;
    left: 0; top: 48px; bottom: 28px;
    width: 280px;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 100;
  }
  .ws-sidebar--open { transform: translateX(0); }
}
```

### 5.3 Touch Considerations

Kanban cards need larger hit targets on touch devices. Minimum 44px tap target for interactive elements. Drag-drop (when added in v2) should support both mouse and touch via `@dnd-kit` or similar.

---

## 6. Component Map

### 6.1 Existing Components (no changes needed for v1)

| Component | Path | Status |
|-----------|------|--------|
| `WorkspaceHeader` | `components/workspace/WorkspaceHeader.tsx` | Complete |
| `TeamRoster` | `components/workspace/TeamRoster.tsx` | Complete |
| `BudgetPanel` | `components/workspace/BudgetPanel.tsx` | Complete |
| `BoardFeed` | `components/workspace/BoardFeed.tsx` | Complete |
| `BoardPost` | `components/workspace/BoardPost.tsx` | Complete |
| `DiscussionCard` | `components/workspace/DiscussionCard.tsx` | Complete |
| `KanbanBacklog` | `components/workspace/KanbanBacklog.tsx` | Complete |
| `TaskCard` | `components/workspace/TaskCard.tsx` | Complete |
| `ChatPanel` | `components/workspace/ChatPanel.tsx` | Complete |
| `StatusBar` | `components/workspace/StatusBar.tsx` | Complete |
| `StatusBadge` | `components/shared/StatusBadge.tsx` | Complete |
| `AgentAvatar` | `components/shared/AgentAvatar.tsx` | Complete |
| `WorkspaceListPage` | `pages/WorkspaceListPage.tsx` | Complete |
| `WorkspacePage` | `pages/WorkspacePage.tsx` | Complete |

### 6.2 New Components Needed

| Component | Purpose | Priority |
|-----------|---------|----------|
| `EscalationBanner` | Persistent alert banner for blocked/failed agents | P1 |
| `BackLink` | "← Workspaces" breadcrumb in header | P1 |
| `ChatToggleButton` | Button to open/close chat drawer on tablet | P1 (responsive) |
| `SidebarToggle` | Hamburger button to open sidebar on mobile | P2 (responsive) |
| `NotificationToast` | Toast notifications for high-priority events | P2 |
| `CommandPalette` | Cmd+K quick navigation/action palette | P2 |

### 6.3 Component Tree

```
App
├── WorkspaceListPage
│   └── WorkspaceCard[] (inline, using ws-list-card class)
│       └── StatusBadge
│
└── WorkspacePage
    ├── WorkspaceHeader
    │   ├── BackLink (new)
    │   ├── StatusBadge
    │   └── BudgetBar (inline)
    │
    ├── EscalationBanner (new, conditional)
    │
    ├── ws-body (layout container)
    │   ├── ws-sidebar
    │   │   ├── TeamRoster
    │   │   │   └── AgentRow[]
    │   │   │       ├── AgentAvatar
    │   │   │       └── StatusDot
    │   │   ├── BudgetPanel
    │   │   └── GoalSnippet (inline)
    │   │
    │   ├── ws-main
    │   │   ├── TabBar (Board | Backlog | Files)
    │   │   └── TabContent
    │   │       ├── BoardFeed (when tab=board)
    │   │       │   ├── DiscussionCard[] (open discussions)
    │   │       │   ├── BoardPost[]
    │   │       │   └── ComposeArea
    │   │       ├── KanbanBacklog (when tab=backlog)
    │   │       │   └── KanbanColumn[]
    │   │       │       └── TaskCard[]
    │   │       └── FilesPlaceholder (when tab=files)
    │   │
    │   └── ChatPanel
    │       ├── ChatHeader
    │       ├── MessageList
    │       │   └── ChatMessage[]
    │       └── ComposeArea
    │
    └── StatusBar
```

---

## 7. Interaction Patterns

### 7.1 Agent Selection Flow

1. Human clicks agent in TeamRoster sidebar
2. Agent row highlights (`.ws-agent-row--selected`)
3. ChatPanel filters to show conversation with that agent
4. ChatPanel compose placeholder updates to "Message {agent}..."
5. Clicking same agent again deselects (shows all messages / empty state)

Already implemented in `WorkspacePage` via `selectedAgent` state.

### 7.2 Board Posting Flow

1. Human types in compose area at bottom of BoardFeed
2. Selects section type from dropdown (post/question/decision/announcement)
3. Presses Enter or clicks Post
4. Optimistic: post appears immediately at top of feed
5. Confirmed: WebSocket pushes `board_post` event to update feed state

Already implemented in `BoardFeed` and `useWorkspace`.

### 7.3 Task Oversight Flow

1. Human switches to Backlog tab
2. Scans kanban columns for task distribution
3. Can click "Claim" on Ready tasks (assigns to human)
4. Can click "Complete" on In Progress tasks
5. Task cards show agent assignment, priority, and status

Already implemented. Future: clicking a task card opens a detail panel.

### 7.4 Messaging Flow

1. Human selects agent in sidebar
2. Types message in ChatPanel compose area
3. Selects speech act (inform/request/directive/propose)
4. Presses Enter or clicks Send
5. Message appears immediately in chat (optimistic update)
6. WebSocket delivers to agent and confirms

Already implemented in `ChatPanel` and `useWorkspace`.

### 7.5 Escalation Handling Flow (New)

1. Agent posts an escalation → `agent_status` event with state `blocked`/`failed`
2. `EscalationBanner` appears below header with agent name + issue summary
3. Human can click "View" to select the agent and see their messages
4. Human can click "Respond" to open the chat with that agent pre-selected
5. Human sends a directive message resolving the issue
6. Agent resumes → `agent_status` event clears the banner

**New component needed:** `EscalationBanner`

### 7.6 Workspace Lifecycle Flow

| Action | Trigger | UI Response |
|--------|---------|-------------|
| Pause | Human clicks "Pause" button in header | Confirmation dialog → status badge changes to amber "PAUSED" → system message in board feed |
| Resume | Human clicks "Resume" button (shown when paused) | Status badge changes to green "ACTIVE" → system message in board feed |
| Complete | Human clicks "Complete" button | Confirmation dialog → status badge changes to "COMPLETED" → summary card in board feed → compose areas become disabled |

Partially implemented. Confirmation dialogs are TODO in current code.

---

## 8. Visual Design Tokens

The existing CSS uses custom properties defined in `workspace.css`. Key tokens referenced by components:

| Token | Purpose |
|-------|---------|
| `--ws-bg` | Page background |
| `--ws-bg-card` | Card/panel background |
| `--ws-bg-raised` | Elevated surface (compose areas) |
| `--ws-bg-inset` | Inset surface (input fields) |
| `--ws-text` | Primary text |
| `--ws-text-secondary` | Secondary text |
| `--ws-text-tertiary` | Muted text |
| `--ws-border` | Border color |
| `--ws-accent` | Primary accent (green, for AgentOS brand) |
| `--ws-accent-dim` | Dimmed accent background |
| `--ws-radius` | Border radius (6px) |
| `--ws-font-mono` | Monospace font family |
| `--ws-font-body` | Body font family |
| `--ws-transition-fast` | Fast transition duration |

**Color system for status:**
- Running/Active: Green (`--ws-accent`)
- Idle/Waiting: Gray (`--ws-text-tertiary`)
- Blocked/Error: Red (to be defined, suggest `--ws-danger: #ef4444`)
- Warning/Paused: Amber (to be defined, suggest `--ws-warning: #f59e0b`)

**Color system for board sections:**
- Post: No accent (default)
- Question: Amber left border (`--ws-warning`)
- Decision: Green left border (`--ws-accent`)
- Announcement: Blue left border (suggest `--ws-info: #38bdf8`)
- Alert: Red left border (`--ws-danger`)

---

## 9. Real-Time Update Behavior

All real-time updates flow through the WebSocket connection managed by `useWorkspace` hook. The following table defines the UI response to each event type:

| WsEvent Type | Component Updated | Animation/Behavior |
|-------------|-------------------|-------------------|
| `board_post` | BoardFeed | New post slides in at top with subtle highlight fade (200ms). Feed auto-scrolls only if user is at top. |
| `agent_status` | TeamRoster, EscalationBanner | Status dot color transitions smoothly (300ms). Current task text cross-fades. If state becomes `blocked`/`failed`, EscalationBanner appears with slide-down animation. |
| `backlog_update` | KanbanBacklog | Full task list replacement (current approach). Future: animate card movement between columns. |
| `message` | ChatPanel | New message appends with slide-up animation. Auto-scroll to bottom if user is already at bottom. Unread badge increments if agent is not currently selected. |
| `budget_update` | WorkspaceHeader, BudgetPanel | Budget bar width animates (transition on CSS width). Cost numbers use `requestAnimationFrame` counter animation. |
| `workspace_status` | WorkspaceHeader, StatusBadge | Badge text and color transition. If completed, compose areas disable with fade. |
| `snapshot` | All components | Full state refresh via `fetchAll()`. No animation — hard reset. |

---

## 10. Keyboard Shortcuts (P2)

| Shortcut | Action |
|----------|--------|
| `1` / `2` / `3` | Switch to Board / Backlog / Files tab |
| `↑` / `↓` | Navigate agent list in sidebar |
| `Enter` | Select highlighted agent (opens chat) |
| `Escape` | Deselect agent / close detail panel |
| `/` | Focus board compose area |
| `Cmd+K` | Open command palette (future) |
| `Cmd+Enter` | Send message / post to board |

---

## 11. Empty States

Each component has a defined empty state for zero-data scenarios:

| Component | Empty State | Already Implemented? |
|-----------|------------|---------------------|
| WorkspaceListPage | Diamond icon + "No workspaces yet" + description | Yes |
| BoardFeed | Diamond icon + "Board is empty" + description | Yes |
| ChatPanel (no agent) | Chat icon + "Select a team member" | Yes |
| ChatPanel (no messages) | "No messages with {agent} yet." | Yes |
| TeamRoster | "No team members" text | Yes |
| KanbanBacklog | Empty columns with 0 counts | Yes (implicit) |
| Files tab | Folder icon + "Coming soon" | Yes |

---

## 12. Prioritized Implementation Roadmap

### Phase 1 — Polish Existing (Current Sprint)

All core components exist and are functional. Phase 1 is about refinement:

1. **Add `BackLink`** to WorkspaceHeader for navigation back to list
2. **Add `EscalationBanner`** component for blocked agent alerts
3. **Add confirmation dialogs** for Pause/Complete workspace actions
4. **Add section-colored left borders** to BoardPost cards
5. **Refine responsive behavior** at 1024px breakpoint (chat panel as drawer)

### Phase 2 — Enhanced Interaction

6. **Sidebar collapse** to icon rail
7. **Chat panel collapse** with unread badge
8. **Keyboard shortcuts** for tab switching and agent navigation
9. **Task detail panel** (slide-in right panel when clicking a task card)
10. **Notification toasts** for high-priority messages and escalations

### Phase 3 — Advanced Features

11. **Drag-drop** on kanban board (using @dnd-kit)
12. **Command palette** (Cmd+K)
13. **Message threading** in ChatPanel
14. **Board post filtering** by section type
15. **Agent detail panel** with activity history and cost breakdown
16. **Dark/light theme toggle** (design tokens already support theming via CSS custom properties)

---

## 13. Design Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Global nav | No persistent global sidebar | Workspace detail already has a sidebar; double-sidebar wastes space. Breadcrumb suffices for workspace switching. |
| Main content switching | Tabs (Board/Backlog/Files) | Tabs are simpler than sidebar nav and keep the sidebar free for team context. Matches Linear's approach. |
| Chat panel position | Fixed right panel | Chat is secondary to board/backlog but needs to be accessible without tab switching. Right panel allows monitoring + messaging simultaneously. |
| Chat panel visibility | Always visible on desktop | Messaging is frequent enough to warrant persistent visibility. Becomes drawer on tablet. |
| Kanban drag-drop | Deferred to Phase 2 | Agents move their own tasks. Human drag-drop is a nice-to-have, not core to oversight. |
| Agent selection model | Single selection in sidebar drives chat | Simple mental model: click agent → see their chat. No multi-select needed. |
| Responsive strategy | Desktop-first with progressive collapse | Primary users are on desktops monitoring agents. Mobile is a fallback, not primary. |
| Board feed ordering | Pinned first, then reverse-chronological | Matches user expectations from Slack/Linear. Open discussions pinned at top for visibility. |

---

*End of design spec. This document should be reviewed by the architect for technical feasibility and by the human lead for design approval.*
