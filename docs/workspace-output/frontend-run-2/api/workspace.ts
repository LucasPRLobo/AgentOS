/* AgentOS Workspace API client */

import type {
  WorkspaceSummary,
  WorkspaceState,
  BoardState,
  BoardPost,
  BacklogTask,
  AgentStatus,
  CostBreakdown,
} from '../types/workspace'

const BASE = '/api/workspaces'

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json()
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json()
}

async function putJSON<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  return resp.json()
}

// ── Workspace List ─────────────────────────────────────────────────

export const listWorkspaces = (): Promise<WorkspaceSummary[]> =>
  fetchJSON<WorkspaceSummary[]>(BASE)

export const getWorkspace = (id: string): Promise<WorkspaceState> =>
  fetchJSON<WorkspaceState>(`${BASE}/${id}`)

export const pauseWorkspace = (id: string) =>
  postJSON(`${BASE}/${id}/control`, { action: 'pause' })

export const resumeWorkspace = (id: string) =>
  postJSON(`${BASE}/${id}/control`, { action: 'resume' })

export const completeWorkspace = (id: string) =>
  postJSON(`${BASE}/${id}/control`, { action: 'complete' })

// ── Board ──────────────────────────────────────────────────────────

export const getBoard = (id: string): Promise<BoardState> =>
  fetchJSON<BoardState>(`${BASE}/${id}/board`)

export const postToBoard = (
  id: string,
  content: string,
  section = 'post',
  speech_act = 'inform',
): Promise<BoardPost> =>
  postJSON<BoardPost>(`${BASE}/${id}/board`, { content, section, speech_act })

// ── Backlog ────────────────────────────────────────────────────────

export const getBacklog = (id: string): Promise<BacklogTask[]> =>
  fetchJSON<BacklogTask[]>(`${BASE}/${id}/backlog`)

export const createTask = (
  id: string,
  task: { title: string; description?: string; suggested_for?: string; priority?: string },
): Promise<BacklogTask> =>
  postJSON<BacklogTask>(`${BASE}/${id}/backlog`, task)

export const claimTask = (id: string, taskId: string, participant = 'human') =>
  putJSON(`${BASE}/${id}/backlog/${taskId}`, { action: 'claim', participant })

export const completeTask = (id: string, taskId: string, summary = '') =>
  putJSON(`${BASE}/${id}/backlog/${taskId}`, { action: 'complete', summary })

// ── Team & Cost ────────────────────────────────────────────────────

export const getTeam = (id: string): Promise<AgentStatus[]> =>
  fetchJSON<AgentStatus[]>(`${BASE}/${id}/team`)

export const getCost = (id: string): Promise<CostBreakdown> =>
  fetchJSON<CostBreakdown>(`${BASE}/${id}/cost`)

// ── WebSocket ──────────────────────────────────────────────────────

export function createWorkspaceSocket(
  workspaceId: string,
  onEvent: (event: { type: string; data: unknown }) => void,
): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/workspace/${workspaceId}`)

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'subscribe', workspace_id: workspaceId }))
  }

  ws.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data))
    } catch { /* ignore malformed frames */ }
  }

  return ws
}
