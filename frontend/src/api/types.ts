/** TypeScript types matching the AgentOS Platform API schemas. */

export interface ToolManifestEntry {
  name: string;
  description: string;
  side_effect: 'PURE' | 'READ' | 'WRITE' | 'DESTRUCTIVE';
  factory: string;
}

export interface RoleTemplate {
  name: string;
  display_name: string;
  description: string;
  system_prompt: string;
  tool_names: string[];
  suggested_model: string;
  budget_profile: BudgetSpec;
  max_steps: number;
  max_instances: number;
}

export interface BudgetSpec {
  max_tokens: number;
  max_tool_calls: number;
  max_time_seconds: number;
  max_recursion_depth: number;
}

export interface WorkflowManifestEntry {
  name: string;
  description: string;
  factory: string;
  default_roles: string[];
}

export interface DomainPackSummary {
  name: string;
  display_name: string;
  description: string;
  version: string;
  tool_count: number;
  role_count: number;
  workflow_count: number;
}

export interface DomainPackDetail {
  name: string;
  display_name: string;
  description: string;
  version: string;
  tools: ToolManifestEntry[];
  role_templates: RoleTemplate[];
  workflows: WorkflowManifestEntry[];
}

export interface AgentSlotConfig {
  role: string;
  model: string;
  count: number;
  budget_override?: BudgetSpec | null;
  system_prompt_override?: string | null;
}

export interface CreateSessionRequest {
  domain_pack: string;
  workflow: string;
  agents: AgentSlotConfig[];
  workspace_root: string;
  task_description?: string;
  max_parallel?: number;
}

export interface SessionSummary {
  session_id: string;
  state: string;
  domain_pack: string;
  workflow: string;
  created_at: string;
  agent_count: number;
}

export interface SessionDetail {
  session_id: string;
  state: string;
  domain_pack: string;
  workflow: string;
  created_at: string;
  agents: AgentSlotConfig[];
  event_count: number;
  error: string | null;
}

export interface EventResponse {
  run_id: string;
  seq: number;
  timestamp: string;
  event_type: string;
  payload: Record<string, unknown>;
}
