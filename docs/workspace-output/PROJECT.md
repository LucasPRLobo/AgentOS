# Project

## Goal
Research and design the AgentOS dashboard frontend — a web UI that shows
the workspace board in real-time, displays the task backlog as a kanban
board, provides a chat interface for human-agent messaging, and gives
visibility into team status, budget, and agent activity.

## Description
AgentOS is a governance and orchestration platform for AI agent teams.
The backend (Python) is complete: workspace runtime, board, messaging,
backlog, coordinator, completion detection, cost tracking.

The dashboard needs to expose these capabilities through a web interface
accessible to non-technical users. It should feel like a project
management tool (Linear, Asana) combined with a team chat (Slack) —
but for human-AI teams.

Key backend systems to surface:
- Board (announcements, findings, decisions, questions, alerts, team status)
- Task backlog (open, claimed, in-progress, review, done, blocked)
- Direct messaging (agent↔agent, agent↔human, threading)
- Team roster (agent states, roles, specializations)
- Budget/cost tracking (per-agent, per-task, workspace total)
- Workspace lifecycle (active, paused, completed)

The dashboard backend already exists at agentos/dashboard/ with a FastAPI
app. The frontend was started but is not shipping in the current release.

Tech constraints:
- React + TypeScript (existing frontend is Vite + React)
- Must connect to the existing FastAPI backend
- WebSocket for real-time updates
- Should work on localhost for local development

## Success Criteria
- UX research report with dashboard patterns and competitor analysis
- Dashboard design document with layout, components, and interaction patterns
- Technical architecture document with component tree and API integration plan
- Human lead has reviewed all outputs

_Last updated: 2026-04-02 21:06 UTC_
