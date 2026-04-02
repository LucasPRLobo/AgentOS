# UX Research: Dashboard Patterns from Project Management Tools

**Researcher:** ui-researcher  
**Date:** 2026-04-02  
**Scope:** Linear, Asana, Notion — patterns relevant to AgentOS dashboard (human-AI teams)

---

## Executive Summary

This report analyzes UX patterns from three leading project management tools (Linear, Asana, Notion) across four dimensions: kanban board layouts, real-time activity feeds, sidebar navigation, and team status/workload visibility. Each pattern is evaluated for applicability to AgentOS's unique context: a dashboard for **human-AI teams** where AI agents are autonomous workers, not just task assignees.

**Key takeaway:** The best patterns for AgentOS combine Linear's speed-first kanban with Notion's flexible board semantics and Asana's workload visibility — but all three tools assume human-only teams. AgentOS needs novel affordances for agent state (running/idle/blocked), AI-specific activity granularity, and human oversight controls that don't exist in any of these tools.

---

## 1. Kanban Board Layouts and Drag-Drop Interaction Patterns

### 1.1 Linear

**Layout:**
- Horizontal columns representing workflow states (Backlog → Todo → In Progress → In Review → Done)
- Cards are compact: title, assignee avatar, priority icon, label chips, sub-issue progress indicator
- Column headers show count. No WIP limits by default but visually scannable
- Columns are fixed-width, horizontally scrollable when many states exist
- Grouping: can group by status (default), assignee, priority, label, or project
- Sub-issues are nested inline with an expand/collapse chevron — not separate cards

**Drag-Drop:**
- Drag handle is implicit (grab anywhere on the card)
- Drop zones highlight with a subtle blue line between cards
- Drag preview is a semi-transparent ghost of the card at ~90% opacity
- Dropping to a different column triggers an immediate status change (optimistic update)
- Multi-select: Cmd/Ctrl+click to select multiple cards, then drag as a batch
- Keyboard: cards can be moved via keyboard shortcuts (Cmd+Shift+Arrow)
- Undo: Cmd+Z reverts the last drag operation

