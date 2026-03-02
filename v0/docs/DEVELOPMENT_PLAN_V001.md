# AgentOS Platform — v0.0.1 Development Plan

> Translates the [v0.0.1 scope](V0.0.1_SCOPE.md) into a phased implementation roadmap. Each phase is a self-contained milestone that can be tested independently.

---

## Current State (What Already Exists)

| Component | Location | Status |
|-----------|----------|--------|
| BaseLMProvider abstract | `agentos/lm/provider.py` | `complete()` only, no structured output |
| OllamaProvider | `labos/providers/ollama.py` | Working, auto-detected |
| Agent runner + action parser | `agentos/lm/agent_runner.py`, `agent_action.py` | Resilient JSON parser |
| DAG executor | `agentos/runtime/dag.py` | Topological scheduling, parallel execution |
| Event log (SQLite) | `agentos/runtime/event_log.py` | Thread-safe, append-only |
| Budget manager | `agentos/governance/budget_manager.py` | Tokens, tool calls, time |
| Permissions engine | `agentos/governance/permissions.py` | Tool access control |
| Session orchestrator | `agentplatform/orchestrator.py` | In-memory, background threads |
| FastAPI server | `agentplatform/server.py` | 7 REST endpoints + WebSocket |
| 13 tools | `labos/tools/` (5), `codeos/tools/` (7), `agentos/tools/` (base) | Pydantic v2 schemas |
| React dashboard | `frontend/` | 4 pages, 6 components |
| Domain pack registry | `agentos/runtime/domain_registry.py` | Manifest-based plugin system |

### What's Missing for v0.0.1

**Backend — Model Layer:**
- OpenAI provider (BYOK, function calling)
- Anthropic provider (BYOK, tool_use)
- `generate_structured()` method on BaseLMProvider
- Model capability registry (context windows, structured output support)
- Model fallback (retry with backup model)
- Managed proxy provider
- Settings storage + API (API keys, preferences)

**Backend — Workflow Engine:**
- Workflow data model (visual builder JSON ↔ DAG executor)
- Workflow CRUD API (save/load from filesystem)
- Workflow validation engine
- Inter-agent data contracts (JSON Schema on edges)
- Context window manager (token counting, auto-compression)
- NL → workflow generation API

**Backend — Tools:**
- Web search tool (Brave/Google API)
- Code execution sandbox (subprocess with limits)
- HTTP request tool
- `file_list` tool (directory listing)
- Google Workspace tools (Gmail, Sheets, Docs, Drive — 8 tools)
- Slack tools (post, read — 2 tools)

**Frontend:**
- Visual DAG builder (React Flow canvas)
- Template gallery page (redesign)
- NL workflow creator page
- Persona studio (node configuration panel)
- Settings page (API keys, model config)
- Workspace artifact browser

---

## Phase 1: Multi-Provider Model Layer

**Goal:** Users can connect OpenAI, Anthropic, or Ollama models. Each provider supports structured output natively where possible.

### 1.1 Extend BaseLMProvider Interface

**File:** `packages/agentos/agentos/lm/provider.py`

Add `generate_structured()` method to the abstract base:

```python
class BaseLMProvider(ABC):
    @abstractmethod
    def complete(self, messages: list[LMMessage]) -> LMResponse: ...

    def generate_structured(
        self,
        messages: list[LMMessage],
        schema: dict[str, Any],       # JSON Schema for output
        tool_schemas: list[dict] | None = None,  # Available tools
    ) -> LMResponse:
        """Generate structured output using native API features.

        Default implementation falls back to complete() + parse.
        Providers override with native structured output (function calling, tool_use).
        """
        response = self.complete(messages)
        return response  # Subclasses override for native structured output
```

Add `ModelCapabilities` dataclass:

```python
@dataclass
class ModelCapabilities:
    context_window: int           # Max tokens (input + output)
    max_output_tokens: int        # Max output tokens
    supports_structured_output: bool  # Native JSON mode / function calling
    supports_tool_use: bool       # Native tool_use protocol
    supports_vision: bool         # Image inputs
    cost_per_1k_input: float      # USD per 1K input tokens
    cost_per_1k_output: float     # USD per 1K output tokens
```

### 1.2 OpenAI Provider

**File:** `packages/agentos/agentos/lm/providers/openai.py` (new)

```python
class OpenAIProvider(BaseLMProvider):
    """BYOK OpenAI provider with function calling support."""

    def __init__(self, model: str, api_key: str): ...
    def complete(self, messages) -> LMResponse: ...
    def generate_structured(self, messages, schema, tool_schemas) -> LMResponse:
        # Use response_format={"type": "json_schema", ...} for structured output
        # Use tools parameter for tool calling
```

**Dependencies:** `openai` Python package (add to optional deps).

### 1.3 Anthropic Provider

**File:** `packages/agentos/agentos/lm/providers/anthropic.py` (new)

```python
class AnthropicProvider(BaseLMProvider):
    """BYOK Anthropic provider with tool_use support."""

    def __init__(self, model: str, api_key: str): ...
    def complete(self, messages) -> LMResponse: ...
    def generate_structured(self, messages, schema, tool_schemas) -> LMResponse:
        # Use tool_use blocks for structured agent actions
```

**Dependencies:** `anthropic` Python package (add to optional deps).

### 1.4 Model Capability Registry

**File:** `packages/agentos/agentos/lm/model_registry.py` (new)

Static registry of known model capabilities. Populated with common models. Users can add custom entries.

