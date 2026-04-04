// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export type SpeechAct = "inform" | "request" | "propose" | "accept" | "reject" | "confirm" | "alert" | "directive" | "status";
export type MessagePriority = "low" | "normal" | "high" | "critical";
export type BoardSection = "announcement" | "status" | "post" | "decision" | "question" | "alert";
export type AgentState = "running" | "waiting" | "pending" | "succeeded" | "failed" | "idle";
export type BacklogTaskStatus =
  | "proposed" | "specifying" | "open" | "claimed" | "in_progress"
  | "completed" | "in_review" | "revision_needed" | "done"
  | "blocked" | "cancelled";
export type BacklogPriority = "low" | "normal" | "high" | "critical";
export type WorkspaceStatus = "active" | "paused" | "completed";
export type WorkspaceControlAction = "pause" | "resume" | "complete";
export type BacklogAction = "claim" | "start" | "complete" | "cancel";
export type GateResolution = "approved" | "rejected" | "edited";

// ---------------------------------------------------------------------------
// Workspace
// ---------------------------------------------------------------------------

export interface WorkspaceSummary {
  workspace_id: string;
  name: string;
  goal: string;
  status: WorkspaceStatus;
  team_mode: string;
  team_size: number;
  tasks_total: number;
  tasks_done: number;
  budget_used_pct: number;
  last_active: string;
  created_at: string;
}

export interface WorkspaceCost {
  total_usd: number;
  total_tokens: number;
  budget_usd: number;
  budget_tokens: number;
  consumed_pct: number;
  per_agent: Record<string, unknown>;
  per_task: Record<string, unknown>;
}

export interface WorkspaceDetail {
  workspace_id: string;
  config: Record<string, unknown>;
  status: WorkspaceStatus;
  board: BoardState;
  backlog: BacklogTask[];
  team: AgentStatus[];
  messages: DirectMessage[];
  cost: WorkspaceCost;
  created_at: string;
  last_active: string;
}

// ---------------------------------------------------------------------------
// Board
// ---------------------------------------------------------------------------

export interface BoardPost {
  post_id: string;
  section: BoardSection;
  author_type: "agent" | "human" | "system";
  author_id: string;
  content: string;
  speech_act: SpeechAct;
  structured_data: Record<string, unknown> | null;
  pinned: boolean;
  resolved: boolean;
  resolved_by: string | null;
  timestamp: string;
  expires_at: string | null;
  source_message_id: string | null;
  source_thread_id: string | null;
}

export interface BoardState {
  workflow_id: string;
  version: number;
  announcements: BoardPost[];
  team_status: AgentStatus[];
  recent_posts: BoardPost[];
  decisions: BoardPost[];
  open_questions: BoardPost[];
  alerts: BoardPost[];
  last_updated: string;
}

// ---------------------------------------------------------------------------
// Agent status
// ---------------------------------------------------------------------------

export interface AgentStatus {
  agent_id: string;
  agent_name: string;
  role: string;
  state: AgentState;
  current_task: string | null;
  progress_summary: string | null;
  last_active: string;
}

// ---------------------------------------------------------------------------
// Backlog
// ---------------------------------------------------------------------------