**Pros for AgentOS:**
- Compact card design works well for task backlogs — agents process many small tasks
- Optimistic updates feel instant, critical for a real-time agent dashboard
- Multi-select drag is useful for bulk reassignment (e.g., reassigning an agent's tasks when it errors)
- Keyboard shortcuts align with power-user workflows (human operators)

**Cons for AgentOS:**
- Linear assumes status changes are human-initiated. In AgentOS, agents move their own tasks. Need to distinguish "agent moved this" from "human moved this"
- No concept of "claimed by agent" vs. "assigned by human" — we need both
- Linear's card doesn't show execution metadata (cost, duration, retries) relevant to AI tasks

### 1.2 Asana

**Layout:**
- Wider columns with more vertical card detail than Linear
- Cards show: title, assignee, due date, custom fields, subtask count, comment count, attachments indicator
- Sections within columns allow sub-grouping (e.g., "Frontend" / "Backend" sections within "In Progress")
- "Add task" button at the top and bottom of each column
- Completed column can auto-archive or collapse

**Drag-Drop:**
- Explicit drag handle (6-dot grip icon on left edge)
- Larger drop zone with a thick horizontal blue line
- Moving between columns updates status AND can trigger automation rules
- Drag across sections within a column re-orders without status change
- No native multi-select drag (must use bulk actions toolbar instead)
- Animation: smooth 200ms ease-out for card reflow

**Pros for AgentOS:**
- Section sub-grouping within columns maps well to agent grouping (e.g., within "In Progress": group by which agent is working on it)
- Custom fields on cards let us show agent-specific data (cost, model, token usage)
- Auto-archive for completed tasks prevents column bloat as agents complete work quickly

**Cons for AgentOS:**
- Heavier card UI may not scale well — AI agents can have dozens of tasks in flight simultaneously
- Explicit drag handle is slower for rapid reordering
- No concept of task velocity or throughput metrics inline

### 1.3 Notion

**Layout:**
- Database-backed boards: each card is a database row, columns are a "Status" property
- Highly customizable: any property can define columns (group by assignee, priority, etc.)
- Cards can show any combination of properties as pills/text below the title
- Cover images optional (not relevant for us)
- "Hidden" columns can be collapsed to save space
- Empty columns can be hidden entirely

**Drag-Drop:**
- Grab anywhere on card
- Drop preview is a thin blue line
- Moving cards updates the underlying database property
- No multi-select drag
- Cards reorder within a column via drag (manual sort or auto-sort by property)
- Filtering: robust filter bar above the board — filter by any property, combine with AND/OR

**Pros for AgentOS:**
- Database-backed model maps perfectly to our task backlog (tasks are structured records)
- Property-based grouping means the same data can be viewed as kanban-by-status, kanban-by-agent, or kanban-by-priority without separate views
- Robust filtering is critical when agents generate many tasks
- Hidden/collapsed columns reduce noise

**Cons for AgentOS:**
- Notion boards feel slower due to the database abstraction layer
- No real-time collaboration feel — updates require a manual refresh or have noticeable delay
- No optimistic updates — card moves feel slightly laggy
- Too much flexibility can overwhelm users who just want a simple status board

### 1.4 Synthesis: Kanban Recommendations for AgentOS

| Pattern | Recommendation | Source |
|---------|---------------|--------|
| Card density | Compact cards (Linear-style) with expandable detail | Linear |
| Drag interaction | Implicit grab (anywhere on card), optimistic update | Linear |
| Column grouping | Support group-by-status, group-by-agent, group-by-priority | Notion |
| Filtering | Filter bar with combinable property filters | Notion |
| Sub-grouping | Sections within columns for agent grouping | Asana |
| Multi-select | Cmd+click multi-select with batch drag | Linear |
| Auto-archive | Auto-collapse or archive completed tasks | Asana |
| **Novel: Agent-moved indicator** | Visual cue when a task was moved by an agent vs. human | None (new) |
| **Novel: Live progress on card** | Show agent's current activity/progress on in-progress cards | None (new) |
| **Novel: Cost badge** | Small token/cost indicator on each card | None (new) |

---

## 2. Real-Time Activity Feeds and Notification UX

### 2.1 Linear

**Activity Feed:**
- Per-issue activity timeline: shows status changes, comments, assignment changes, label changes
- Workspace-level "Inbox" — aggregated notifications for all activity relevant to user
- Inbox items are grouped by issue, not chronological flat list
- Each inbox item shows: issue title, what changed, who changed it, timestamp
- Read/unread state with bulk mark-as-read
- Inbox filtering: by project, team, type (assigned to me, mentioned, subscribed)

**Notification UX:**
- Desktop notifications for mentions and assignments
- In-app notification badge on Inbox icon (count)
- No toast/snackbar for background changes — relies on Inbox model
- Cmd+K spotlight search doubles as a quick navigation tool

**Pros for AgentOS:**
- Grouped-by-issue inbox prevents notification flooding (agents generate lots of activity)
- Read/unread state helps humans track what they've reviewed
- Inbox-centric model (vs. toast spam) is better for high-activity environments

**Cons for AgentOS:**
- Linear's feed doesn't distinguish automated vs. human actions — in AgentOS, most activity is agent-generated
- No urgency tiers beyond read/unread — we need alert levels (agent error, human review needed, FYI)
- No concept of "agent is actively working" real-time presence

### 2.2 Asana

**Activity Feed:**
- "Activity" tab on each task: chronological list of all changes
- "Inbox" (now called "Home"): personalized activity feed
- Home shows: tasks due soon, tasks completed, overdue tasks, status updates from projects
- Status updates are a first-class object: project leads post weekly updates with RAG status
- Activity items include automated rule triggers ("This task was moved to Done by a rule")

**Notification UX:**
- In-app bell icon with notification dropdown
- Toast notifications for real-time changes while viewing a project
- Email digest (daily/weekly) for offline catch-up
- Notification preferences per project (all activity, @mentions only, nothing)

**Pros for AgentOS:**
- Status updates as first-class objects map well to agent progress reports
- "Moved by a rule" concept is analogous to "moved by an agent" — Asana already normalizes non-human actors
- Per-project notification preferences help humans control noise level
- Toast for real-time changes is good for active monitoring

**Cons for AgentOS:**
- Asana's Home feed is optimized for daily/weekly cadence — agents work in seconds/minutes
- Email digests irrelevant for real-time agent monitoring
- No streaming/live-updating feed — updates appear on refresh or with a "new activity" banner

### 2.3 Notion

**Activity Feed:**
- Page-level "Updates" panel: shows edits, comments, property changes
- "All Updates" page: workspace-wide chronological feed
- Updates are fairly noisy — every property change generates an entry
- No aggregation or grouping — flat reverse-chronological list
- Comments support @mentions, inline discussion threads

**Notification UX:**
- Bell icon → notification panel (right-side overlay)
- Shows mentions, page invitations, comments, reminders
- No toast notifications for background changes
- "Follow" pages to subscribe to updates

**Pros for AgentOS:**
- Comment threading is useful for human-agent back-and-forth discussions
- Page-level updates panel is a good model for task-level activity

**Cons for AgentOS:**
- Flat chronological feed doesn't scale for agent activity volume
- No concept of urgency/priority in notifications
- Too noisy without grouping — agents would flood this

### 2.4 Synthesis: Activity Feed Recommendations for AgentOS

| Pattern | Recommendation | Source |
|---------|---------------|--------|
| Feed structure | Grouped by task/topic, not flat chronological | Linear |
| Update model | Inbox-centric with read/unread state | Linear |
| Real-time updates | Toast for critical events, silent feed update for FYI | Asana |
| Status reports | First-class "agent report" objects (not just log entries) | Asana |
| Notification control | Per-agent or per-task subscribe/unsubscribe | Asana/Notion |
| Threading | Inline comment threads on tasks for human-agent discussion | Notion |
| **Novel: Alert tiers** | Critical (agent error/blocked), Action (review needed), FYI (completed) | None (new) |
| **Novel: Live streaming** | WebSocket-powered live activity stream with auto-scroll | None (new) |
| **Novel: Agent attribution** | Distinct visual treatment for agent-generated vs. human activity | None (new) |
| **Novel: Cost tracking in feed** | Show cumulative cost alongside activity entries | None (new) |

---

## 3. Sidebar Navigation and Information Hierarchy

### 3.1 Linear

**Sidebar Structure:**
```
[Workspace Name] ▾
─────────────────
🔍 Search (Cmd+K)
📥 Inbox (badge count)
📊 My Issues
📋 Views (saved filters)
─────────────────
Teams
  └─ Team A
      ├─ Active Issues
      ├─ Backlog
      ├─ Projects
      └─ Views
  └─ Team B
      └─ ...
─────────────────
⚙ Settings
```

**Key Design Decisions:**
- Sidebar is collapsible to icon-only mode (narrow rail)
- Fixed width (~240px), doesn't resize
- Two-level hierarchy: top-level nav items + team-scoped sub-items
- Active item highlighted with background color + left border accent
- Hover reveals tooltip in collapsed mode
- Workspace switcher at top

**Pros for AgentOS:**
- Clean two-level hierarchy maps to: workspace-level items (board, chat, budget) → agent-scoped items (agent tasks, agent logs)
- Collapsible sidebar maximizes main content area
- Inbox as top-level item normalizes notification-first workflow

**Cons for AgentOS:**
- Team hierarchy assumes static teams — agents can be dynamic
- No visual indication of team health/status in sidebar

### 3.2 Asana

**Sidebar Structure:**
```
[Home]
[My Tasks]
[Inbox]
─────────────────
Favorites (pinned)
  ├─ Project A
  ├─ Project B
  └─ Portfolio X
─────────────────
Projects
  ├─ All Projects
  └─ + New Project
─────────────────
Portfolios
Goals
Reporting
─────────────────
[Invite] [Help]
```

**Key Design Decisions:**
- Sidebar is fixed, always visible (no collapse)
- Three-level: global nav → favorites → full project list
- "Favorites" section for quick access to frequently used items
- Projects have colored dot icons for visual differentiation
- Sidebar has a resizable drag handle (rare feature)
- "Reporting" as a top-level section signals analytics importance

**Pros for AgentOS:**
- "Favorites" / pinned items concept: let users pin specific agents or tasks for quick monitoring
- Reporting as top-level nav item — we should make budget/cost a top-level concern
- Colored indicators per project could show agent health status (green/yellow/red)

**Cons for AgentOS:**
- Non-collapsible sidebar wastes space on smaller screens
- Too many top-level items — cognitive load is higher than Linear
- Portfolio/Goals abstractions don't map to our domain

### 3.3 Notion

**Sidebar Structure:**
```
[Workspace Name] ▾
─────────────────
🔍 Search
🕐 Updates
⚙ Settings & Members
─────────────────
Favorites
  ├─ Page A
  └─ Page B
─────────────────
Private
  ├─ Page C
  └─ Page D
─────────────────
Shared
  ├─ Teamspace 1
  │   ├─ Page E
  │   └─ Page F
  └─ Teamspace 2
      └─ ...
```

**Key Design Decisions:**
- Tree-based navigation with infinite nesting
- Sidebar items are user-created (pages) not system-defined
- Hover to reveal "..." menu, "+" button on each section
- Drag to reorder and nest pages
- Collapsible sections with toggle arrows
- Width is resizable via drag handle

**Pros for AgentOS:**
- Tree view is natural for: Workspace → Agents → Agent's Tasks
- Collapsible sections reduce noise when monitoring specific agents
- Resizable width adapts to user preference

**Cons for AgentOS:**
- Too unstructured — users shouldn't have to organize their own navigation for a monitoring dashboard
- Deep nesting gets confusing for real-time monitoring
- No semantic meaning to sidebar items (everything is "a page")

### 3.4 Synthesis: Navigation Recommendations for AgentOS

**Recommended sidebar structure for AgentOS:**

```
[AgentOS] ▾ (workspace name)
═══════════════════════════
🔲 Board           ← workspace board (announcements, decisions, questions)
📋 Tasks            ← kanban backlog view
💬 Chat             ← messaging interface
👥 Team             ← agent roster + status
📊 Budget           ← cost tracking dashboard
═══════════════════════════
Agents (live status dots)
  ● agent-1 (active)     ← green dot = running
  ● agent-2 (idle)       ← gray dot = idle
  ○ agent-3 (blocked)    ← red dot = needs attention
═══════════════════════════
⚙ Settings
```

| Pattern | Recommendation | Source |
|---------|---------------|--------|
| Structure | Fixed two-level: global nav + agent list | Linear |
| Collapsibility | Collapsible to icon rail | Linear |
| Status indicators | Colored dots for agent state in sidebar | Asana (adapted) |
| Pinning | Allow pinning specific agents to top | Asana |
| Width | Fixed default, no resize needed | Linear |
| **Novel: Live agent status** | Real-time status dots updating via WebSocket | None (new) |
| **Novel: Agent-centric second level** | Agents listed with live state, not static teams | None (new) |

---

## 4. Team Status and Workload Visibility

### 4.1 Linear

**Team Status Patterns:**
- "Members" view shows each person's assigned issue count and current cycle load
- Cycle (sprint) progress bar: % of issues completed, chart of burn-down
- No dedicated workload view — inferred from issue counts per assignee
- Avatar stack on issues shows who's involved
- "Active" indicator on team members (online presence dot)

**Pros for AgentOS:**
- Simple issue-count-per-assignee is a baseline metric for agent load
- Online presence dot directly maps to agent running/idle state
- Burn-down charts could show task completion velocity per agent

**Cons for AgentOS:**
- No capacity planning or workload balancing view
- Presence is binary (online/offline) — agents have more states (running, idle, blocked, errored)
- No cost dimension — Linear doesn't track resource consumption

### 4.2 Asana

**Team Status Patterns:**
- **Workload view** (premium): Gantt-like horizontal bars showing each person's tasks over time, with effort (hours) stacked
- Color coding: green = under capacity, yellow = at capacity, red = over capacity
- Drag to reassign tasks from the workload view
- **Portfolio status**: Red/yellow/green RAG status per project, set manually by project leads
- **Status updates**: Narrative updates posted by project leads with structured fields (status color, summary, blockers, next steps)
- **Dashboard widgets**: Charts for task completion rate, tasks by section, tasks by assignee

**Pros for AgentOS:**
- Workload view with capacity indicators directly maps to agent utilization monitoring
- RAG status pattern: each agent could have a red/yellow/green health indicator
- Dashboard widgets for task completion rate are essential for agent performance tracking
- Status updates as structured objects (not free text) work well for agent progress reports

**Cons for AgentOS:**
- Workload view assumes time-based capacity (hours/day) — agent capacity is token/cost-based
- Manual RAG status doesn't work for agents — must be auto-computed
- Asana's workload view requires premium — signals this is a complex feature to build well

### 4.3 Notion

**Team Status Patterns:**
- No built-in team status view — users build custom databases
- Common pattern: "Team" database with status, current task, availability properties
- Linked databases allow embedding a team status table in any page
- Rollup properties can aggregate task counts per team member
- No real-time presence or activity indicators

**Pros for AgentOS:**
- Database-driven approach means team status data is queryable and filterable
- Rollup/aggregation pattern: show per-agent task counts, completion rates, costs as computed properties

**Cons for AgentOS:**
- No built-in patterns — everything is DIY
- No real-time updates — manual or slow-polling only
- No workload visualization — just data tables

### 4.4 Synthesis: Team Status Recommendations for AgentOS

| Pattern | Recommendation | Source |
|---------|---------------|--------|
| Agent roster | List with live status, current task, and utilization metric | Linear + Asana |
| Health indicators | Auto-computed RAG status per agent (based on error rate, task throughput, cost) | Asana (adapted) |
| Workload view | Horizontal bar chart showing agent utilization (token usage / budget) | Asana (adapted) |
| Dashboard widgets | Task completion rate, cost burn-down, agent activity timeline | Asana |
| Status reports | Structured agent progress reports (not free text) | Asana |
| Presence | Multi-state indicator: running (green), idle (gray), blocked (red), errored (orange) | Linear (extended) |
| **Novel: Cost-based capacity** | Show budget consumed vs. budget remaining per agent, not time-based | None (new) |
| **Novel: Activity sparkline** | Tiny inline chart showing agent activity over last N minutes | None (new) |
| **Novel: Human oversight queue** | Dedicated view for "items needing human decision" across all agents | None (new) |

---

## 5. Cross-Cutting Patterns for Human-AI Teams

These patterns don't exist in any of the analyzed tools but are critical for AgentOS:

### 5.1 Agent vs. Human Attribution
- **Problem:** In Linear/Asana/Notion, all actors are human. In AgentOS, most activity is agent-generated.
- **Recommendation:** Use distinct visual treatments — robot avatar/icon for agents, photo for humans. Color-code activity entries by actor type. Allow filtering feed by "agent only" / "human only" / "all."

### 5.2 Oversight and Intervention Controls
- **Problem:** Existing tools have no concept of "pause this worker" or "override this decision."
- **Recommendation:** Add inline action buttons on agent cards: Pause, Resume, Reassign, Cancel. These should be prominent, not buried in menus, because human oversight is a primary use case.

### 5.3 Transparency and Explainability
- **Problem:** Existing tools don't need to explain why a task was picked up or how work is being done.
- **Recommendation:** Agent cards should have an expandable "reasoning" section showing what the agent is currently doing and why. This maps to the `report_progress` data in the backend.

### 5.4 Error Handling and Escalation
- **Problem:** In human teams, errors are handled via conversation. AI agents need structured escalation.
- **Recommendation:** Escalation requests should appear as high-priority inbox items with structured context (what the agent tried, why it's stuck). Show a persistent banner when any agent is blocked/errored.

### 5.5 Cost Awareness
- **Problem:** Human team tools track time, not computational cost.
- **Recommendation:** Cost should be a first-class dimension everywhere: on task cards, in the sidebar (workspace total), in the activity feed (per-action cost), and as a dedicated budget dashboard.

---

## 6. Recommended Feature Priority for AgentOS Dashboard

Based on this analysis, here are the highest-impact patterns to implement first:

### P0 — Must Have
1. **Kanban board** with compact cards, drag-drop (Linear-style), group-by-status default
2. **Live agent status** in sidebar with multi-state indicators (running/idle/blocked/errored)
3. **Activity feed** grouped by topic with alert tiers (critical/action/FYI)
4. **WebSocket real-time updates** for all views — no manual refresh
5. **Agent vs. human visual distinction** throughout the UI

### P1 — Should Have
6. **Board view** for workspace announcements, decisions, questions (maps to backend board)
7. **Chat interface** for human-agent messaging with threading
8. **Budget dashboard** with per-agent cost tracking
9. **Oversight controls** (pause/resume/reassign) on agent cards
10. **Filter/group-by** on kanban (by agent, priority, status)

### P2 — Nice to Have
11. **Workload visualization** (horizontal utilization bars per agent)
12. **Activity sparklines** on agent roster cards
13. **Keyboard shortcuts** for power users
14. **Collapsible sidebar** for maximum content area
15. **Saved filter views** (Linear-style custom views)

---

## Appendix: Tool-by-Tool Summary

| Dimension | Linear | Asana | Notion | AgentOS Need |
|-----------|--------|-------|--------|-------------|
| Kanban card density | Compact ✓ | Medium | Flexible | Compact (high volume) |
| Drag-drop feel | Excellent | Good | Adequate | Must be excellent |
| Real-time updates | Good (Inbox) | Moderate | Poor | Critical (WebSocket) |
| Activity feed | Grouped ✓ | Chronological | Flat/noisy | Grouped + tiered |
| Sidebar nav | Clean 2-level ✓ | Cluttered | Tree-based | Clean 2-level + agent list |
| Team status | Basic presence | Workload view ✓ | DIY | Auto-computed health + cost |
| Workload vis | None | Capacity bars ✓ | None | Budget-based utilization |
| AI-ready | No | No | No | Must design from scratch |

---

*This report provides the UX research foundation for the AgentOS dashboard design phase. The designer should use these patterns and recommendations as input for the layout and component design document.*