```python
MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "gpt-4o": ModelCapabilities(context_window=128000, ...),
    "gpt-4o-mini": ModelCapabilities(context_window=128000, ...),
    "claude-sonnet-4-5-20250929": ModelCapabilities(context_window=200000, ...),
    "claude-haiku-4-5-20251001": ModelCapabilities(context_window=200000, ...),
    "llama3.2:latest": ModelCapabilities(context_window=8192, ...),
    # ...
}

def get_capabilities(model: str) -> ModelCapabilities | None: ...
def register_model(model: str, caps: ModelCapabilities) -> None: ...
```

### 1.5 Settings Storage

**File:** `packages/platform/agentplatform/settings.py` (new)

Local settings persisted to `~/.agentos/settings.json`:

```python
class PlatformSettings(BaseModel):
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    managed_proxy_url: str | None = None
    default_model: str = "gpt-4o-mini"
    workspace_dir: str = "~/.agentos/workspaces"
    workflows_dir: str = "~/.agentos/workflows"

class SettingsManager:
    def load(self) -> PlatformSettings: ...
    def save(self, settings: PlatformSettings) -> None: ...
    # Keys encrypted at rest using platform-generated Fernet key
```

### 1.6 Settings API

**File:** `packages/platform/agentplatform/server.py` (modify)

```
GET  /api/settings          → current settings (keys masked)
PUT  /api/settings          → update settings
GET  /api/models            → list available models across all providers
GET  /api/models/{model}/capabilities → model capabilities
```

### 1.7 Managed Proxy Provider

**File:** `packages/agentos/agentos/lm/providers/managed.py` (new)

Proxies requests through a configured backend endpoint. For self-hosted deployments where the platform operator provides model access.

```python
class ManagedProxyProvider(BaseLMProvider):
    """Routes LLM requests through a managed proxy endpoint."""
    def __init__(self, model: str, proxy_url: str, proxy_key: str | None = None): ...
```

### 1.8 Model Fallback Logic

**File:** `packages/agentos/agentos/lm/providers/fallback.py` (new)

```python
class FallbackProvider(BaseLMProvider):
    """Wraps a primary provider with fallback to a backup on failure."""
    def __init__(self, primary: BaseLMProvider, fallback: BaseLMProvider): ...
    def complete(self, messages) -> LMResponse:
        try:
            return self.primary.complete(messages)
        except (RateLimitError, APIError, TimeoutError):
            return self.fallback.complete(messages)
```

### 1.9 Provider Factory Update

**File:** `packages/platform/agentplatform/server.py` (modify)

Update `create_app()` to build a provider factory from settings:

```python
def _make_provider_factory(settings: PlatformSettings) -> Callable[[str], BaseLMProvider]:
    """Create factory that routes model names to the right provider."""
    def factory(model_name: str) -> BaseLMProvider:
        if model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3"):
            return OpenAIProvider(model=model_name, api_key=settings.openai_api_key)
        elif model_name.startswith("claude-"):
            return AnthropicProvider(model=model_name, api_key=settings.anthropic_api_key)
        elif settings.managed_proxy_url and ...:
            return ManagedProxyProvider(model=model_name, proxy_url=settings.managed_proxy_url)
        else:
            return OllamaProvider(model=model_name, base_url=settings.ollama_base_url)
    return factory
```

### Tests for Phase 1

| Test File | Tests | Description |
|-----------|-------|-------------|
| `tests/unit/test_openai_provider.py` | ~5 | Mock API calls, structured output, error handling |
| `tests/unit/test_anthropic_provider.py` | ~5 | Mock API calls, tool_use blocks, error handling |
| `tests/unit/test_model_registry.py` | ~4 | Lookup, register, unknown model fallback |
| `tests/unit/test_settings.py` | ~5 | Save/load, key encryption, defaults |
| `tests/unit/test_fallback_provider.py` | ~4 | Primary success, primary fail → fallback, both fail |
| `tests/integration/test_provider_factory.py` | ~3 | Factory routes model names correctly |

### Commits for Phase 1

1. `feat(lm): add generate_structured() protocol and ModelCapabilities`
2. `feat(lm): add OpenAI provider with function calling`
3. `feat(lm): add Anthropic provider with tool_use`
4. `feat(lm): add model capability registry`
5. `feat(lm): add FallbackProvider and ManagedProxyProvider`
6. `feat(platform): add settings storage and API endpoints`
7. `feat(platform): update provider factory to route by model name`
8. `test(lm): add unit tests for providers, registry, settings, fallback`

---

## Phase 2: Workflow Engine

**Goal:** Workflows can be saved, loaded, validated, and executed. The visual builder's JSON model maps cleanly to the existing DAG executor.

### 2.1 Workflow Data Model

**File:** `packages/agentos/agentos/schemas/workflow.py` (new)

The bridge between the visual builder's JSON and the DAG executor:

