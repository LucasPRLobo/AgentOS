# TUI Development Backlog

Issues and improvements to address in future iterations.

## Input

- [ ] **Long text pasting breaks** — pasting multi-line or long text into the Input widget causes display issues. Text wraps awkwardly or moves the cursor off-screen. Need a multi-line input (TextArea widget) or better overflow handling.
- [ ] **Full prompt visibility** — when typing long messages, should be able to see the entire prompt. Consider auto-expanding input or a scrollable TextArea.
- [ ] **Text copying** — Shift+mouse drag works but isn't intuitive. Explore Textual's selection API or a /copy command.

## Views

- [ ] **Board view shows in coordinator chat** — raw board renders sometimes leak into the home view
- [ ] **View switching indicators** — make it clearer which view is active (highlight the current view in the footer)
- [ ] **Agent view shows duplicate activity** — same tool call appears in both activity strip and agent chat

## Coordinator

- [ ] **Coordinator should proactively update** — post status updates to the home chat when tasks complete, agents stall, etc. without human asking
- [ ] **Setup coordinator config display** — show the proposed JSON config formatted nicely, not as raw text

## Agents

- [ ] **Agent response format** — DM responses from agents sometimes include tool call noise. Should filter to just the conversational response.
- [ ] **Idle agent indicator** — show how long an agent has been idle, suggest reassignment

## General

- [ ] **Permission handling in TUI** — when agents need approval for dangerous operations, show a prompt in the TUI instead of silently hanging
- [ ] **Token budget display** — show per-agent token usage, not just total
- [ ] **Workspace persistence** — save workspace state so you can resume later
- [ ] **Multiple workspaces** — run multiple workspaces simultaneously
