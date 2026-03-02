# AgentOS

A domain-agnostic cognitive execution substrate for multi-agent AI workflows.

AgentOS is a local-first platform where you build teams of AI agents through a visual DAG builder or pre-built templates, configure each agent's role and LLM provider, and monitor execution in real time.

## Architecture

```
Frontend (React + TypeScript)     ← Visual workflow builder, session dashboard
    │
    │  REST + WebSocket
    ▼
Platform API (FastAPI)            ← Sessions, workflows, templates, events
    │
    ▼
AgentOS Kernel (Python)           ← DAG execution, budget governance, event log
    │
    ├── LabOS (research domain)   ← ML experiment replication tools
    └── CodeOS (coding domain)    ← File ops, shell, git tools
```

**Core constraint**: AgentOS contains zero domain-specific logic. Domain packs (LabOS, CodeOS) register tools and workflows via public interfaces only.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An LLM provider (Ollama for local, or OpenAI/Anthropic API keys)

### Install

```bash
# Clone and install
git clone <repo-url> && cd AgentOS
pip install -e ".[dev,platform]"

# Install frontend
cd frontend && npm install && cd ..
```

### Run

```bash
# Terminal 1 — start the API server
python -m agentplatform

# Terminal 2 — start the frontend dev server
cd frontend && npm run dev
```

Open `http://localhost:5173` to access the platform.

### Usage

1. **Pick a template** from the Home page, or describe what you need in plain English, or build from scratch in the visual builder
2. **Configure agents** — set each agent's LLM model, system prompt, tools, and budget
3. **Run the workflow** — monitor execution in real-time with the session dashboard
4. **Review results** — check the event log, artifacts, and cost estimates

## Project Structure

```
packages/
  agentos/agentos/       Kernel: schemas, runtime, DAG, governance, event log
  labos/labos/           Lab Research domain: ML tools and workflows
  codeos/codeos/         Coding domain: file, shell, git tools
  platform/agentplatform/ Platform: API server, orchestrator, templates
frontend/                React + TypeScript web UI
tests/
  unit/                  Unit tests
  integration/           Integration tests
  e2e/                   End-to-end tests
docs/                    Design documents
```

## Key Concepts

- **Event-sourced execution** — all state changes are append-only events in SQLite
- **Budget-constrained cognition** — hard limits on tokens, tool calls, time, recursion depth
- **Typed tool interface** — tools are syscalls with Pydantic v2 schemas and side-effect classification
- **DAG-based workflows** — tasks form directed acyclic graphs with topological scheduling
- **Domain packs** — pluggable domain modules that register tools and role templates

## Development

```bash
# Run all offline tests
pytest -m "not network" tests/

# Run specific test suites
pytest tests/unit/ -v
pytest tests/integration/platform/ -v
pytest tests/e2e/platform/ -v

# Frontend type check and build
cd frontend && npx tsc --noEmit && npx vite build
```

### Git Workflow

- **GitFlow**: `main` → `dev` → `feature/*`
- **Commits**: Conventional format — `feat(scope): ...`, `fix(scope): ...`, `test(scope): ...`

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Kernel | Python 3.11+, Pydantic v2, SQLite |
| API | FastAPI, uvicorn, WebSocket |
| Frontend | React 18, TypeScript, Vite, React Flow, Tailwind CSS |
| Testing | pytest, httpx (TestClient) |

## License

See LICENSE file for details.