```python
class WorkflowNodeConfig(BaseModel):
    """Configuration for a single agent node in a workflow."""
    model: str
    system_prompt: str = ""
    persona_preset: str = "analytical"
    tools: list[str] = []
    budget: BudgetSpec = BudgetSpec()
    advanced: AdvancedModelConfig | None = None

class WorkflowNode(BaseModel):
    """A node in the visual workflow graph."""
    id: str
    role: str                    # Role name or "custom"
    display_name: str
    position: dict[str, float]   # {x, y} for canvas placement
    config: WorkflowNodeConfig

class DataContract(BaseModel):
    """Schema contract for data flowing between nodes."""
    output_schema: dict | None = None   # JSON Schema
    input_schema: dict | None = None    # JSON Schema

class WorkflowEdge(BaseModel):
    """A connection between two nodes."""
    source: str                  # Node ID
    target: str                  # Node ID
    data_contract: DataContract | None = None

class WorkflowVariable(BaseModel):
    """A workflow-level input variable."""
    name: str
    type: str = "string"
    default: Any = None

class WorkflowDefinition(BaseModel):
    """Complete workflow definition (serializable to JSON)."""
    id: str = Field(default_factory=lambda: generate_run_id())
    name: str
    description: str = ""
    version: str = "1.0.0"
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    variables: list[WorkflowVariable] = []
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    template_source: str | None = None  # Template ID this was cloned from
```

### 2.2 Workflow Validation Engine

**File:** `packages/agentos/agentos/runtime/workflow_validator.py` (new)

Validates a WorkflowDefinition before execution:

```python
class ValidationError(BaseModel):
    node_id: str | None
    edge_id: str | None
    severity: str  # "error" | "warning"
    message: str

def validate_workflow(
    workflow: WorkflowDefinition,
    available_tools: set[str],
    available_models: set[str],
) -> list[ValidationError]:
    """Validate workflow structure and configuration.

    Checks:
    - No cycles in the graph
    - All edge sources/targets reference valid nodes
    - All node tool references exist in available_tools
    - All node model references exist in available_models
    - No orphaned nodes (nodes with no edges, except single-node workflows)
    - Budget specs are valid (positive values)
    - Data contracts have valid JSON Schema
    - At least one node exists
    """
```

### 2.3 Workflow → DAG Compiler

**File:** `packages/platform/agentplatform/workflow_compiler.py` (new)

Converts a WorkflowDefinition into executable DAGWorkflow + TaskNodes:

```python
def compile_workflow(
    workflow: WorkflowDefinition,
    domain_registry: DomainRegistry,
    event_log: EventLog,
    workspace: Workspace,
    provider_factory: Callable[[str], BaseLMProvider],
    stop_event: threading.Event,
) -> DAGWorkflow:
    """Compile a visual workflow definition into an executable DAG.

    For each node:
    1. Resolve model → provider via factory
    2. Resolve tools from domain registry
    3. Build AgentRunner with budget manager
    4. Create TaskNode with proper dependencies from edges

    Returns a DAGWorkflow ready for DAGExecutor.run()
    """
```

### 2.4 Workflow CRUD API

**File:** `packages/platform/agentplatform/workflow_store.py` (new)

Filesystem-based workflow persistence:

```python
class WorkflowStore:
    """Save/load workflows as JSON files on the local filesystem."""

    def __init__(self, base_dir: str = "~/.agentos/workflows"): ...
    def save(self, workflow: WorkflowDefinition) -> None: ...
    def load(self, workflow_id: str) -> WorkflowDefinition: ...
    def list(self) -> list[WorkflowSummary]: ...
    def delete(self, workflow_id: str) -> None: ...
    def clone(self, workflow_id: str) -> WorkflowDefinition: ...
```

**API endpoints** (add to `server.py`):

```
POST   /api/workflows              → save workflow
GET    /api/workflows              → list workflows
GET    /api/workflows/:id          → get workflow by ID
PUT    /api/workflows/:id          → update workflow
DELETE /api/workflows/:id          → delete workflow
POST   /api/workflows/:id/clone    → clone workflow (returns new ID)
POST   /api/workflows/:id/run      → compile + create session + start
```

### 2.5 Inter-Agent Data Contracts

**File:** `packages/agentos/agentos/runtime/data_contracts.py` (new)

Validation layer between agent outputs and inputs:

```python
def validate_output(output: str, schema: dict) -> ValidationResult:
    """Validate agent output against a JSON Schema data contract."""

def compress_for_context(
    text: str,
    max_tokens: int,
    model: str,
    provider: BaseLMProvider,
) -> str:
    """Compress text to fit within token budget.

    Strategy:
    1. If text fits, return as-is
    2. If text is JSON, extract key fields only
    3. Otherwise, summarize using the same model
    """
```

### 2.6 Context Window Manager

**File:** `packages/agentos/agentos/lm/context_manager.py` (new)

Manages token budgets for agent prompts:

```python
class ContextManager:
    """Manages the context window budget for an agent."""

    def __init__(self, model: str, capabilities: ModelCapabilities): ...

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count (tiktoken for OpenAI, approximate for others)."""

    def build_prompt(
        self,
        system_prompt: str,
        tool_schemas: list[dict],
        upstream_output: str,
        conversation_history: list[LMMessage],
        memory_context: str | None = None,
    ) -> list[LMMessage]:
        """Assemble prompt within context window budget.

        Priority (highest first):
        1. System prompt (never trimmed)
        2. Tool schemas (never trimmed)
        3. Current upstream output (compressed if needed)
        4. Recent conversation history (sliding window)
        5. Memory context (trimmed first)
        """

    def available_tokens(self) -> int:
        """Remaining tokens after system prompt and tool schemas."""
```

### 2.7 Update Orchestrator

**File:** `packages/platform/agentplatform/orchestrator.py` (modify)

Add a new method to run workflows from WorkflowDefinition (alongside the existing session-based flow):

```python
def create_session_from_workflow(
    self, workflow: WorkflowDefinition, task_description: str = ""
) -> str:
    """Create and prepare a session from a WorkflowDefinition."""
```

