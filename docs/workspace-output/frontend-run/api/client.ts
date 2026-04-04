import type {
  WorkspaceSummary,
  WorkspaceDetail,
  WorkspaceCost,
  BoardState,
  BoardPost,
  BacklogTask,
  AgentStatus,
  DirectMessage,
  WorkflowSummary,
  WorkflowSnapshot,
  EventsResponse,
  WorkflowBudgetResponse,
  GateSnapshot,
  Template,
  RunInfo,
  BoardPostRequest,
  SendMessageRequest,
  CreateBacklogTaskRequest,
  UpdateBacklogTaskRequest,
  ResolveGateRequest,
  WorkspaceControlRequest,
  CreateTemplateRequest,
  UpdateTemplateRequest,
  StartRunRequest,
  GenerateWorkflowRequest,
} from "../types/api";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8420";

// ---------------------------------------------------------------------------
// Generic fetch helpers
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public detail?: string,
  ) {
    super(detail ?? `API ${status}: ${statusText}`);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body.detail;
    } catch {
      // no parseable body
    }
    throw new ApiError(res.status, res.statusText, detail);
  }
  return res.json();
}

function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path);
}

function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: body != null ? JSON.stringify(body) : undefined });
}

function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: "PUT", body: body != null ? JSON.stringify(body) : undefined });
}

function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Workspaces
// ---------------------------------------------------------------------------

export function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiGet("/api/workspaces");
}

export function getWorkspace(workspaceId: string): Promise<WorkspaceDetail> {
  return apiGet(`/api/workspaces/${workspaceId}`);
}

export function controlWorkspace(workspaceId: string, body: WorkspaceControlRequest): Promise<{ status: string }> {
  return apiPost(`/api/workspaces/${workspaceId}/control`, body);
}

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

export function getBoard(workspaceId: string): Promise<BoardState> {
  return apiGet(`/api/workspaces/${workspaceId}/board`);
}

export function postToBoard(workspaceId: string, body: BoardPostRequest): Promise<BoardPost> {
  return apiPost(`/api/workspaces/${workspaceId}/board`, body);
}

// ---------------------------------------------------------------------------
// Backlog
// ---------------------------------------------------------------------------

export function getBacklog(workspaceId: string): Promise<BacklogTask[]> {
  return apiGet(`/api/workspaces/${workspaceId}/backlog`);
}

export function createBacklogTask(workspaceId: string, body: CreateBacklogTaskRequest): Promise<BacklogTask> {
  return apiPost(`/api/workspaces/${workspaceId}/backlog`, body);
}

export function updateBacklogTask(workspaceId: string, taskId: string, body: UpdateBacklogTaskRequest): Promise<BacklogTask> {
  return apiPut(`/api/workspaces/${workspaceId}/backlog/${taskId}`, body);
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export function getMessages(workspaceId: string, participant?: string): Promise<DirectMessage[]> {
  const qs = participant ? `?participant=${encodeURIComponent(participant)}` : "";
  return apiGet(`/api/workspaces/${workspaceId}/messages${qs}`);
}

export function sendMessage(workspaceId: string, body: SendMessageRequest): Promise<DirectMessage> {
  return apiPost(`/api/workspaces/${workspaceId}/messages`, body);
}

export function getThread(workspaceId: string, threadId: string): Promise<DirectMessage[]> {
  return apiGet(`/api/workspaces/${workspaceId}/messages/${threadId}`);
}

// ---------------------------------------------------------------------------
// Team
// ---------------------------------------------------------------------------

export function getTeam(workspaceId: string): Promise<AgentStatus[]> {
  return apiGet(`/api/workspaces/${workspaceId}/team`);
}

// ---------------------------------------------------------------------------
// Cost
// ---------------------------------------------------------------------------

export function getCost(workspaceId: string): Promise<WorkspaceCost> {
  return apiGet(`/api/workspaces/${workspaceId}/cost`);
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export function listWorkflows(): Promise<WorkflowSummary[]> {
  return apiGet("/api/workflows");
}

export function getWorkflow(workflowId: string): Promise<WorkflowSnapshot> {
  return apiGet(`/api/workflows/${workflowId}`);
}

export function getWorkflowEvents(
  workflowId: string,
  params?: { type?: string; since_seq?: number; limit?: number },
): Promise<EventsResponse> {
  const qs = new URLSearchParams();
  if (params?.type) qs.set("type", params.type);
  if (params?.since_seq != null) qs.set("since_seq", String(params.since_seq));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return apiGet(`/api/workflows/${workflowId}/events${query ? `?${query}` : ""}`);
}

export function getWorkflowBudget(workflowId: string): Promise<WorkflowBudgetResponse> {
  return apiGet(`/api/workflows/${workflowId}/budget`);
}

export function getWorkflowGates(workflowId: string): Promise<GateSnapshot[]> {
  return apiGet(`/api/workflows/${workflowId}/gates`);
}

export function resolveGate(workflowId: string, gateId: string, body: ResolveGateRequest): Promise<{ gate_id: string; resolution: string }> {
  return apiPost(`/api/workflows/${workflowId}/gates/${gateId}/resolve`, body);
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export function listTemplates(): Promise<Template[]> {
  return apiGet("/api/templates");
}

export function getTemplate(templateId: string): Promise<Template> {
  return apiGet(`/api/templates/${templateId}`);
}

export function createTemplate(body: CreateTemplateRequest): Promise<Template> {
  return apiPost("/api/templates", body);
}

export function updateTemplate(templateId: string, body: UpdateTemplateRequest): Promise<Template> {
  return apiPut(`/api/templates/${templateId}`, body);
}

export function deleteTemplate(templateId: string): Promise<{ deleted: boolean }> {
  return apiDelete(`/api/templates/${templateId}`);
}

export function validateTemplate(body: { workflow_yaml: string }): Promise<Record<string, unknown>> {
  return apiPost("/api/templates/validate", body);
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export function listRuns(): Promise<RunInfo[]> {
  return apiGet("/api/run");
}

export function startRun(body: StartRunRequest): Promise<{ run_id: string }> {
  return apiPost("/api/run", body);
}

export function cancelRun(runId: string): Promise<{ cancelled: boolean }> {
  return apiDelete(`/api/run/${runId}`);
}

// ---------------------------------------------------------------------------
// NL Builder
// ---------------------------------------------------------------------------

export function generateWorkflow(body: GenerateWorkflowRequest): Promise<{ workflow_yaml: string }> {
  return apiPost("/api/builder/generate", body);
}
