# AgentOS Platform — Quickstart Guide

This guide walks you through installing, running, and using the AgentOS platform.

## 1. Installation

### System Requirements

- Python 3.11 or higher
- Node.js 18 or higher (for the frontend)
- An LLM provider — one of:
  - **Ollama** (local, free) — recommended for getting started
  - **OpenAI API key** — set `OPENAI_API_KEY` env var
  - **Anthropic API key** — set `ANTHROPIC_API_KEY` env var

### Install Python Dependencies

```bash
cd AgentOS

# Core + development tools + platform server
pip install -e ".[dev,platform]"
```

### Install Frontend

```bash
cd frontend
npm install
cd ..
```

## 2. Configure a Model Provider

Open the platform, go to **Settings**, and configure at least one provider:

### Option A: Ollama (Local)

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1:latest
```

In Settings, add the Ollama provider with base URL `http://localhost:11434`.

### Option B: OpenAI

In Settings, add the OpenAI provider with your API key.

### Option C: Anthropic

In Settings, add the Anthropic provider with your API key.

## 3. Start the Platform

You need two terminals:

```bash
# Terminal 1 — API server (port 8420)
python -m agentplatform

# Terminal 2 — Frontend dev server (port 5173)
cd frontend
npm run dev
```

Open your browser to `http://localhost:5173`.

## 4. Your First Workflow

### From a Template

1. On the Home page, browse the template gallery
2. Click a template (e.g., "Research Report") to instantiate it
3. The visual builder opens with pre-configured agents
4. Review the agent prompts and tools, adjust models if needed
5. Click **Run** to start the workflow
6. Watch execution in the session dashboard

### From Natural Language

1. Click **Describe It** on the Home page
2. Type what you want: e.g., "A team that analyzes a CSV file, finds patterns, and writes a summary report"
3. Select a model and click **Generate Workflow**
4. Review the generated agents, then click **Open in Builder**
5. Fine-tune and run

### From Scratch

1. Click **Build from Scratch** on the Home page
2. Drag role templates from the left palette onto the canvas
3. Connect agents by drawing edges between them
4. Click each node to configure its system prompt, model, tools, and budget
5. Click **Validate** to check the workflow
6. Click **Run** to start

## 5. Monitoring Execution

The Session Dashboard shows:

- **DAG visualization** — agent phases with color-coded status (gray=pending, blue=running, green=done, red=failed)
- **Event log** — real-time stream of all events (filterable)
- **Artifacts tab** — files produced by agents during execution
- **Cost estimates** — token usage and tool call counts
- **Stop button** — gracefully stop a running session

## 6. Available Templates

| Template | Agents | Description |
|----------|--------|-------------|
| Research Report | 4 | Researcher, Analyst, Writer, Reviewer |
| Data Analysis | 3 | Data Loader, Statistician, Report Writer |
| Content Pipeline | 3 | Outliner, Drafter, Editor |
| Code Review | 3 | Diff Analyzer, Code Reviewer, Summarizer |
| Competitor Analysis | 4 | Scout, Deep Diver, Comparator, Strategist |
| File Organizer | 3 | Scanner, Categorizer, Organizer |
| Meeting Notes | 2 | Extractor, Formatter |
| Email Summary | 2 | Email Reader, Digest Writer |

## 7. API Reference

The platform API runs on `http://localhost:8420`. Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/packs` | List domain packs |
| GET | `/api/packs/{name}` | Get pack details |
| GET | `/api/templates` | List workflow templates |
| POST | `/api/templates/{id}/instantiate` | Create workflow from template |
| POST | `/api/workflows` | Save a workflow |
| GET | `/api/workflows` | List saved workflows |
| POST | `/api/workflows/{id}/run` | Run a workflow |
| POST | `/api/workflows/generate` | Generate workflow from NL |
| GET | `/api/sessions` | List sessions |
| GET | `/api/sessions/{id}` | Get session details |
| GET | `/api/sessions/{id}/events` | Get session events |
| WS | `/ws/sessions/{id}/events` | Real-time event stream |

## 8. Keyboard Shortcuts

| Shortcut | Context | Action |
|----------|---------|--------|
| Ctrl+S / Cmd+S | Workflow Builder | Save workflow |
| Delete / Backspace | Workflow Builder | Delete selected node |

## 9. Running Tests

```bash
# All offline tests
pytest -m "not network" tests/

# Platform unit tests
pytest tests/unit/test_template_store.py tests/unit/test_nl_generator.py -v

# Platform integration tests
pytest tests/integration/platform/ -v

# Platform E2E tests
pytest tests/e2e/platform/ -v

# Frontend type check
cd frontend && npx tsc --noEmit
```