### Tests for Phase 2

| Test File | Tests | Description |
|-----------|-------|-------------|
| `tests/unit/test_workflow_definition.py` | ~6 | Pydantic validation, serialization roundtrip |
| `tests/unit/test_workflow_validator.py` | ~8 | Cycle detection, orphans, missing tools/models, schema validation |
| `tests/unit/test_workflow_compiler.py` | ~5 | Compile to DAG, dependency mapping, tool resolution |
| `tests/unit/test_workflow_store.py` | ~6 | Save, load, list, delete, clone |
| `tests/unit/test_data_contracts.py` | ~5 | Schema validation, compression, edge cases |
| `tests/unit/test_context_manager.py` | ~6 | Token estimation, priority-based assembly, overflow handling |
| `tests/integration/test_workflow_api.py` | ~6 | CRUD endpoints, run endpoint |

### Commits for Phase 2

1. `feat(schemas): add WorkflowDefinition data model`
2. `feat(runtime): add workflow validation engine`
3. `feat(platform): add WorkflowStore with filesystem persistence`
4. `feat(platform): add workflow compiler (WorkflowDefinition → DAG)`
5. `feat(runtime): add inter-agent data contracts and context window manager`
6. `feat(platform): add workflow CRUD and run API endpoints`
7. `feat(platform): update orchestrator for workflow-based sessions`
8. `test(platform): add unit and integration tests for workflow engine`

---

## Phase 3: Tools & Integrations

**Goal:** Agents have access to web search, code execution, HTTP requests, Google Workspace, and Slack.

### 3.1 Core Tool Package

Create a new package for platform-level tools that aren't domain-specific:

**Location:** `packages/platform/agentplatform/tools/` (new directory)

This keeps core tools separate from domain packs (LabOS, CodeOS) while making them available to all workflows.

### 3.2 Web Search Tool

**File:** `packages/platform/agentplatform/tools/web_search.py` (new)

```python
class WebSearchTool(BaseTool):
    """Search the web using Brave Search or Google Custom Search API."""
    name = "web_search"
    side_effect = SideEffect.READ

    # Input: query, max_results, search_engine ("brave" | "google")
    # Output: list of {title, url, snippet}
    # Requires API key in settings
```

### 3.3 Code Execution Tool

**File:** `packages/platform/agentplatform/tools/code_execute.py` (new)

```python
class CodeExecuteTool(BaseTool):
    """Execute Python or Node.js code in a sandboxed subprocess."""
    name = "code_execute"
    side_effect = SideEffect.WRITE

    # Input: language ("python" | "node"), code, timeout_seconds
    # Output: stdout, stderr, exit_code, timed_out
    # Security: subprocess with resource limits, restricted filesystem
    # Uses workspace directory for file I/O
```

Implementation: `subprocess.run()` with `timeout`, `cwd` set to workspace. On Linux, use `resource.setrlimit()` for memory caps. Restricted PATH, no network access from sandbox.

### 3.4 HTTP Request Tool

**File:** `packages/platform/agentplatform/tools/http_request.py` (new)

```python
class HTTPRequestTool(BaseTool):
    """Make HTTP requests to external APIs."""
    name = "http_request"
    side_effect = SideEffect.READ  # or WRITE depending on method

    # Input: method, url, headers, body, timeout
    # Output: status_code, headers, body, elapsed_ms
```

### 3.5 File List Tool

**File:** `packages/platform/agentplatform/tools/file_list.py` (new)

```python
class FileListTool(BaseTool):
    """List files in a directory with metadata."""
    name = "file_list"
    side_effect = SideEffect.READ

    # Input: path, pattern (glob), recursive
    # Output: list of {name, path, size, modified, type}
```

Note: `file_read` and `file_write` already exist in CodeOS. For platform tools, either re-export from CodeOS or create lightweight wrappers that work without CodeOS's workspace enforcement.

### 3.6 Google Workspace Integration

**File:** `packages/platform/agentplatform/tools/google/` (new directory)

**Auth:** `google/auth.py` — OAuth2 flow using `google-auth` + `google-auth-oauthlib`. Stores refresh token in settings. Endpoint: `GET /api/integrations/google/auth` → redirect to Google OAuth.

**Tools:**

| File | Tool Class | Name | Side Effect |
|------|-----------|------|-------------|
| `google/gmail.py` | `GmailReadTool` | `gmail_read` | READ |
| `google/gmail.py` | `GmailSendTool` | `gmail_send` | WRITE |
| `google/sheets.py` | `GoogleSheetsReadTool` | `google_sheets_read` | READ |
| `google/sheets.py` | `GoogleSheetsWriteTool` | `google_sheets_write` | WRITE |
| `google/docs.py` | `GoogleDocsReadTool` | `google_docs_read` | READ |
| `google/docs.py` | `GoogleDocsWriteTool` | `google_docs_write` | WRITE |
| `google/drive.py` | `GoogleDriveListTool` | `google_drive_list` | READ |
| `google/drive.py` | `GoogleDriveDownloadTool` | `google_drive_download` | READ |

**Dependencies:** `google-api-python-client`, `google-auth`, `google-auth-oauthlib` (add to optional deps group `integrations`).

### 3.7 Slack Integration

**File:** `packages/platform/agentplatform/tools/slack.py` (new)

