/** API client for the AgentOS Platform server. */

import type {
  CreateSessionRequest,
  DomainPackDetail,
  DomainPackSummary,
  EventResponse,
  IntegrationStatus,
  ModelCapabilities,
  ModelInfo,
  PlatformSettings,
  RoleTemplate,
  SessionDetail,
  SessionSummary,
  WorkflowDefinition,
  WorkflowSummary,
  WorkflowValidationResult,
} from './types';

const BASE = '';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`API error ${resp.status}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

async function fetchVoid(url: string, init?: RequestInit): Promise<void> {
  const resp = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`API error ${resp.status}: ${body}`);
  }
}

// ── Domain Packs ────────────────────────────────────────────────────

export async function listPacks(): Promise<DomainPackSummary[]> {
  return fetchJSON('/api/packs');
}

export async function getPack(name: string): Promise<DomainPackDetail> {
  return fetchJSON(`/api/packs/${name}`);
}

export async function getPackRoles(name: string): Promise<RoleTemplate[]> {
  return fetchJSON(`/api/packs/${name}/roles`);
}

// ── Models ────────────────────────────────────────────────────────

export async function listModels(): Promise<ModelInfo[]> {
  return fetchJSON('/api/models');
}

export async function getModelCapabilities(
  model: string,
): Promise<ModelCapabilities> {
  return fetchJSON(`/api/models/${encodeURIComponent(model)}/capabilities`);
}

// ── Sessions ────────────────────────────────────────────────────────

export async function createSession(
  request: CreateSessionRequest,
): Promise<SessionSummary> {
  return fetchJSON('/api/sessions', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function listSessions(): Promise<SessionSummary[]> {
  return fetchJSON('/api/sessions');
}

export async function getSession(id: string): Promise<SessionDetail> {
  return fetchJSON(`/api/sessions/${id}`);
}

export async function startSession(id: string): Promise<{ status: string }> {
  return fetchJSON(`/api/sessions/${id}/start`, { method: 'POST' });
}

export async function stopSession(id: string): Promise<{ status: string }> {
  return fetchJSON(`/api/sessions/${id}/stop`, { method: 'POST' });
}

export async function getSessionEvents(
  id: string,
  afterSeq = 0,
): Promise<EventResponse[]> {
  return fetchJSON(`/api/sessions/${id}/events?after_seq=${afterSeq}`);
}

// ── Workflows ────────────────────────────────────────────────────

export async function listWorkflows(): Promise<WorkflowSummary[]> {
  return fetchJSON('/api/workflows');
}

export async function getWorkflow(id: string): Promise<WorkflowDefinition> {
  return fetchJSON(`/api/workflows/${id}`);
}

export async function saveWorkflow(
  workflow: WorkflowDefinition,
): Promise<WorkflowSummary> {
  return fetchJSON('/api/workflows', {
    method: 'POST',
    body: JSON.stringify(workflow),
  });
}

export async function updateWorkflow(
  id: string,
  workflow: WorkflowDefinition,
): Promise<WorkflowSummary> {
  return fetchJSON(`/api/workflows/${id}`, {
    method: 'PUT',
    body: JSON.stringify(workflow),
  });
}

export async function deleteWorkflow(id: string): Promise<void> {
  return fetchVoid(`/api/workflows/${id}`, { method: 'DELETE' });
}

export async function cloneWorkflow(
  id: string,
): Promise<WorkflowSummary> {
  return fetchJSON(`/api/workflows/${id}/clone`, { method: 'POST' });
}

export async function validateWorkflow(
  id: string,
): Promise<WorkflowValidationResult> {
  return fetchJSON(`/api/workflows/${id}/validate`, { method: 'POST' });
}

export async function runWorkflow(
  id: string,
  taskDescription = '',
): Promise<{ session_id: string; state: string }> {
  return fetchJSON(`/api/workflows/${id}/run`, {
    method: 'POST',
    body: JSON.stringify({ task_description: taskDescription }),
  });
}

// ── Settings ────────────────────────────────────────────────────

export async function getSettings(): Promise<PlatformSettings> {
  return fetchJSON('/api/settings');
}

export async function updateSettings(
  settings: Partial<PlatformSettings>,
): Promise<PlatformSettings> {
  return fetchJSON('/api/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

// ── Integrations ────────────────────────────────────────────────

export async function listIntegrations(): Promise<IntegrationStatus[]> {
  return fetchJSON('/api/integrations');
}

export async function connectSlack(
  botToken: string,
): Promise<IntegrationStatus> {
  return fetchJSON('/api/integrations/slack/connect', {
    method: 'POST',
    body: JSON.stringify({ bot_token: botToken }),
  });
}

export async function disconnectIntegration(
  name: string,
): Promise<{ status: string }> {
  return fetchJSON(`/api/integrations/${name}/disconnect`, {
    method: 'DELETE',
  });
}

// ── WebSocket ────────────────────────────────────────────────────────

export class EventStreamClient {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<(event: EventResponse) => void>>();

  connect(sessionId: string): void {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(
      `${protocol}//${location.host}/ws/sessions/${sessionId}/events`,
    );
    this.ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as EventResponse;
      this.notify(event);
    };
  }

  subscribe(
    eventType: string | '*',
    callback: (event: EventResponse) => void,
  ): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)!.add(callback);
    return () => this.listeners.get(eventType)?.delete(callback);
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
    this.listeners.clear();
  }

  private notify(event: EventResponse): void {
    // Notify type-specific listeners
    this.listeners.get(event.event_type)?.forEach((cb) => cb(event));
    // Notify wildcard listeners
    this.listeners.get('*')?.forEach((cb) => cb(event));
  }
}
