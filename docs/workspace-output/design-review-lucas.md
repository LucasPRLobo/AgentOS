# Design Document Review

**Reviewer:** lucas  
**Documents reviewed:**  
- `dashboard-design-spec.md` (designer)  
- `component-interaction-patterns.md` (ui-researcher)  
**Date:** 2026-04-02  

---

## Overall Assessment: APPROVED WITH MINOR FEEDBACK

Both documents are comprehensive, well-structured, and demonstrate strong alignment with the research findings. The design is grounded in real research (Linear, Asana, Notion, CrewAI, LangGraph, etc.) and makes thoughtful tradeoffs. The focus on oversight-first design, progressive disclosure, and non-technical accessibility is exactly right for the target audience.

The existing component inventory is impressive — most of the core UI already exists, which means the design is grounded in reality rather than being purely aspirational.

---

## Strengths

### 1. Strong Research-to-Design Traceability

The six design principles (oversight-first, progressive disclosure, real-time as baseline, cost as core dimension, minimize context switching, human-readable agent actions) map directly to the UX research findings. Specific examples:

- "Oversight-first" directly addresses the research finding that agents are autonomous workers, not just task assignees — the human's job is monitoring and intervening
- "Cost as core dimension" responds to the research gap that existing PM tools and chat UIs don't surface cost data
- "Human-readable agent actions" addresses the research finding that most agent dashboards treat agents as black boxes

### 2. Navigation Model Decision

The no-global-sidebar decision is well-reasoned and backed by the Linear comparison. Avoiding double-sidebar is the right call for a workspace-focused tool. The breadcrumb-based workspace switching is sufficient for the use case.

### 3. Information Hierarchy

The P0-P6 priority ranking is sound. Placing agent activity (P1) above board activity (P2) and task progress (P3) correctly reflects that this is an oversight tool, not a project management tool. Budget at P4 (always-visible summary) with P6 detailed view follows progressive disclosure.

### 4. Escalation Banner Design

The `EscalationBanner` pattern for blocked/failed agents is a novel and important addition not found in the competitor analysis. Making it persistent below the header with "View" and "Respond" quick actions is exactly the right pattern for oversight-first design.

### 5. Agent vs. Human Visual Distinction

The consistent violet-for-agents, sky-for-humans color system across avatars, message alignment, and attribution text is clean and solves a real UX problem identified in the research (existing tools don't distinguish agent-initiated from human-initiated actions).

### 6. Real-Time Update Strategy

The per-component WebSocket event mapping with specific animations (slide-in for board posts, crossfade for agent status, animate budget bars) shows attention to perceived performance and information salience.

---

## Feedback (Minor Issues)

### 1. Inconsistency: Sidebar Width

The design spec says the left sidebar is **220px** (`dashboard-design-spec.md` Section 3.2 panel structure). The interaction patterns doc defines `--ws-sidebar-width: 272px` and the chat panel as `--ws-chat-width: 352px` vs. the design spec's 280px. These should be reconciled. 

**Recommendation:** Go with the design spec's more compact values (220px sidebar, 280px chat) for desktop, since the three-panel layout needs to leave adequate main content width on 1280px screens. At 1280px: 220 + 280 + main = 780px main content, which is workable. At 272 + 352 = 624px left for main, which is tight for a kanban board.

### 2. Inconsistency: Kanban Column Status Mapping

The design spec maps columns as: Proposed (proposed/specifying), Ready (open), In Progress (claimed/in_progress), Review (completed/in_review/revision_needed), Done (done), Blocked (blocked).

The interaction patterns doc maps them as: Open, Claimed, In Progress, Review, Done, Blocked — treating "claimed" as its own column.

**Recommendation:** Use the design spec's grouping (claimed + in_progress = "In Progress" column) to reduce the number of columns. Having a separate "Claimed" column adds clutter when the distinction between "claimed" and "in_progress" is brief for an agent.

### 3. Drag-Drop Scope Clarity

The design spec explicitly says "No drag-drop in v1" and defers to Phase 2. The interaction patterns doc specifies full drag-drop interaction patterns (Section 2.3) including multi-select, keyboard moves, and undo. This is fine since the interaction patterns doc is forward-looking, but both documents should clearly label what's v1 vs. v2 so implementers don't build the wrong thing first.

**Recommendation:** Add a `[v2]` label to the drag-drop section header in the interaction patterns doc.

### 4. Chat Panel: Threading Scope

The design spec lists threading as a "P2 future enhancement." The interaction patterns doc (Section 4.6) defines a full threading model (thread view replaces message list, reply composer, max 1-level nesting). This is a potential confusion point.

Note that the architecture review also flagged that the backend already has `GET /api/workspaces/{id}/messages/{thread_id}` — so the backend supports it even if the frontend defers it. 

**Recommendation:** Keep threading as P2 in the design spec, but keep the interaction patterns doc's threading spec as the reference design for when P2 is implemented. Add a note in both documents clarifying the phasing.

### 5. Budget Panel: Hardcoded Zeros

Per my architecture review, the `get_cost` endpoint currently returns hardcoded zeros. The design spec and interaction patterns doc both design rich budget visualizations (per-agent breakdown, threshold alerts, burn rate) that depend on real cost data.

**Recommendation:** Add a note in the design spec's Phase 1 roadmap that budget panel visualization depends on backend cost tracking being wired up. Show "Budget data unavailable" empty state when cost returns zeros, rather than showing misleading $0.00 values.

### 6. Accessibility for Non-Technical Users

The project goal specifies accessibility to non-technical users. The design does well here overall (plain language, progressive disclosure, no graph/DAG visualization). A few areas to check:

- **Speech acts (inform/request/propose):** These are jargon-y for non-technical users. Consider whether the labels need plain-English alternatives like "FYI" / "Question" / "Suggestion" in the UI, even if the API uses the formal terms.
- **Board sections (post/question/decision):** These are clear and intuitive — good.
- **Status bar metadata:** "board v14" means nothing to a non-technical user. Consider omitting the board version or making it a tooltip-only detail.

### 7. Responsive Breakpoints: Minor Inconsistency

The design spec uses breakpoints at 1280/1024/768px. The interaction patterns doc uses 1200/900/600px. Pick one set and standardize.

**Recommendation:** Use the design spec's breakpoints (1280/1024/768) as they align with common device widths.

---

## Cross-Document Consistency with Architecture Review

My earlier architecture review (`architecture-review.md`) identified that the API integration plan targets the wrong backend (v0 `server.py` instead of v1 `workspace_api.py`). The design documents correctly reference `useWorkspace` hook and WebSocket events that match the actual backend (`board_post`, `agent_status`, `backlog_update`, `message`, `snapshot`). This is good — the design spec is aligned with the real backend, even though the architecture doc wasn't.

However, the design spec's Section 9 (Real-Time Update Behavior) references `budget_update` and `workspace_status` events that may not exist yet in the actual WebSocket protocol. The architect should confirm which events the backend currently emits and which need to be added.

---

## Verdict

**APPROVED.** Both documents are ready for implementation with the minor reconciliations noted above (sidebar widths, kanban column mapping, breakpoints, v1/v2 labeling). None of the feedback items are blockers.

The design team should:
1. Reconcile the sidebar/chat width values between the two documents
2. Standardize the breakpoint values
3. Add clear v1/v2 labels to the interaction patterns sections that are Phase 2+
4. Add a "budget data unavailable" empty state for when cost tracking isn't wired up
5. Consider plain-English alternatives for speech act labels in the UI

These are all quick fixes that can be done alongside implementation. No additional design review cycle needed.

---

*Reviewed by lucas, 2026-04-02*