| Tool Class | Name | Side Effect |
|-----------|------|-------------|
| `SlackPostTool` | `slack_post` | WRITE |
| `SlackReadTool` | `slack_read` | READ |

**Auth:** Bot token or user token stored in settings. Uses `slack_sdk` package.

**Dependencies:** `slack-sdk` (add to optional deps group `integrations`).

### 3.8 Integration Auth API

**File:** `packages/platform/agentplatform/server.py` (modify)

```
GET  /api/integrations                    → list connected integrations + status
GET  /api/integrations/google/auth        → initiate OAuth2 flow
GET  /api/integrations/google/callback    → OAuth2 callback
POST /api/integrations/slack/connect      → save Slack bot token
DELETE /api/integrations/{name}/disconnect → remove integration
```

### 3.9 Register Platform Tools

**File:** `packages/platform/agentplatform/_domain_manifests.py` (modify)

Add platform tools to all domain pack manifests so they're available in every workflow:

```python
PLATFORM_TOOLS = [
    ToolManifestEntry(name="web_search", ...),
    ToolManifestEntry(name="code_execute", ...),
    ToolManifestEntry(name="http_request", ...),
    ToolManifestEntry(name="file_list", ...),
    ToolManifestEntry(name="file_read", ...),
    ToolManifestEntry(name="file_write", ...),
    ToolManifestEntry(name="gmail_read", ...),
    ToolManifestEntry(name="gmail_send", ...),
    ToolManifestEntry(name="google_sheets_read", ...),
    ToolManifestEntry(name="google_sheets_write", ...),
    ToolManifestEntry(name="google_docs_read", ...),
    ToolManifestEntry(name="google_docs_write", ...),
    ToolManifestEntry(name="google_drive_list", ...),
    ToolManifestEntry(name="google_drive_download", ...),
    ToolManifestEntry(name="slack_post", ...),
    ToolManifestEntry(name="slack_read", ...),
]
```

### Tests for Phase 3

| Test File | Tests | Description |
|-----------|-------|-------------|
| `tests/unit/test_web_search_tool.py` | ~4 | Mock API responses, error handling |
| `tests/unit/test_code_execute_tool.py` | ~6 | Success, timeout, stderr, security limits |
| `tests/unit/test_http_request_tool.py` | ~4 | GET/POST, headers, timeout |
| `tests/unit/test_file_list_tool.py` | ~4 | List, glob pattern, recursive |
| `tests/unit/test_google_tools.py` | ~8 | Mock Google API for each tool |
| `tests/unit/test_slack_tools.py` | ~4 | Mock Slack API for post/read |
| `tests/integration/test_integrations_api.py` | ~4 | Auth endpoints, connection status |

### Commits for Phase 3

1. `feat(tools): add web search tool with Brave/Google API`
2. `feat(tools): add sandboxed code execution tool`
3. `feat(tools): add HTTP request and file list tools`
4. `feat(tools): add Google Workspace integration (Gmail, Sheets, Docs, Drive)`
5. `feat(tools): add Slack integration (post, read)`
6. `feat(platform): add integration auth API endpoints`
7. `feat(platform): register platform tools in domain manifests`
8. `test(tools): add unit tests for all platform tools`

---

## Phase 4: Frontend — Visual Builder

**Goal:** Users can build agent workflows via drag-and-drop, configure agents with the persona studio, and save/load workflows.

### 4.1 Dependencies

Add to `frontend/package.json`:
```json
{
  "@xyflow/react": "^12",
  "@tanstack/react-query": "^5",
  "react-router-dom": "^7"
}
```

### 4.2 New API Client Functions

**File:** `frontend/src/api/client.ts` (modify)

```typescript
// Workflow CRUD
export function listWorkflows(): Promise<WorkflowSummary[]>
export function getWorkflow(id: string): Promise<WorkflowDefinition>
export function saveWorkflow(workflow: WorkflowDefinition): Promise<void>
export function deleteWorkflow(id: string): Promise<void>
export function cloneWorkflow(id: string): Promise<WorkflowDefinition>
export function runWorkflow(id: string): Promise<{ session_id: string }>

// NL Generation
export function generateWorkflow(description: string, model?: string): Promise<WorkflowDefinition>

// Settings
export function getSettings(): Promise<PlatformSettings>
export function updateSettings(settings: Partial<PlatformSettings>): Promise<void>

// Integrations
export function listIntegrations(): Promise<IntegrationStatus[]>

// Models (enhanced)
export function listModels(): Promise<ModelInfo[]>
export function getModelCapabilities(model: string): Promise<ModelCapabilities>
```

### 4.3 TypeScript Types

**File:** `frontend/src/api/types.ts` (modify)

Add types matching the backend workflow model, settings, and model capabilities.

### 4.4 Visual Builder Page

**File:** `frontend/src/pages/WorkflowBuilder.tsx` (new)

The main canvas page. Layout:

```
┌─────────────────────────────────────────────────────────┐
│ Toolbar: [Save] [Run] [Undo] [Redo] [Validate] [Name]  │
├────────┬────────────────────────────────┬───────────────┤
│ Node   │                                │ Config Panel  │
│ Palette│    React Flow Canvas            │ (Persona      │
│        │                                │  Studio)      │
│ ──── │    [Agent Nodes + Edges]        │               │
│ Roles  │                                │ Simple Mode   │
│ from   │                                │ - Name        │
│ pack   │                                │ - Behavior    │
│        │                                │ - Preset      │
│ ──── │                                │ - Model       │
│ Custom │                                │ - Tools       │
│ Agent  │                                │               │
│        │                                │ Advanced Mode │
│        │                                │ - Temperature │
│        │                                │ - System prmpt│
│        │                                │ - Few-shot    │
├────────┴────────────────────────────────┴───────────────┤
│ Status bar: [Validation: OK] [Nodes: 4] [Edges: 3]     │
└─────────────────────────────────────────────────────────┘
```

