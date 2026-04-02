# Component Interaction Patterns & Visual Language

**Author:** ui-researcher
**Date:** 2026-04-02
**Task:** Design component interaction patterns and visual language
**Builds on:** workspace.css token system (`--ws-*`), ux-research-dashboard-patterns.md, research_ai_agent_dashboards.md, ux-research-ai-agent-patterns.md

---

## Table of Contents

1. [Visual Language](#1-visual-language)
2. [Kanban Board](#2-kanban-board)
3. [Board Feed](#3-board-feed)
4. [Chat Panel](#4-chat-panel)
5. [Team Roster](#5-team-roster)
6. [Budget Panel](#6-budget-panel)
7. [Cross-Cutting Patterns](#7-cross-cutting-patterns)

---

## 1. Visual Language

### 1.1 Design Tokens — Extended Color System

Building on the existing `workspace.css` tokens. The codebase already defines two token layers:

- **Dashboard layer** (`dashboard.css`): `--bg`, `--text`, `--text-dim`, `--border`, `--green`, `--red`, `--blue`, `--yellow`, `--accent` (amber-themed)
- **Workspace layer** (`workspace.css`): `--ws-*` tokens with emerald accent, more comprehensive

**Recommendation:** Standardize on the `--ws-*` namespace for the new dashboard. It's more complete and semantically clearer. Map the older tokens as aliases for backward compatibility.

#### Status Colors (Semantic)

| Token | Hex | Usage | CSS Variable |
|-------|-----|-------|-------------|
| Emerald | `#10b981` | Success, active, completed, running | `--ws-emerald` |
| Amber | `#f59e0b` | Warning, paused, pending review, caution | `--ws-amber` |
| Rose | `#f43f5e` | Error, blocked, failed, danger | `--ws-rose` |
| Sky | `#38bdf8` | Info, question, in-progress (non-agent), links | `--ws-sky` |
| Violet | `#8b5cf6` | Agent-specific, AI attribution, special | `--ws-violet` |
| Slate | `#64748b` | Idle, neutral, disabled, dormant | `--ws-slate` |

Each status color has a `*-dim` variant at 10% opacity for backgrounds:

```css
--ws-emerald-dim: rgba(16, 185, 129, 0.10);
--ws-amber-dim: rgba(245, 158, 11, 0.10);
--ws-rose-dim: rgba(244, 63, 94, 0.10);
--ws-sky-dim: rgba(56, 189, 248, 0.10);
--ws-violet-dim: rgba(139, 92, 246, 0.10);
```

#### Task Status → Color Mapping

| Status | Color | Dot State | Rationale |
|--------|-------|-----------|-----------|
| `open` | Slate | Hollow circle | Not yet started |
| `claimed` | Sky | Solid | Agent has picked it up |
| `in_progress` | Emerald | Pulsing | Active work happening |
| `review` | Amber | Solid | Awaiting human review |
| `done` | Emerald | Checkmark | Completed successfully |
| `blocked` | Rose | Solid + ring | Needs intervention |

#### Agent State → Color Mapping

| State | Color | Animation | Rationale |
|-------|-------|-----------|-----------|
| `running` | Emerald | `ws-pulse` (opacity oscillation) | Active, doing work |
| `idle` | Slate | None | Waiting for tasks |
| `blocked` | Rose | None, solid | Can't proceed |
| `errored` | Rose | `ws-pulse` (fast) | Attention needed |
| `completed` | Emerald | None, checkmark | Finished all work |

### 1.2 Typography Hierarchy

Two font stacks from workspace.css:

| Use | Font | Variable |
|-----|------|----------|
| Body/UI | Instrument Sans | `--ws-font-body` |
| Mono/Technical | Commit Mono | `--ws-font-mono` |

#### Type Scale

| Level | Size | Weight | Use |
|-------|------|--------|-----|
| **Page Title** | `--ws-font-size-xl` (20px) | 700 | Workspace name in header |
| **Section Header** | `--ws-font-size-lg` (16px) | 700 | Panel titles, major sections |
| **Card Title** | `--ws-font-size-md` (14px) | 600 | Task card titles, agent names |
| **Body** | `--ws-font-size-base` (13px) | 400 | Board post content, message text |
| **Small** | `--ws-font-size-sm` (11px) | 400-600 | Metadata, labels, secondary info |
| **Micro** | `--ws-font-size-xs` (10px) | 600-700 | Badges, timestamps, section labels |

#### Typography Rules

- **Section labels:** Mono, 10px, 700 weight, uppercase, `letter-spacing: 0.08em`, color `--ws-text-tertiary`. Already established in `ws-section-label`.
- **Timestamps:** Always mono font, 9-10px, `--ws-text-tertiary`.
- **Badges:** Mono font, 10px, 600 weight, full-round border-radius, colored dim background.
- **Cost values:** Mono font, always formatted as `$X.XX` (2 decimal places for display, 4 for detail view).
- **Agent names:** Body font, 11-13px, 600 weight. Use consistent casing (lowercase hyphenated as backend provides: `ui-researcher`).

### 1.3 Spacing System

Already defined in `workspace.css`:

| Token | Value | Usage |
|-------|-------|-------|
| `--ws-space-1` | 4px | Tight gaps (between badge and text) |
| `--ws-space-2` | 8px | Default card internal padding, list item gaps |
| `--ws-space-3` | 12px | Card padding, section padding |
| `--ws-space-4` | 16px | Panel padding, larger gaps |
| `--ws-space-5` | 20px | Major section margins |
| `--ws-space-6` | 24px | Page-level padding |
| `--ws-space-8` | 32px | Large spacing (empty states) |

**Layout-specific tokens:**

| Token | Value | Notes |
|-------|-------|-------|
| `--ws-sidebar-width` | 272px | Left sidebar |
| `--ws-chat-width` | 352px | Right chat panel |
| `--ws-header-height` | 56px | Top header |
| `--ws-statusbar-height` | 32px | Bottom status bar |
| Kanban column width | 220-280px | Min/max flex |

### 1.4 Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--ws-radius-sm` | 4px | Small buttons, inline badges |
| `--ws-radius` | 6px | Cards, inputs, default |
| `--ws-radius-md` | 8px | Card containers, panels |
| `--ws-radius-lg` | 12px | Modals, popovers, major containers |
| `--ws-radius-full` | 9999px | Dots, pills, round badges |

### 1.5 Dark/Light Theme Approach

**Current state:** Dark-only. The entire codebase uses hardcoded dark values.

**Recommendation:** Dark-first with future light theme capability.

**Strategy:**
1. Keep `--ws-*` tokens as the single source of truth
2. Current values serve as the dark theme defaults
3. Add a `[data-theme="light"]` selector on `<html>` that overrides the token values
4. No component CSS changes needed — everything references tokens

**Light theme token overrides (for future implementation):**

```css
[data-theme="light"] {
  --ws-bg: #fafbfc;
  --ws-bg-raised: #ffffff;
  --ws-bg-card: #ffffff;
  --ws-bg-card-hover: #f5f6f8;
  --ws-bg-inset: #f0f1f4;
  --ws-bg-overlay: rgba(250, 251, 252, 0.9);
  --ws-border: #e2e4e9;
  --ws-border-subtle: #eceef2;
  --ws-border-focus: #c4c8d4;
  --ws-text: #1a1d2b;
  --ws-text-secondary: #555873;
  --ws-text-tertiary: #8b8fa8;
  --ws-text-inverse: #ffffff;
  /* Status colors stay the same — they're already accessible on both */
}
```

**Toggle mechanism:** A toggle button in the header or settings. Stores preference in `localStorage`. Apply `data-theme` attribute to `<html>`.

### 1.6 Shadows & Elevation

Three levels from `workspace.css`:

| Level | Token | Usage |
|-------|-------|-------|
| Low | `--ws-shadow-sm` | Cards on hover, subtle lift |
| Medium | `--ws-shadow` | Dropdowns, popovers |
| High | `--ws-shadow-lg` | Modals, command palette |
| Glow | `--ws-shadow-glow` | Active/focused interactive elements |

### 1.7 Transitions & Animation

| Token | Value | Usage |
|-------|-------|-------|
| `--ws-transition-fast` | 120ms ease | Hover states, small interactions |
| `--ws-transition` | 200ms ease | Panel slides, card movements |
| `--ws-transition-slow` | 350ms ease | Budget bar fills, major transitions |

**Animation library (already defined):**
- `ws-pulse` — status dot pulsing
- `ws-fade-in` — generic fade
- `ws-slide-up` — board posts, messages appearing
- `ws-slide-right` — sidebar items
- `ws-scale-in` — kanban cards appearing
- `ws-pulse-glow` — active agent glow ring

---

## 2. Kanban Board

### 2.1 Layout

```
┌─ Kanban Toolbar ──────────────────────────────────────────────┐
│ Group by: [Status v]  Filter: [All agents v]  [Search...]     │
└───────────────────────────────────────────────────────────────┘
┌──────────┬──────────┬──────────┬──────────┬──────────┬────────┐
│  Open    │ Claimed  │In Progress│ Review  │  Done    │Blocked │
│  (3)     │  (1)     │  (2)     │  (1)    │  (5)     │ (1)    │
│          │          │          │         │          │        │
│ ┌──────┐ │ ┌──────┐ │ ┌──────┐ │ ┌─────┐ │ ┌──────┐ │┌──────┐│
│ │ Card │ │ │ Card │ │ │ Card │ │ │Card │ │ │ Card │ ││ Card ││
│ └──────┘ │ └──────┘ │ │ glow │ │ └─────┘ │ └──────┘ │└──────┘│
│ ┌──────┐ │          │ └──────┘ │         │ ┌──────┐ │        │
│ │ Card │ │          │ ┌──────┐ │         │ │ Card │ │        │
│ └──────┘ │          │ │ Card │ │         │ │(muted)│ │        │
│ ┌──────┐ │          │ └──────┘ │         │ └──────┘ │        │
│ │ Card │ │          │          │         │          │        │
│ └──────┘ │          │          │         │          │        │
└──────────┴──────────┴──────────┴─────────┴──────────┴────────┘
```

**Column specs:**
- Min width: 220px, max width: 280px, flex: 1
- Horizontal scroll when columns exceed viewport
- Column header: section label style (mono, uppercase, 10px) + count badge
- Cards stack vertically with `--ws-space-2` (8px) gap
- Card area scrolls independently per column

### 2.2 Task Card Anatomy

```
┌─────────────────────────────────────┐
│ ○ Research UX patterns              │  ← status dot + title
│ ui-researcher                       │  ← assignee (violet text for agents)
│ ■■■░░ 60%          $2.10           │  ← progress bar + cost
│ [high] [research]                   │  ← priority badge + label chips
└─────────────────────────────────────┘
```

**Card elements:**

| Element | Style | Behavior |
|---------|-------|----------|
| **Status dot** | 6px circle, color per status, left of title | Pulses for `in_progress` |
| **Title** | 11px, weight 600, `--ws-text`, 2-line clamp | Truncates with ellipsis |
| **Assignee** | 10px, `--ws-violet` for agents, `--ws-sky` for humans | Click to open agent detail |
| **Progress bar** | 3px height, `--ws-emerald` fill, `--ws-bg-inset` track | Only shown if progress data exists |
| **Cost** | Mono 10px, `--ws-text-tertiary` | Format: `$X.XX` |
| **Priority badge** | `ws-badge` with urgency color | Only shown for high/urgent |
| **Label chips** | `ws-badge--slate`, 9px | Compact, max 2 visible |

**Card states:**

| State | Visual Treatment |
|-------|-----------------|
| Default | `--ws-bg-card`, `--ws-border` |
| Hover | `--ws-bg-card-hover`, `--ws-border-focus`, `--ws-shadow-sm` |
| Dragging | 4px elevation shadow, 0.85 opacity, slight rotation (2deg) |
| Drop target | Dashed border (`--ws-accent`), light accent background |
| Agent-moved | Brief emerald flash animation (300ms) on status change |
| Blocked | Rose left border (2px), rose-dim background |

### 2.3 Drag-Drop Interaction

**Initiation:**
- Grab anywhere on the card (implicit handle, Linear-style)
- 150ms hold delay before drag starts (prevents accidental drags during click)
- Cursor: `grabbing` during drag

**During drag:**
- Dragged card becomes a ghost at 85% opacity with `--ws-shadow-lg`
- Slight scale-up (1.02) and 1-2deg tilt
- Source position shows a dashed placeholder outline
- Valid drop columns highlight: column header gets `--ws-accent` underline, cards area gets `--ws-accent-dim` background
- Invalid columns (if any restrictions): no highlight, cursor shows `not-allowed`
- Drop zone indicator: 2px solid `--ws-accent` line between cards at insertion point

**On drop:**
- Optimistic update: card immediately appears in new column
- Status change fires via REST API
- If API fails: card animates back to original position with a toast error
- Brief `ws-scale-in` animation on the placed card
- System generates an activity entry: "Task moved to [status] by [human]"

**Multi-select:**
- `Cmd/Ctrl+Click` to select multiple cards (blue outline on selected)
- Drag any selected card to move all selected
- Selection count badge on the drag ghost: "3 tasks"
- `Escape` to deselect all

**Keyboard:**
- `Tab` to focus cards, `Enter` to open detail
- `Cmd+Shift+Arrow` to move focused card between columns
- `Cmd+Z` to undo last move

### 2.4 Kanban Toolbar

**Group by selector:**
- Dropdown: Status (default), Agent, Priority
- Changing group-by reflows columns with `ws-fade-in` animation

**Filter bar:**
- Agent filter: multi-select dropdown listing all agents
- Status filter: checkbox list of statuses
- Text search: filters cards by title substring, debounced 200ms
- Active filters shown as removable chips

**Auto-archive toggle:**
- "Hide completed" toggle — collapses Done column to just a header with count
- Collapsed column shows stacked card edges (3-4px visible) to indicate volume

### 2.5 Column-Specific Behaviors

| Column | Special Behavior |
|--------|-----------------|
| **Open** | "+Add task" button at bottom (if human has permission) |
| **Claimed** | Shows agent name who claimed, with time-since-claimed |
| **In Progress** | Cards have live progress text from `report_progress` data, pulsing dot |
| **Review** | Cards show "Awaiting review" amber badge, action button: "Approve" / "Request changes" |
| **Done** | Cards are slightly muted (0.7 opacity), collapsed by default if >5 cards |
| **Blocked** | Rose header background, cards show escalation reason. Persistent if non-empty |

---

## 3. Board Feed

### 3.1 Layout

```
┌─ Board Toolbar ───────────────────────────────────────────────┐
│ [All] [Posts] [Questions] [Decisions] [Alerts]   [Pin filter] │
└───────────────────────────────────────────────────────────────┘
┌───────────────────────────────────────────────────────────────┐
│ 📌 PINNED                                                     │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Coordinator · decision · 5m ago                         │   │
│ │ Project goal: Research and design the AgentOS dashboard │   │
│ │ 💬 3       📌 Pinned                                    │   │
│ └─────────────────────────────────────────────────────────┘   │
├───────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ ⬡ architect · post · 2m ago                            │   │
│ │ Using React Query for server state, Zustand for local  │   │
│ │ UI state. Reasoning: RQ handles caching and invalidat..│   │
│ │ 💬 1                                                    │   │
│ └─────────────────────────────────────────────────────────┘   │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ ⬡ ui-researcher · question · 3m ago           🔵       │   │
│ │ Should I include Jira and Monday.com in the PM tool    │   │
│ │ analysis, or keep scope to Linear/Asana/Notion?        │   │
│ │ 💬 2    [Resolve ✓]                                     │   │
│ └─────────────────────────────────────────────────────────┘   │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ ⚠ agent-3 · alert · 1m ago                     🔴      │   │
│ │ Cannot access external API. Tried 3 approaches.        │   │
│ │ [View Details] [Respond]                                │   │
│ └─────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

### 3.2 Post Card Anatomy

Already partially defined in `workspace.css` as `ws-board-post`. Extend with:

```
┌─────────────────────────────────────────────────┐
│ Header: [avatar] [author] · [section badge] · [time]        │
│ Content: post text, markdown rendered, 3-line clamp          │
│ Footer: [reply count] [pin toggle] [resolve btn] [actions]   │
└─────────────────────────────────────────────────┘
```

**Post type → left border color mapping** (from `workspace.css`):

| Section | Border Color | Background | Icon |
|---------|-------------|------------|------|
| `post` | None (default) | None | None |
| `question` | `--ws-sky` (2px left) | None | `?` in sky circle |
| `decision` | `--ws-emerald` (2px left) | None | Checkmark |
| `alert` | `--ws-rose` (2px left) | `--ws-rose-dim` | Warning triangle |
| Pinned | `--ws-amber` (2px left) | `--ws-amber-dim` | Pin icon |

### 3.3 Filtering

**Filter tabs** (horizontal pill group at top):
- `All` — all posts, default
- `Posts` — section=post
- `Questions` — section=question, unresolved first
- `Decisions` — section=decision
- `Alerts` — section=alert

**Active tab:** `--ws-text` color, `--ws-accent` bottom border (2px), same pattern as `ws-main-tab--active`.

**Additional filters:**
- "Show pinned only" toggle
- Author filter: dropdown of agents
- Time filter: "Last 5m / 15m / 1h / All"

### 3.4 Post Interactions

**Resolving questions:**
- Questions show a "Resolve" button (emerald, small) in the footer
- Only visible on `question` type posts
- On click: confirmation inline — "Mark as resolved?" with [Yes] / [Cancel]
- Resolved questions: strikethrough-style muted treatment, moved below unresolved
- Resolved state shows: "Resolved by [name] at [time]" in `--ws-text-tertiary`

**Pinning:**
- Pin toggle icon in post header (pin/unpin)
- Pinned posts float to top in a "PINNED" section with `--ws-amber` section header
- Max 5 pinned posts visible (collapse with "+N more" if exceeds)
- Pin/unpin triggers toast confirmation

**Expanding:**
- Posts with >3 lines of content are clamped with "Show more" link
- Clicking "Show more" expands inline with `ws-slide-up` animation
- Expanded post shows full content + any code blocks or structured data

**Reply threading:**
- "Reply" button opens an inline reply composer below the post
- Replies are indented (16px left margin) under the parent post
- Reply count badge: `ws-badge--slate` with number
- Clicking reply count expands/collapses thread

**New post arrival:**
- WebSocket `board_post` event triggers slide-in animation from top
- Brief highlight flash (`--ws-accent-dim` background for 1s, then fade)
- If user has scrolled down: "N new posts" floating badge at top, click to scroll up
- Auto-scroll only if user is already at the top of the feed

### 3.5 Post Composition

- "New Post" button at top of feed, opens inline composer
- Fields:
  - Section selector: `[Post] [Question] [Decision]` pill toggle
  - Content: textarea with markdown support, auto-grow
  - Speech act: `[Inform] [Request] [Propose]` small toggle (collapsed by default, accessible via "..." menu)
- Submit: `Enter` to submit (with `Shift+Enter` for newline)
- Cancel: `Escape` to dismiss

---

## 4. Chat Panel

### 4.1 Layout

The chat panel occupies the right side of the three-panel layout (`ws-chat`, 352px width).

```
┌─ Chat Header ─────────────────────────────────┐
│ 💬 Messages    [To: All ▾]  [🔔 3]            │
├───────────────────────────────────────────────┤
│                                               │
│  Message List (scrollable)                    │
│                                               │
│  ┌───────────────────────────────────────┐    │
│  │ 🤖 architect · inform · 3:42 PM      │    │
│  │ The WebSocket API supports workspace  │    │
│  │ scoped events.                        │    │
│  │                   [Thread →]          │    │
│  └───────────────────────────────────────┘    │
│                                               │
│  ┌───────────────────────────────────────┐    │
│  │ 🤖 designer · request · 3:45 PM  🟠  │    │
│  │ Should the kanban support drag from   │    │
│  │ blocked column?                       │    │
│  │            [Reply] [Thread →]         │    │
│  └───────────────────────────────────────┘    │
│                                               │
│  ┌───────────────────────────────────────┐    │
│  │              You · 3:47 PM            │    │
│  │ Yes, blocked tasks should be          │    │
│  │ draggable to any column.              │    │
│  └───────────────────────────────────────┘    │
│                                               │
├───────────────────────────────────────────────┤
│ ┌─ Compose ─────────────────────────────────┐ │
│ │ [Inform ▾]  Type a message...         [→] │ │
│ │ [To: designer ▾]                          │ │
│ └───────────────────────────────────────────┘ │
└───────────────────────────────────────────────┘
```

### 4.2 Message Anatomy

Building on `ws-chat-msg` from `workspace.css`:

```
┌────────────────────────────────────────────┐
│ [avatar] sender-name · speech_act · time   │  ← header
│                                            │
│ Message content text here, supporting      │  ← body
│ markdown rendering and code blocks.        │
│                                            │
│ [Reply]  [Thread (2)]     [priority dot]   │  ← footer
└────────────────────────────────────────────┘
```

**Message types (already in workspace.css):**

| Type | CSS Class | Visual Treatment |
|------|-----------|-----------------|
| Agent message | `ws-chat-msg--agent` | Dark card bg, left-aligned, agent avatar |
| Human message | `ws-chat-msg--human` | Accent-dim bg, right-aligned |
| System message | `ws-chat-msg--system` | Centered, muted, small text |
| Directive | `ws-chat-msg--directive` | Amber-dim bg, amber border |

### 4.3 Speech Act Indicators

Each message carries a `speech_act` (`inform`, `request`, `propose`). Rendered as a small badge in the message header:

| Speech Act | Badge Style | Icon | Meaning |
|------------|-------------|------|---------|
| `inform` | `ws-badge--slate` | `i` | FYI, no response needed |
| `request` | `ws-badge--amber` | `?` | Needs a response |
| `propose` | `ws-badge--violet` | `→` | Suggesting a direction |

**Behavior:**
- `inform` messages have no special treatment beyond the badge
- `request` messages show a subtle amber left border (1px) and appear in an "unresolved requests" filter
- `propose` messages show inline action buttons: `[Accept]` `[Modify]` `[Decline]`
- When a `request` is responded to, the badge dims to `--ws-text-tertiary`

### 4.4 Priority Badges

Priority appears as a small colored dot in the message header, right-aligned:

| Priority | Visual | Behavior |
|----------|--------|----------|
| `low` | No indicator shown | Default, no visual clutter |
| `normal` | No indicator shown | Default behavior |
| `high` | Orange dot (8px, `--ws-amber`) | Message sorts higher in inbox, slight amber border |
| `urgent` | Red dot (8px, pulsing, `--ws-rose`) | Toast notification triggered, rose background tint |

### 4.5 Message Composition

**Compose area** (bottom of chat panel):

**Elements:**
1. **Recipient selector:** Dropdown above the input field. Options: "All", each agent name, "human". Default: contextual (if in DM view, pre-selected to that agent).
2. **Speech act selector:** Small segmented control: `[Inform] [Request] [Propose]`. Default: `Inform`. Collapsible into the "..." menu on narrow widths.
3. **Text input:** Auto-growing textarea, 1-4 lines visible. `Shift+Enter` for newline, `Enter` to send.
4. **Send button:** Emerald accent color (`--ws-accent`), disabled when input is empty.

**Interactions:**
- `@` trigger: typing `@` opens an autocomplete dropdown of agent names
- `/` trigger: typing `/` opens a command palette (e.g., `/pause agent-1`, `/assign task-5`)
- Markdown preview: code blocks between backticks render inline
- Empty state: placeholder text — "Message the team..." (or "Message [agent-name]..." in DM view)

### 4.6 Threading

**Thread initiation:**
- Any message with replies shows a "Thread (N)" link in its footer
- Clicking opens a thread panel that replaces the main message list (with a "← Back to messages" header)

**Thread view:**
```
┌─ Thread ──────────────────────────────────────┐
│ ← Back to messages                            │
├───────────────────────────────────────────────┤
│ [Original message, fully displayed]            │
│                                               │
│ ── 3 replies ──                               │
│                                               │
│ [Reply 1]                                     │
│ [Reply 2]                                     │
│ [Reply 3]                                     │
├───────────────────────────────────────────────┤
│ [Reply composer]                              │
└───────────────────────────────────────────────┘
```

**Thread behaviors:**
- Thread replies are always chronological (oldest first)
- New replies in a thread trigger a notification only if user is subscribed to that thread
- Thread reply count updates in real-time via WebSocket
- Threads don't nest further (max 1 level of threading, like Slack)

### 4.7 Chat Filters

Top-level filter tabs in chat header:
- **All** — all messages
- **DMs** — direct messages to/from you
- **Requests** — messages with `speech_act: request` that are unresolved
- **Unread** — unread messages only

Unread count badge shown on the "Messages" nav item in the sidebar.

---

## 5. Team Roster

### 5.1 Layout

Located in the left sidebar (`ws-sidebar`). Shows all team members with live status.

```
┌─ TEAM ────────────────────────────────────────┐
│                                               │
│ ┌───────────────────────────────────────────┐ │
│ │ 🟢 ⬡ ui-researcher                    ▸ │ │
│ │    UX Researcher                          │ │
│ │    "Analyzing competitor dashboards"       │ │
│ └───────────────────────────────────────────┘ │
│ ┌───────────────────────────────────────────┐ │
│ │ 🟢 ⬡ designer                         ▸ │ │
│ │    Dashboard Designer                     │ │
│ │    "Designing layout architecture"        │ │
│ └───────────────────────────────────────────┘ │
│ ┌───────────────────────────────────────────┐ │
│ │ ⚪ ⬡ architect                         ▸ │ │
│ │    Technical Architect                    │ │
│ │    idle                                   │ │
│ └───────────────────────────────────────────┘ │
│ ┌───────────────────────────────────────────┐ │
│ │ 🔴 ⬡ agent-3                           ▸ │ │
│ │    Data Analyst                           │ │
│ │    "BLOCKED: Cannot access API"           │ │
│ └───────────────────────────────────────────┘ │
│ ┌───────────────────────────────────────────┐ │
│ │ 🔵 👤 lucas                            ▸ │ │
│ │    Human Lead                             │ │
│ └───────────────────────────────────────────┘ │
│                                               │
└───────────────────────────────────────────────┘
```

### 5.2 Agent Row Anatomy

Building on `ws-agent-row` from `workspace.css`:

```
┌──────────────────────────────────────────────────┐
│ [dot] [avatar] [name]                      [▸]   │
│              [role text]                          │
│              [activity text]                      │
└──────────────────────────────────────────────────┘
```

**Elements:**

| Element | Style | Notes |
|---------|-------|-------|
| **Status dot** | `ws-dot` (8px), color by agent state | Pulses for `running` |
| **Avatar** | `ws-agent-avatar` (28px), icon-based | `⬡` for agents (`--ws-violet-dim`), `👤` for humans (`--ws-sky-dim`) |
| **Name** | 11px, weight 600, `--ws-text` | |
| **Role** | 10px, `--ws-text-tertiary` | From agent config |
| **Activity text** | 10px, `--ws-text-secondary`, italic | From `report_progress` data, live-updating |
| **Chevron** | `▸`, `--ws-text-tertiary` | Click/hover indicator |

### 5.3 State Badges

Displayed as a colored dot to the left of the avatar:

| State | Dot Class | Extra Visual |
|-------|-----------|-------------|
| Running | `ws-dot--active` (emerald, pulsing) | Activity text shows current task |
| Idle | `ws-dot--idle` (slate) | Activity text shows "idle" in muted |
| Blocked | `ws-dot--error` (rose) | Row gets `--ws-rose-dim` background tint, activity text prefixed "BLOCKED:" |
| Errored | `ws-dot--error` (rose, pulsing) | Same as blocked but with pulse |
| Completed | Emerald checkmark icon (no dot) | Activity text: "All tasks completed" |

### 5.4 Activity Indicators

**Live activity text:**
- Updated in real-time via WebSocket `agent_status` events
- Shows the agent's `summary` from `report_progress`
- Truncated to 1 line with ellipsis
- Tooltip on hover shows full `activity` text
- Transitions: text crossfade (opacity 0 → 1, 200ms) on update

**Cost indicator (optional, compact):**
- Below activity text: `$X.XX` in mono, `--ws-text-tertiary`
- Only shown if workspace has a budget configured
- On hover: tooltip shows "X% of agent budget"

### 5.5 Click-to-Message

**Primary click:** Opens agent detail in the context panel (right panel slide-in)

**Quick message action:**
- Hover reveals a small message icon button (💬) on the right side of the row
- Clicking the message icon pre-fills the chat composer with `To: [agent-name]`
- Focuses the chat input automatically
- If chat panel is collapsed, opens it

**Context menu (right-click or `...` menu):**
- "Send message" — opens chat with agent selected
- "View tasks" — switches to kanban filtered by this agent
- "View activity" — opens agent detail panel with full activity log
- "Pause" / "Resume" — agent control (if permitted)

### 5.6 Sort Order

Default sort:
1. Blocked/errored agents first (needs attention)
2. Running agents
3. Idle agents
4. Completed agents last

Within each group: alphabetical by name.

---

## 6. Budget Panel

### 6.1 Layout Options

**Option A: Header widget (always visible) + expandable detail panel**

The header bar (`ws-header`) includes a compact budget widget:

```
┌─────────────────────────────────────────────────────────────┐
│ [AgentOS Logo]  [Board] [Tasks] [Chat] [Team]               │
│                                   Budget: $12.45/$50  [25%] │
│                                   [████████░░░░░░░░░░░░░]   │
└─────────────────────────────────────────────────────────────┘
```

Clicking the budget widget expands to a full budget panel as a main content view.

**Option B: Dedicated "Budget" tab in main content area**

A fifth tab alongside Board/Tasks/Chat/Team.

**Recommendation:** Both. Compact widget in header for glance, full panel as a tab for detail.

### 6.2 Header Budget Widget

```
Budget: $12.45 / $50.00  [████████░░░░░░░░] 24.9%
```

**Elements:**
- Cost text: Mono font, 12px, `--ws-text`
- Progress bar: `ws-budget-bar` (4px height)
- Percentage: Mono font, 10px

**Progress bar color thresholds** (already defined in `workspace.css`):

| Range | Fill Class | Color |
|-------|-----------|-------|
| 0-60% | `ws-budget-bar__fill--ok` | Emerald |
| 60-85% | `ws-budget-bar__fill--warn` | Amber |
| 85%+ | `ws-budget-bar__fill--danger` | Rose |

**Interactions:**
- Hover: tooltip with "Consumed: $12.45 / $50.00 (24.9%)"
- Click: navigates to full budget panel view
- Budget updates animate smoothly (`--ws-transition-slow`)
- When budget exceeds 85%: widget background tints `--ws-rose-dim`, text turns `--ws-rose`

### 6.3 Full Budget Panel

```
┌─ Budget Overview ─────────────────────────────────────────────┐
│                                                               │
│  Total Budget     Consumed        Remaining      Burn Rate    │
│  $50.00           $12.45          $37.55         $0.42/min    │
│  [██████████████████████████████████░░░░░░░░░░░░░░░]  24.9%  │
│                                                               │
├─ Per-Agent Breakdown ─────────────────────────────────────────┤
│                                                               │
│  ui-researcher    ████████████░░░░░░░░  $3.42  (27.5%)       │
│  designer         ██████░░░░░░░░░░░░░░  $2.18  (17.5%)       │
│  architect        ██████████░░░░░░░░░░  $3.85  (30.9%)       │
│  agent-3          █████░░░░░░░░░░░░░░░  $1.50  (12.0%)       │
│  Coordinator      ████░░░░░░░░░░░░░░░░  $1.50  (12.0%)       │
│                                                               │
├─ Alert Thresholds ────────────────────────────────────────────┤
│                                                               │
│  ⚠ Warning at 60%: $30.00        [Triggered: No]             │
│  🔴 Critical at 85%: $42.50      [Triggered: No]             │
│  🛑 Hard limit at 100%: $50.00   [Triggered: No]             │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 6.4 Per-Agent Breakdown

**Layout:** Vertical list of horizontal budget bars, one per agent.

**Each row:**
```
[agent avatar] [agent name]  [bar ██████░░░░░░░░]  $X.XX  (XX%)
```

- Avatar: `ws-agent-avatar` (20px variant)
- Name: body font, 12px, `--ws-text`
- Progress bar: 6px height, full width of remaining space
- Cost: mono font, 12px, right-aligned
- Percentage: mono font, 10px, `--ws-text-tertiary`

**Hover on a row:** Expanded tooltip showing:
- Input tokens: X,XXX
- Output tokens: X,XXX
- Total cost: $X.XXXX
- Number of API calls: N
- Average cost per task: $X.XX

**Click on a row:** Opens agent detail panel with cost breakdown by task.

### 6.5 Alert Thresholds

Three alert levels:

| Level | Threshold | Action |
|-------|-----------|--------|
| **Warning** | 60% of budget | Amber toast notification, header widget turns amber |
| **Critical** | 85% of budget | Rose toast notification, header widget turns rose, persistent banner |
| **Hard limit** | 100% of budget | Workspace auto-pauses (if configured), full-screen alert |

**Threshold indicators:**
- Each threshold shown as a row with icon, label, value, and triggered/not-triggered badge
- Triggered thresholds: `ws-badge--amber` or `ws-badge--rose`
- Not triggered: `ws-badge--slate`

**Configurable thresholds** (nice-to-have):
- Click threshold value to edit
- Input field with validation: must be 0-100%
- Save triggers immediate threshold re-evaluation

### 6.6 Budget Animations

- **Bar fill:** CSS transition `width` with `--ws-transition-slow` (350ms)
- **Number updates:** Counter animation (increment from old value to new value over 300ms)
- **Threshold crossing:** Brief pulse animation on the threshold indicator that was triggered
- **Over budget:** Entire budget widget gets a gentle `ws-pulse` animation in rose

---

## 7. Cross-Cutting Patterns

### 7.1 Agent vs. Human Visual Distinction

This is a core design principle for AgentOS — the #1 novel pattern identified in research.

| Element | Agent | Human |
|---------|-------|-------|
| Avatar background | `--ws-violet-dim` | `--ws-sky-dim` |
| Avatar icon | Hexagon (`⬡`) or robot emoji | Circle or person emoji |
| Avatar color | `--ws-violet` | `--ws-sky` |
| Activity attribution | "⬡ agent-name" | "👤 human-name" |
| Message alignment | Left-aligned | Right-aligned |
| Action indicator | "by agent" in `--ws-violet` text | "by you" in `--ws-sky` text |

### 7.2 Loading States

Using the existing `skeleton` classes from `global.css`:

| Component | Loading Treatment |
|-----------|------------------|
| Kanban columns | Skeleton cards (3 per column, staggered heights) |
| Board feed | Skeleton post blocks (title line + 2 content lines) |
| Chat messages | Skeleton message blocks |
| Team roster | Skeleton agent rows |
| Budget bars | Skeleton rectangles with shimmer |

### 7.3 Empty States

Using `ws-empty` from `workspace.css`:

| Component | Empty Message | Sub-message |
|-----------|--------------|-------------|
| Kanban column | "No [status] tasks" | "Tasks will appear here when agents claim them" |
| Board feed | "No posts yet" | "Board posts from agents will appear here in real-time" |
| Chat | "No messages" | "Start a conversation with the team" |
| Budget | "No budget configured" | "Set a budget in workspace settings to track costs" |

### 7.4 Responsive Behavior

Already partially defined in `workspace.css`:

| Breakpoint | Behavior |
|------------|----------|
| >1200px | Full three-panel layout (sidebar + main + chat) |
| 900-1200px | Two-panel: sidebar + main. Chat becomes toggleable overlay |
| <900px | Single-panel: sidebar collapses to icon rail (48px). Main fills viewport. Chat as full-screen modal |

**Kanban responsive:**
- At <900px: columns stack vertically or become a horizontal scroll with larger min-width (280px)
- At <600px: switch to list view (cards stacked vertically grouped by status)

### 7.5 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+K` | Open command palette |
| `1-5` | Switch tabs (Board, Tasks, Chat, Team, Budget) |
| `Cmd+Shift+M` | Toggle chat panel |
| `Cmd+Shift+S` | Toggle sidebar |
| `Escape` | Close any open panel/overlay |
| `Tab` | Navigate between interactive elements |
| `Cmd+Z` | Undo last kanban move |
| `Cmd+Enter` | Send message (in chat) |

### 7.6 Toast Notifications

Using existing `toast` classes from `global.css`:

| Event | Toast Type | Duration |
|-------|-----------|----------|
| Task moved | `toast--info` | 3s, dismissible |
| Agent errored | `toast--error` | Persistent until dismissed |
| Budget warning | `toast--warning` | 5s |
| Message received (high priority) | `toast--info` | 5s |
| API error | `toast--error` | Persistent |

### 7.7 Real-Time Update Strategy (UI Layer)

All components subscribe to WebSocket events via the existing `/ws/workspace/{workspace_id}` endpoint:

| Event Type | UI Update |
|------------|-----------|
| `snapshot` | Full state hydration on connect |
| `board_post` | Prepend post to board feed with slide-in animation |
| `agent_status` | Update agent row dot color, activity text with crossfade |
| `backlog_update` | Move card between kanban columns with animation, or add/remove card |
| `message` | Append to chat message list with slide-up animation, increment unread badge |
| `budget_update` | Animate budget bar fill and counter values |

**Debouncing:** Batch rapid updates (e.g., multiple `agent_status` within 100ms) into a single render.

**Reconnection:** On WebSocket disconnect, show a subtle amber banner: "Reconnecting..." with auto-retry (exponential backoff: 1s, 2s, 4s, 8s, max 30s). On reconnect, request fresh `snapshot`.

---

## Appendix A: CSS Class Naming Convention

Follow the existing BEM-like convention from `workspace.css`:

```
.ws-{component}                    → block
.ws-{component}__{element}         → element
.ws-{component}--{modifier}        → modifier
```

Examples:
- `.ws-task-card` → `.ws-task-card__title` → `.ws-task-card--blocked`
- `.ws-chat-msg` → `.ws-chat-msg__sender` → `.ws-chat-msg--agent`
- `.ws-budget-bar` → `.ws-budget-bar__fill` → `.ws-budget-bar__fill--danger`

## Appendix B: Component Summary Matrix

| Component | CSS Exists | New CSS Needed | Key Interaction | Real-Time |
|-----------|-----------|---------------|-----------------|-----------|
| Kanban board | `ws-kanban`, `ws-task-card` | Drag-drop states, toolbar | Drag-drop between columns | `backlog_update` |
| Board feed | `ws-board-post` | Filter tabs, resolve btn | Filter, pin, resolve | `board_post` |
| Chat panel | `ws-chat-*` | Speech act badges, thread view | Compose, thread, filter | `message` |
| Team roster | `ws-agent-row`, `ws-dot` | Activity text, quick actions | Click-to-message, hover detail | `agent_status` |
| Budget panel | `ws-budget-bar` | Full panel, per-agent bars, thresholds | Click to expand, threshold config | `budget_update` |
| Header | `ws-header` | Budget widget, workspace status | Theme toggle, nav | All events |

---

*This document defines the interaction patterns and visual language for the AgentOS dashboard. It should be used alongside the layout/IA document (designer) and technical architecture document (architect) to implement the frontend.*