export interface BacklogTask {
  task_id: string;
  title: string;
  description: string;
  created_by: string;
  assigned_to: string | null;
  suggested_for: string | null;
  required_role: string | null;
  spec: string | null;
  spec_approach: string | null;
  spec_expected_output: string | null;
  spec_discussion_id: string | null;
  review_discussion_id: string | null;
  review_verdict: string | null;
  status: BacklogTaskStatus;
  depends_on: string[];
  blocks: string[];
  acceptance_criteria: string[];
  output: Record<string, unknown> | null;
  budget: Record<string, unknown> | null;
  priority: BacklogPriority;
  computed_priority: number | null;
  estimated_minutes: number | null;
  model_tier: "haiku" | "sonnet" | "opus" | null;
  next_task: Record<string, unknown> | null;
  created_at: string;
  claimed_at: string | null;
  completed_at: string | null;
  review_count: number;
  stall_count: number;
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export interface DirectMessage {
  message_id: string;
  thread_id: string | null;
  reply_to: string | null;
  reply_by: string | null;
  sender_type: "agent" | "human" | "system";
  sender_id: string;
  recipient_type: "agent" | "human";
  recipient_id: string;
  content: string;
  speech_act: SpeechAct;
  structured_data: Record<string, unknown> | null;
  attachments: string[] | null;
  priority: MessagePriority;
  workflow_id: string;
  timestamp: string;
  delivered: boolean;
  delivered_at: string | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export interface WorkflowSummary {
  workflow_id: string;
  name: string;
  status: string;
  task_count: number;
  started_at: string | null;
  completed_at: string | null;
  total_cost: number;
  event_count: number;
  task_definitions: Record<string, unknown>;
}

export interface TaskTransition {
  from: string;
  to: string;
  timestamp: string | null;
}

export interface WorkflowTask {
  name: string;
  state: string;
  agent_id: string | null;
  transitions: TaskTransition[];
  output?: Record<string, unknown>;
}

export interface WorkflowAgent {
  agent_id: string;
  agent_name: string;
  adapter_tier: string;
  spawned_at: string | null;
  terminated_at: string | null;
  termination_reason: string | null;
  metrics: Record<string, unknown>;
}

export interface GateSnapshot {
  gate_id: string;
  task_id: string;
  gate_type: string;
  resolution: string;
  resolved_by: string | null;
  pending: boolean;
}

export interface BudgetUsage {
  tokens: number;
  cost: number;
}

export interface AgentBudget {
  agent_id: string;
  usage: BudgetUsage;
  exceeded: boolean;
  exceeded_resource: string | null;
}

export interface Event {
  event_id: string;
  event_type: string;
  workflow_id: string;
  seq: number;
  timestamp: string;
  schema_version: number | string;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface WorkflowSnapshot {
  workflow_id: string;
  workflow_name: string;
  status: string;
  task_count: number;
  started_at: string | null;
  completed_at: string | null;
  total_cost: number;
  total_tokens: number;
  event_count: number;
  tasks: Record<string, WorkflowTask>;
  agents: Record<string, WorkflowAgent>;
  gates: Record<string, GateSnapshot>;
  budgets: Record<string, AgentBudget>;
  events: Event[];
  errors: unknown[];
  task_definitions: Record<string, unknown>;
}

export interface EventsResponse {
  events: Event[];
  last_seq: number;
}

export interface WorkflowBudgetResponse {
  agents: Record<string, AgentBudget>;
  total: BudgetUsage;
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export interface Template {
  id: string;
  name: string;
  description: string;
  workflow_yaml: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export interface RunInfo {
  run_id: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// WebSocket messages
// ---------------------------------------------------------------------------

export type WorkspaceWSMessage =
  | { type: "snapshot"; data: { board: BoardState; backlog: BacklogTask[]; team: AgentStatus[] } }
  | { type: "board_post"; data: BoardPost }
  | { type: "agent_status"; data: AgentStatus[] }
  | { type: "backlog_update"; data: BacklogTask[] }
  | { type: "message"; data: DirectMessage }
  | { type: "error"; data: { detail: string } };

export type WorkflowWSMessage =
  | { type: "snapshot"; data: WorkflowSnapshot }
  | ({ type: "event" } & Event)
  | { type: "error"; message: string };

// ---------------------------------------------------------------------------
// Request bodies
// ---------------------------------------------------------------------------

export interface BoardPostRequest {
  content: string;
  section?: BoardSection;
  speech_act?: SpeechAct;
}

export interface SendMessageRequest {
  to: string;
  content: string;
  speech_act?: SpeechAct;
  priority?: MessagePriority;
}

export interface CreateBacklogTaskRequest {
  title: string;
  description?: string;
  suggested_for?: string | null;
  priority?: BacklogPriority;
}

export interface UpdateBacklogTaskRequest {
  action: BacklogAction;
  participant?: string;
  summary?: string;
  reason?: string;
}

export interface ResolveGateRequest {
  resolution: GateResolution;
  feedback?: string;
  resolved_by?: string;
}

export interface WorkspaceControlRequest {
  action: WorkspaceControlAction;
}

export interface CreateTemplateRequest {
  name?: string;
  workflow_yaml: string;
  description?: string;
}

export interface UpdateTemplateRequest {
  name?: string | null;
  workflow_yaml?: string | null;
  description?: string | null;
}

export interface StartRunRequest {
  workflow_yaml: string;
  live?: boolean;
  interactive?: boolean;
}

export interface GenerateWorkflowRequest {
  description: string;
}