**Key components within this page:**

### 4.5 Node Palette Component

**File:** `frontend/src/components/builder/NodePalette.tsx` (new)

- Lists available role templates from the selected domain pack
- Draggable items that drop onto the canvas
- "Custom Agent" option for freeform agents
- Search/filter for roles

### 4.6 Agent Node Component

**File:** `frontend/src/components/builder/AgentNode.tsx` (new)

Custom React Flow node:
- Role icon + display name
- Model badge
- Tool count indicator
- Status indicator (valid/invalid)
- Click → opens config panel

### 4.7 Config Panel (Persona Studio)

**File:** `frontend/src/components/builder/ConfigPanel.tsx` (new)

Right-side panel that appears when a node is selected:

**Simple mode:**
- Role name (editable)
- Behavior instructions (textarea)
- Personality preset (dropdown: Formal, Creative, Analytical, Concise, Friendly)
- Model selector (dropdown from available models, shows context window + cost)
- Tool permissions (checkboxes)

**Advanced mode (toggle):**
- Temperature slider
- Max output tokens slider
- System prompt editor (monospace textarea)
- Few-shot examples (add/remove pairs)

### 4.8 Workflow Toolbar

**File:** `frontend/src/components/builder/Toolbar.tsx` (new)

- Workflow name (editable inline)
- Save button (calls workflow CRUD API)
- Run button (saves + creates session + navigates to dashboard)
- Undo/Redo buttons
- Validate button (shows validation errors)
- Delete button (with confirmation)

### 4.9 Updated Routing

**File:** `frontend/src/App.tsx` (modify)

```typescript
<Routes>
  <Route path="/" element={<Home />} />                          // Template gallery
  <Route path="/workflows/:id/edit" element={<WorkflowBuilder />} />
  <Route path="/workflows/new/describe" element={<NLCreator />} />
  <Route path="/sessions/:id" element={<SessionDashboard />} />
  <Route path="/sessions" element={<SessionHistory />} />
  <Route path="/settings" element={<Settings />} />
</Routes>
```

### Tests for Phase 4

Frontend tests using Vitest + React Testing Library:

| Test File | Tests | Description |
|-----------|-------|-------------|
| `frontend/src/__tests__/WorkflowBuilder.test.tsx` | ~6 | Canvas renders, nodes draggable, edges connectable |
| `frontend/src/__tests__/ConfigPanel.test.tsx` | ~5 | Simple/advanced toggle, model selector, tools |
| `frontend/src/__tests__/NodePalette.test.tsx` | ~3 | Lists roles, drag interaction |

### Commits for Phase 4

1. `feat(frontend): add React Flow dependency and workflow TypeScript types`
2. `feat(frontend): add visual workflow builder canvas with node palette`
3. `feat(frontend): add agent node component with drag-drop`
4. `feat(frontend): add persona studio config panel (simple + advanced)`
5. `feat(frontend): add toolbar with save/run/validate actions`
6. `feat(frontend): update routing for builder, NL creator, settings`
7. `test(frontend): add component tests for builder`

---

## Phase 5: Frontend — Templates, NL Creator, Settings, Polish

**Goal:** Template gallery as the landing page, NL workflow creation, settings for API keys, and session dashboard improvements.

### 5.1 Template Gallery (Home Page Redesign)

**File:** `frontend/src/pages/Home.tsx` (new, replaces DomainPicker)

Layout:
```
┌─────────────────────────────────────────────────────────┐
│ AgentOS    [My Workflows ▾]  [Sessions]  [Settings]  ⚙  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  How would you like to start?                           │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │ 📝 Describe It   │  │ 🎨 Build from    │             │
│  │ Tell us what you  │  │    Scratch       │             │
│  │ need in plain     │  │ Open the visual  │             │
│  │ English           │  │ builder          │             │
│  └──────────────────┘  └──────────────────┘             │
│                                                         │
│  ── Or start from a template ──                         │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ File     │ │ Research │ │ Content  │ │ Code     │  │
│  │ Organizer│ │ Report   │ │ Pipeline │ │ Review   │  │
│  │          │ │          │ │          │ │          │  │
│  │ 3 agents │ │ 4 agents │ │ 3 agents │ │ 3 agents │  │
│  │ ~$0.05   │ │ ~$0.30   │ │ ~$0.20   │ │ ~$0.15   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Email    │ │ Data     │ │ Meeting  │ │ Competitor│  │
│  │ Summary  │ │ Analysis │ │ Notes    │ │ Analysis │  │
│  │ ...      │ │ ...      │ │ ...      │ │ ...      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────┘
```

- Click template → clone into visual builder
- Click "Describe It" → navigate to NL creator
- Click "Build from Scratch" → open empty builder

### 5.2 Template JSON Files

**Location:** `packages/platform/agentplatform/templates/` (new directory)

8 workflow template JSON files matching the `WorkflowDefinition` schema. Pre-configured with:
- Agent nodes with roles, models, system prompts, tools
- Edges defining execution order
- Sensible budget defaults

Templates loaded by a new API endpoint:
```
GET /api/templates → list available templates
GET /api/templates/:id → get template definition
```

