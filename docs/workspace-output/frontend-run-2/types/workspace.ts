/* AgentOS Workspace Types — complete, fresh interfaces mirroring Python schemas */

// ── Board ──────────────────────────────────────────────────────────

export type BoardSection =
  | 'announcement'
  | 'status'
  | 'post'
  | 'decision'
  | 'question'
  | 'alert'

export type SpeechAct =
  | 'inform'
  | 'request'
  | 'propose'
  | 'accept'
  | 'reject'
  | 'confirm'
  | 'alert'
  | 'directive'
  | 'status'

export interface BoardPost {
  post_id: string
  section: BoardSection
  author_type: 'agent' | 'human' | 'system'
  author_id: string
  content: string
  speech_act: SpeechAct
  structured_data?: Record<string, unknown>
  pinned: boolean
  resolved: boolean
  resolved_by?: string
  timestamp: string
  expires_at?: string
  source_message_id?: string
}

export interface BoardState {
  workflow_id: string
  version: number
  announcements: BoardPost[]
  team_status: AgentStatus[]
  recent_posts: BoardPost[]
  decisions: BoardPost[]
  open_questions: BoardPost[]
  alerts: BoardPost[]
  last_updated: string
}

// ── Team ───────────────────────────────────────────────────────────

export type AgentState =
  | 'running'
  | 'waiting'
  | 'pending'
  | 'succeeded'
  | 'failed'
  | 'idle'
  | 'dormant'
  | 'active'
  | 'suspended'

export interface AgentStatus {
  agent_id: string
  agent_name: string
  role: string
  state: AgentState
  current_task?: string
  progress_summary?: string
  last_active: string
}

// ── Backlog ────────────────────────────────────────────────────────

export type BacklogTaskStatus =
  | 'proposed'
  | 'specifying'
  | 'open'
  | 'claimed'
  | 'in_progress'
  | 'completed'
  | 'in_review'
  | 'revision_needed'
  | 'done'
  | 'blocked'
  | 'cancelled'

export type TaskPriority = 'low' | 'normal' | 'high' | 'critical'

export interface BacklogTask {
  task_id: string
  title: string
  description: string
  created_by: string
  assigned_to?: string
  suggested_for?: string
  required_role?: string
  status: BacklogTaskStatus
  depends_on: string[]
  blocks: string[]
  acceptance_criteria: string[]
  output?: Record<string, unknown>
  budget?: { max_cost_usd?: number; max_tokens?: number }
  priority: TaskPriority
  computed_priority?: number
  estimated_minutes?: number
  model_tier?: 'haiku' | 'sonnet' | 'opus'
  created_at: string
  claimed_at?: string
  completed_at?: string
  review_count: number
  stall_count: number
}

// ── Workspace ──────────────────────────────────────────────────────

export type WorkspaceStatus = 'active' | 'paused' | 'completed'
export type TeamMode = 'locked' | 'suggest' | 'auto_minor' | 'auto_full'

export interface WorkspaceParticipant {
  name: string
  type: 'human' | 'agent'
  roles: string[]
  specialization: string
  adapter?: string
  model?: string
}

export interface WorkspaceConfig {
  name: string
  goal: string
  description: string
  team_mode: TeamMode
  budget: { max_cost_usd?: number; max_tokens?: number }
  team: WorkspaceParticipant[]
  acceptance_criteria: string[]
}

export interface WorkspaceSummary {
  workspace_id: string
  name: string
  goal: string
  status: WorkspaceStatus
  team_mode: TeamMode
  team_size: number
  tasks_total: number
  tasks_done: number
  budget_used_pct: number
  last_active: string
  created_at: string
}

export interface CostBreakdown {
  total_usd: number
  total_tokens: number
  budget_usd?: number
  budget_tokens?: number
  consumed_pct: number
  per_agent: Record<string, { tokens: number; cost_usd: number }>
  per_task: Record<string, { tokens: number; cost_usd: number }>
}

export interface WorkspaceState {
  workspace_id: string
  config: WorkspaceConfig
  status: WorkspaceStatus
  board: BoardState
  backlog: BacklogTask[]
  team: AgentStatus[]
  cost: CostBreakdown
  created_at: string
  last_active: string
}

// ── WebSocket Events ───────────────────────────────────────────────

export type WsEventType =
  | 'snapshot'
  | 'board_post'
  | 'backlog_update'
  | 'message'
  | 'agent_status'
  | 'budget_update'
  | 'workspace_status'
  | 'error'

export interface WsEvent {
  type: WsEventType
  data: unknown
}

export interface WsSnapshot {
  board: BoardState
  backlog: BacklogTask[]
  team: AgentStatus[]
}
