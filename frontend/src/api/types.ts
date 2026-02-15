/** TypeScript types matching the AgentOS Platform API schemas. */

// ── Tool & Role ──────────────────────────────────────────────────

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

// ── Domain Pack ──────────────────────────────────────────────────

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

// ── Session ──────────────────────────────────────────────────────

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

// ── Workflow Definition ──────────────────────────────────────────

export interface AdvancedModelConfig {
  temperature?: number;
  max_output_tokens?: number;
  few_shot_examples?: { input: string; output: string }[];
}

export interface WorkflowNodeConfig {
  model: string;
  system_prompt: string;
  persona_preset: string;
  tools: string[];
  budget: BudgetSpec | null;
  max_steps: number;
  advanced: AdvancedModelConfig | null;
}

export interface WorkflowNode {
  id: string;
  role: string;
  display_name: string;
  position: { x: number; y: number };
  config: WorkflowNodeConfig;
}

export interface DataContract {
  schema: Record<string, unknown>;
  compression_limit: number;
}

export interface WorkflowEdge {
  source: string;
  target: string;
  data_contract?: DataContract | null;
}

export interface WorkflowVariable {
  name: string;
  description: string;
  default_value: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  domain_pack: string;
  version: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables: WorkflowVariable[];
  created_at: string;
  updated_at: string;
  template_source: string | null;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  version: string;
  node_count: number;
  edge_count: number;
  domain_pack: string;
  created_at: string;
  updated_at: string;
  template_source: string | null;
}

export interface WorkflowValidationIssue {
  severity: 'error' | 'warning';
  message: string;
  node_id?: string;
}

export interface WorkflowValidationResult {
  valid: boolean;
  issues: WorkflowValidationIssue[];
}

// ── Models ───────────────────────────────────────────────────────

export interface ModelInfo {
  name: string;
  provider: string;
  display_name: string;
  available: boolean;
}

export interface ModelCapabilities {
  context_window: number;
  max_output_tokens: number;
  supports_structured_output: boolean;
  supports_tool_use: boolean;
  supports_vision: boolean;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  provider: string;
  display_name: string;
}

// ── Settings ─────────────────────────────────────────────────────

export interface PlatformSettings {
  openai_api_key: string | null;
  anthropic_api_key: string | null;
  ollama_base_url: string;
  managed_proxy_url: string | null;
  managed_proxy_key: string | null;
  default_model: string;
  workspace_dir: string;
  workflows_dir: string;
  google_oauth_token: string | null;
  slack_bot_token: string | null;
}

// ── Templates ───────────────────────────────────────────────────

export interface TemplateSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  agent_count: number;
  estimated_cost: string;
  domain_pack: string;
  tags: string[];
}

// ── NL Generation ───────────────────────────────────────────────

export interface GenerateWorkflowResponse {
  workflow: WorkflowDefinition;
  explanation: string;
}

// ── Integrations ─────────────────────────────────────────────────

export interface IntegrationStatus {
  name: string;
  connected: boolean;
  display_name: string;
}