### 5.3 NL Workflow Creator Page

**File:** `frontend/src/pages/NLCreator.tsx` (new)

Layout:
```
┌─────────────────────────────────────────────────────────┐
│ Describe Your Agent Team                                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  What do you want your agents to do?                    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ I need a team that researches a topic online,   │    │
│  │ writes a detailed report with citations, and    │    │
│  │ has a reviewer check everything before          │    │
│  │ delivering the final document.                  │    │
│  │                                                 │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Model for generation: [GPT-4o ▾]                       │
│                                                         │
│  [Generate Workflow →]                                  │
│                                                         │
│  ── Generated Workflow Preview ──                       │
│  (Shows a read-only React Flow preview of the DAG)      │
│  (Agent count, estimated cost, tools used)               │
│                                                         │
│  [Open in Builder]  [Regenerate]                        │
└─────────────────────────────────────────────────────────┘
```

### 5.4 NL Generation Backend

**File:** `packages/platform/agentplatform/nl_generator.py` (new)

```python
class WorkflowGenerator:
    """Generates WorkflowDefinition from natural language description."""

    def __init__(self, provider_factory, tool_catalog, model_catalog): ...

    def generate(self, description: str, model: str = "gpt-4o") -> WorkflowDefinition:
        """Generate a workflow from a natural language description.

        System prompt includes:
        - Available tools (names + descriptions)
        - Available models (names + capabilities + costs)
        - The WorkflowDefinition JSON schema
        - 3 example workflows (research, content, file organizer)

        Uses generate_structured() for reliable JSON output.
        Validates result before returning.
        """
```

**API endpoint:**
```
POST /api/workflows/generate
Body: { "description": "...", "model": "gpt-4o" }
Response: { "workflow": WorkflowDefinition, "explanation": "..." }
```

### 5.5 Settings Page

**File:** `frontend/src/pages/Settings.tsx` (new)

Layout:
```
┌─────────────────────────────────────────────────────────┐
│ Settings                                                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Model Providers                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ OpenAI    API Key: [sk-...****]  [Test] ✓ Connected │ │
│ │ Anthropic API Key: [sk-...****]  [Test] ✓ Connected │ │
│ │ Ollama    URL: [localhost:11434] [Test] ✓ Running   │ │
│ │ Managed   URL: [optional]                           │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Default Model: [gpt-4o-mini ▾]                          │
│                                                         │
│ Integrations                                            │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Google Workspace  [Connect]  ○ Not connected        │ │
│ │ Slack             [Connect]  ○ Not connected        │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Directories                                             │
│ Workspace: [~/.agentos/workspaces]                      │
│ Workflows: [~/.agentos/workflows]                       │
│                                                         │
│ [Save Settings]                                         │
└─────────────────────────────────────────────────────────┘
```

### 5.6 Workspace Artifact Browser

**File:** `frontend/src/components/ArtifactBrowser.tsx` (new)

Panel in the session dashboard that shows files produced during a run:
- Tree view of workspace directory
- Click file → preview contents (text, markdown rendered, images, CSV as table)
- Download individual files
- Uses new API endpoint: `GET /api/sessions/:id/artifacts`

### 5.7 Session Dashboard Upgrades

**File:** `frontend/src/pages/SessionDashboard.tsx` (modify)

- Add the artifact browser panel
- Improve agent detail view with full conversation history
- Add per-session cost display (tokens × model pricing)
- Better DAG visualization using React Flow (consistent with builder)

### 5.8 Navigation Header

**File:** `frontend/src/components/NavHeader.tsx` (new)

Persistent top nav across all pages:
- Logo / "AgentOS"
- Home (templates)
- My Workflows (list saved workflows)
- Sessions (history)
- Settings

### Tests for Phase 5

| Test File | Tests | Description |
|-----------|-------|-------------|
| `tests/unit/test_nl_generator.py` | ~5 | Mock LLM, validate output, error handling |
| `tests/unit/test_template_store.py` | ~4 | Load templates, list, not-found |
| `frontend/src/__tests__/Home.test.tsx` | ~4 | Templates render, click actions |
| `frontend/src/__tests__/NLCreator.test.tsx` | ~3 | Input, generate, preview |
| `frontend/src/__tests__/Settings.test.tsx` | ~3 | Load, save, test connection |

### Commits for Phase 5

1. `feat(frontend): redesign home page with template gallery`
2. `feat(platform): add workflow template store and API`
3. `feat(platform): add template JSON files (8 templates)`
4. `feat(platform): add NL workflow generator`
5. `feat(frontend): add NL workflow creator page`
6. `feat(frontend): add settings page with API key management`
7. `feat(frontend): add workspace artifact browser`
8. `feat(frontend): upgrade session dashboard with cost display and artifacts`
9. `feat(frontend): add navigation header`
10. `test(platform): add tests for NL generator and template store`

---

## Phase 6: Integration Testing & Polish

**Goal:** Everything works end-to-end. Templates are tuned. UX is polished.

### 6.1 End-to-End Test Suite

New E2E tests that exercise the full stack:

| Test | Description |
|------|-------------|
| Template → Run | Load Research Report template, run with mock provider, verify events + artifacts |
| Builder → Save → Load | Create workflow in builder, save, reload, verify fidelity |
| NL → Generate → Run | Generate workflow from description, validate structure, run |
| Multi-provider | Run same workflow with OpenAI mock and Anthropic mock, verify both work |
| Data contracts | Run pipeline with schema validation, verify compression when output too large |
| Error recovery | Primary model fails, verify fallback model succeeds |
| Settings persistence | Save API keys, restart server, verify keys loaded |
| Integration tools | Mock Google/Slack APIs, verify tools work in workflow |

