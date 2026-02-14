/** API client for the AgentOS Platform server. */

import type {
  CreateSessionRequest,
  DomainPackDetail,
  DomainPackSummary,
  EventResponse,
  RoleTemplate,
  SessionDetail,
  SessionSummary,
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

export async function listModels(): Promise<{ name: string; size: string }[]> {
  return fetchJSON('/api/models');
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