### 6.2 Template Tuning

For each of the 8 templates:
- Verify system prompts produce good results with GPT-4o-mini (cheapest capable model)
- Tune budget defaults (tokens, tool calls, time)
- Verify data contracts between agents are correct
- Test with at least 2 different model providers

### 6.3 UX Polish

- Loading states for all async operations
- Error messages that non-technical users understand
- Empty states for template gallery, workflow list, session history
- Keyboard shortcuts for builder (Delete node, Ctrl+S save, Ctrl+Z undo)
- Responsive layout for smaller screens (not mobile, but laptop)
- Dark mode (if Tailwind dark mode is low effort)

### 6.4 Documentation

- `README.md` update with quickstart instructions
- `docs/QUICKSTART.md` — install, configure API key, run first workflow
- `--help` flag on the server entry point

### Commits for Phase 6

1. `test(e2e): add end-to-end tests for full workflow lifecycle`
2. `fix(templates): tune template prompts, budgets, and data contracts`
3. `feat(frontend): add loading states, error messages, empty states`
4. `feat(frontend): add keyboard shortcuts and UX polish`
5. `docs: update README and add quickstart guide`

---

## Dependency Graph

```
Phase 1: Multi-Provider Model Layer
    │
    ├── Phase 2: Workflow Engine (needs providers for compilation)
    │       │
    │       ├── Phase 4: Visual Builder (needs workflow CRUD API)
    │       │
    │       └── Phase 5: Templates, NL, Settings (needs workflow model + CRUD)
    │
    └── Phase 3: Tools & Integrations (needs settings for API keys)
                │
                └── Phase 5: Templates need tools to be available

Phase 6: Polish (needs all previous phases)
```

**Parallelization opportunity:** Phase 3 (Tools) and Phase 4 (Builder frontend) can run in parallel after Phase 2 is complete. Phase 5 depends on both.

```
Phase 1 ──→ Phase 2 ──→ Phase 3 (tools) ─────────→ Phase 6
                    └──→ Phase 4 (builder frontend) ──→ Phase 5 ──→ Phase 6
```

---

## Git Strategy

**Branch:** `feature/v0.0.1` off `dev`

Each phase is a set of commits on this branch. After Phase 6, merge to `dev`, then tag `v0.0.1-alpha` for testing. After testing, merge `dev` → `main` and tag `v0.0.1`.

Alternatively, each phase can be a separate feature branch merged into `dev`:
- `feature/v0.0.1-providers` (Phase 1)
- `feature/v0.0.1-workflow-engine` (Phase 2)
- `feature/v0.0.1-tools` (Phase 3)
- `feature/v0.0.1-builder` (Phase 4)
- `feature/v0.0.1-templates-nl` (Phase 5)
- `feature/v0.0.1-polish` (Phase 6)

---

## New Dependencies

### Python (pyproject.toml)

```toml
[project.optional-dependencies]
platform = [
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "wsproto>=1.2",
]
providers = [
    "openai>=1.30",
    "anthropic>=0.30",
    "tiktoken>=0.7",       # Token counting for OpenAI models
]
integrations = [
    "google-api-python-client>=2.100",
    "google-auth>=2.25",
    "google-auth-oauthlib>=1.2",
    "slack-sdk>=3.27",
]
all = [
    "agentos[platform,providers,integrations]",
]
```

### Frontend (package.json)

```json
{
  "dependencies": {
    "@xyflow/react": "^12.0.0",
    "@tanstack/react-query": "^5.0.0",
    "react-router-dom": "^7.0.0"
  },
  "devDependencies": {
    "vitest": "^2.0.0",
    "@testing-library/react": "^16.0.0"
  }
}
```

---

## File Count Summary

| Phase | New Files | Modified Files | Total |
|-------|-----------|---------------|-------|
| Phase 1 | ~10 | ~3 | ~13 |
| Phase 2 | ~7 | ~3 | ~10 |
| Phase 3 | ~12 | ~2 | ~14 |
| Phase 4 | ~8 | ~3 | ~11 |
| Phase 5 | ~12 | ~4 | ~16 |
| Phase 6 | ~4 | ~5 | ~9 |
| **Total** | **~53** | **~20** | **~73** |

---

## Success Criteria (Revisited)

When v0.0.1 is complete, this flow works:

1. `pip install -e ".[all]"` — installs all dependencies
2. `python -m agentplatform` — starts the server
3. `cd frontend && npm run dev` — starts the UI
4. Open `http://localhost:5173`
5. Enter OpenAI API key in Settings
6. Browse template gallery → pick "Research Report"
7. Workflow opens in the visual builder with 4 pre-configured agents
8. Change the writer's model to Claude Sonnet
9. Edit the researcher's behavior: "Focus on academic sources only"
10. Click "Run" → watch agents execute in the session dashboard
11. See the final report in the artifact browser
12. OR: Click "Describe It" → type a description → get a generated workflow → run it
13. OR: Click "Build from Scratch" → drag agents onto canvas → connect → configure → run

---

*This plan is the implementation contract for v0.0.1. Each phase produces a working, testable increment. Phases execute in order, with 3+4 parallelizable after Phase 2.*
