# AgentOS Platform — Feature Ideation

> Outcome of the ideation session. Captures all decisions, feature definitions, and priorities before the development plan.

---

## Decisions Summary

| Area | Decision |
|------|----------|
| Target users | Non-technical individuals + technical power users |
| First experience | Templates gallery + natural language workflow description |
| Deployment | Cloud SaaS (primary) |
| Model access | All: BYOK API keys, managed access, local models (Ollama) |
| Agent configuration | Layered: plain English default + advanced toggle |
| Agent communication | Pipeline data flow + shared workspace + direct messaging |
| Error handling | Auto-retry + human approval gates + LLM-as-judge auto-scoring |
| Flow control | Full: branching, loops, sub-workflows, dynamic agent spawning |
| Sharing model | Team workspaces (private) + public marketplace |
| Integrations at launch | Broad: web, files, productivity suite, developer stack |
| Real-time collaboration | View-only sharing (owner edits, others monitor) |
| Cost tracking | Detailed per-agent breakdown with historical trends |
| Agent memory | Persistent memory + uploadable knowledge base |
| Monetization | Freemium with credits system |
| Scheduling | Scheduled (cron) + event-driven triggers |
| Branding | Decide later — focus on building first |

---

## Feature Definitions

### 1. Visual Workflow Builder

The centerpiece of the product. A drag-and-drop canvas where users design agent workflows as directed graphs.

**Core capabilities:**
- **Agent nodes** — Drag from a palette onto the canvas. Each node represents an agent role.
- **Connection edges** — Draw edges to define execution order and data flow.
- **Click to configure** — Select any node to open its configuration panel.
- **Full flow control** — Support for:
  - Linear sequences (A → B → C)
  - Parallel fan-out (A → [B, C, D] → E)
  - Conditional branching (if reviewer rejects → loop back to writer)
  - Loops with exit conditions (retry up to N times or until quality threshold met)
  - Sub-workflows (nest a workflow inside another workflow as a single node)
  - Dynamic agent spawning (workflow decides at runtime to create additional agents)
- **Zoom, pan, minimap** — Navigate large workflows.
- **Undo/redo** — Full history of canvas operations.
- **Workflow validation** — Real-time checks: no cycles (except explicit loops), all required connections present, agent configs valid.

**Data model:**
```
Workflow {
  id, name, description, version
  nodes: [{ id, role, position, config }]
  edges: [{ source, target, condition?, label? }]
  variables: [{ name, type, default }]  // workflow-level inputs
}
```

### 2. Natural Language Workflow Creation

Users describe what they want in plain English. An LLM generates a workflow.

**Flow:**
1. User types: *"I need a team that researches a topic, writes a report, and has a reviewer check it."*
2. System generates:
   - Agent nodes with roles, system prompts, and suggested models
   - DAG connections in logical order
   - Recommended tools per agent
   - Budget estimates per agent
3. Generated workflow appears in the visual builder
4. User reviews, adjusts, and launches

**Implementation approach:**
- Use a capable LLM (GPT-4 / Claude) as the "workflow architect"
- Output structured JSON matching the workflow data model
- Include refinement loop: "Would you like to add a quality check step?" / "Should the researcher search the web or use uploaded documents?"
- Pre-built prompt templates for common patterns accelerate generation

### 3. Template Gallery

Pre-built workflow templates users can browse, preview, clone, and customize.

**Template categories:**
- **Content & Marketing** — Blog pipeline, social media scheduler, SEO optimizer
- **Research & Analysis** — Literature review, competitor analysis, data analysis
- **Engineering** — Code review, PR summary, test generation, documentation
- **Operations** — Ticket triage, meeting→action items, email responder
- **Personal** — File organizer, inbox manager, note summarizer

**Template structure:**
- Title, description, preview image/diagram
- Pre-configured agent roles and connections
- Customization points highlighted: "Change the model here", "Edit the writing style here"
- Estimated cost per run
- Community rating and usage count (for marketplace templates)

### 4. Agent Persona Studio

**Simple mode (default):**
- Behavior instructions in plain English: "Be thorough and cite sources. Format as markdown. Never make up statistics."
- Personality presets: Formal, Creative, Analytical, Concise, Friendly
- Role description: what this agent does and what it produces

**Advanced mode (toggle):**
- Temperature slider (0.0–2.0)
- Max output tokens
- Top-p / frequency penalty
- Few-shot examples: "When you see input like X, respond like Y"
- System prompt editor (raw text)
- Stop sequences
- Response format constraints (JSON schema, markdown structure)
- Tool permissions: which tools this agent can access, with confirmation toggles for destructive tools

**Reusable personas:**
- Save a configured agent as a named persona: "My Strict Financial Analyst"
- Drag personas into any workflow
- Version personas — track changes over time
- Share personas within team workspace or publish to marketplace

**Test sandbox:**
- Chat with a configured agent in isolation
- Verify behavior before putting it in a live workflow
- Send test inputs and inspect outputs
- Swap models to compare behavior

### 5. Agent Communication System

Three layers of communication between agents:

**Layer 1: Pipeline data flow (default)**
- Each agent's output becomes the next agent's input
- Structured handoff: output of phase N is injected into the prompt of phase N+1
- Supports typed data: text, JSON, file references

**Layer 2: Shared workspace**
- Agents read/write to a shared file workspace
- File-based artifact passing: reports, data files, code, images
- Each agent can see what others produced
- Workspace browser in the UI shows all artifacts

**Layer 3: Direct messaging**
- Agent-to-agent messages via the event log
- Broadcast messages (all agents) or targeted (specific agent)
- Use cases: status updates, clarification requests, coordination
- Messages appear in the monitoring dashboard

### 6. Error Handling & Quality Control

**Auto-retry:**
- On parse errors or tool failures, retry with adjusted prompt (up to N times)
- Exponential backoff for rate limits
- Automatic fallback: if primary model fails, try backup model
- Notification to user if all retries exhausted

**Human approval gates:**
- Mark any edge in the DAG as "requires human approval"
- Agent completes work → user reviews → approve/reject/edit → next agent starts
- Approval can happen in-app, via email link, or Slack button
- Configurable timeout: auto-approve after X minutes if no response

**LLM-as-judge auto-scoring:**
- Separate evaluator LLM scores each agent's output on configurable dimensions:
  - Accuracy, completeness, clarity, relevance, formatting
- Configurable thresholds: score < 6/10 → auto-retry, score < 4/10 → escalate to human
- Quality scores visible in the dashboard per agent per run
- Historical quality trends across sessions

### 7. Integrations

**Tier 1 — Core (built-in):**
- Web search (Brave/Google/Bing API)
- File operations (read, write, organize)
- Code execution (sandboxed Python/Node)
- HTTP/REST API calls

**Tier 2 — Productivity suite:**
- Google Workspace: Sheets, Docs, Drive, Gmail
- Microsoft 365: Excel, Word, OneDrive, Outlook
- Slack: send messages, read channels, post to threads
- Notion: read/write pages and databases
- Email: send/receive via SMTP/IMAP

**Tier 3 — Developer stack:**
- GitHub: PRs, issues, code search, actions
- Jira: create/update tickets, sprint boards
- Databases: PostgreSQL, MySQL, MongoDB (read/write with guardrails)
- REST/GraphQL: generic API connector with auth

**No-code tool builder:**
- Point at any REST API: provide URL, auth method, request/response schema
- Describe what the API does in plain English
- System generates a tool definition agents can use
- Test the tool before adding it to workflows

**Community tool marketplace:**
- Users publish custom tools and integrations
- Browse, install, rate, and review
- Verified/certified tools badge for quality assurance

### 8. Live Monitoring & Dashboard

**Session monitoring view:**
- Real-time DAG visualization: nodes color-coded by state (pending/running/done/failed)
- Click any node to see that agent's live output, tool calls, and reasoning
- Elapsed time, estimated time remaining
- Stop/pause/resume controls

**Agent detail panel:**
- Current state: idle, thinking, tool call, writing
- Step counter: "Step 5 of max 50"
- Budget usage bars: tokens, tool calls, time
- Last tool call with input/output
- Full message history (LLM conversation thread)

**Event log:**
- Scrollable, filterable, searchable
- Color-coded by event type
- Filter by agent, event type, severity
- Export as JSON or CSV

**Cost dashboard:**
- Per-agent cost breakdown
- Per-model cost comparison
- Per-tool-call cost attribution
- Historical trends across sessions
- Budget alerts: email/Slack when spending exceeds threshold

### 9. Agent Memory & Knowledge Base

**Persistent memory (per agent):**
- Agents can optionally retain learnings across sessions
- Key-value memory store: agent writes facts it wants to remember
- Memory is injected into agent's context at the start of each session
- Users can view, edit, and delete agent memories
- Memory capacity limits to prevent unbounded growth

**Knowledge base (per workspace/team):**
- Upload documents: PDFs, Word docs, text files, CSVs
- Automatic chunking and embedding for RAG retrieval
- Agents query the knowledge base as a tool
- Supports versioning: update documents, old versions archived
- Access controls: which agents/workflows can access which knowledge bases
- Usage tracking: which documents were retrieved, how often

### 10. Scheduling & Triggers

**Scheduled runs:**
- Cron-style scheduling: daily, weekly, monthly, custom
- Time zone aware
- Calendar view of upcoming and past scheduled runs
- Pause/resume schedules

**Event-driven triggers:**
- Webhook receiver: external systems trigger workflow runs
- Email trigger: new email matching rules → start workflow
- File watcher: new file in a connected drive folder → start workflow
- API polling: check an endpoint periodically, trigger on change
- GitHub events: new PR, issue created, push to branch

**Trigger configuration:**
- Input mapping: how trigger data becomes workflow input
- Deduplication: don't re-run for the same trigger event
- Rate limiting: max N runs per hour/day
- Notification on trigger: email/Slack when a scheduled or event-driven run starts

### 11. Sharing & Marketplace

**Team workspaces:**
- Create organizations with invited members
- Shared workflows, personas, knowledge bases within the team
- Role-based access: Admin, Editor, Viewer
- Activity feed: who ran what, when, with what results
- Shared cost tracking across the team

**Public marketplace:**
- Publish workflows, personas, tools, and templates
- Categories and search
- Ratings, reviews, usage counts
- Free and paid listings (creator sets price)
- Revenue share: platform takes 20-30% commission
- Verified publisher badges
- Version history and changelogs

### 12. Cost & Credits System

**Freemium model:**
- **Free tier**: X credits/month (enough for ~20-30 simple sessions)
- **Pro tier** ($25-40/mo): 10x credits, priority model access, team features
- **Team tier** ($15-25/user/mo): shared workspace, admin controls, audit logs
- **Enterprise**: custom pricing, SLA, SSO, dedicated support

**Credit system:**
- Credits are the universal currency
- Different models cost different credits per token (GPT-4 costs more than Llama 3)
- Tool calls cost credits based on type (web search > file read)
- Users see credit balance and burn rate in real-time
- Buy additional credit packs on demand
- BYOK users pay reduced credits (platform fee only, no model cost)
- Monthly credit rollover (up to 2x monthly allocation)

### 13. View-Only Sharing & Monitoring

**Share a running session:**
- Generate a shareable link for any session
- Viewers see live DAG, event log, and agent status
- No editing — read-only observation
- Useful for demos, stakeholder reviews, debugging with colleagues

**Session replay:**
- Past sessions are fully replayable (event-sourced)
- Step through events one by one
- Scrub timeline forward/backward
- See agent reasoning at each step

---

## Feature Prioritization

### MVP (Launch)

Must-have features for the initial launch:

| Feature | Rationale |
|---------|-----------|
| Visual workflow builder (linear + parallel) | Core product. Users need to see and build workflows visually. |
| Template gallery (5-10 templates) | Fastest path to value. Users start from a template, not a blank canvas. |
| NL → workflow generation | Key differentiator. "Describe your team" is the magic moment. |
| Agent persona studio (simple mode) | Users must configure agent behavior. Plain English is the minimum. |
| Pipeline data flow + shared workspace | Agents need to communicate. Pipeline + files covers 90% of use cases. |
| Live monitoring dashboard | Users need to see what's happening. Core trust-building feature. |
| Per-session cost tracking | Users need to know what they're spending. |
| Web search + file ops + code execution | Minimum useful tool set for agents. |
| BYOK model access (OpenAI, Anthropic) | Users bring their own API keys. Simplest to implement. |
| User accounts + auth | Multi-user SaaS requires accounts. |
| Freemium + credits (basic) | Monetization from day one. |

### Phase 2 (Post-Launch)

| Feature | Rationale |
|---------|-----------|
| Conditional branching + loops | Power users need flow control. |
| Advanced persona studio | Temperature, few-shot, test sandbox. |
| Approval gates (human-in-the-loop) | Quality control for high-stakes workflows. |
| Productivity integrations (Slack, Google, Email) | Expand what agents can do. |
| Team workspaces | Multi-user collaboration. |
| Detailed cost breakdown (per-agent) | Cost optimization. |
| Scheduled runs (cron) | Recurring workflows. |
| Agent persistent memory | Agents learn across sessions. |

### Phase 3 (Growth)

| Feature | Rationale |
|---------|-----------|
| Full flow control (sub-workflows, dynamic spawn) | Complex enterprise workflows. |
| LLM-as-judge auto-scoring | Automated quality assurance. |
| Public marketplace | Community growth engine. |
| Event-driven triggers | Full automation. |
| Knowledge base (RAG) | Agents work with user's own data. |
| Developer integrations (GitHub, Jira, DBs) | Technical user segment. |
| No-code tool builder | Users create custom integrations. |
| Direct agent messaging | Advanced coordination. |
| Session replay + comparison | Debugging and optimization. |
| View-only sharing | Demos and stakeholder reviews. |
| Managed model access | Revenue from model routing margin. |
| Local model support (Ollama) | Privacy-conscious users. |

---

## Demo Workflows

Concrete demonstrations to showcase the platform's value:

### Demo 1: File Organizer (Simplest — MVP)
**Audience:** Anyone with a messy computer.

3 agents:
1. **Scanner** — Lists all files in a directory with metadata
2. **Classifier** — Categorizes files and proposes folder structure
3. **Organizer** — Renames and moves files into organized directories

**Why:** Tangible, relatable, visible results. Non-technical people immediately get it.

### Demo 2: Research Report (Knowledge Worker — MVP)
**Audience:** Analysts, consultants, researchers.

4 agents:
1. **Researcher** — Searches web, collects key findings
2. **Analyst** — Identifies patterns, draws conclusions
3. **Writer** — Produces structured report with citations
4. **Reviewer** — Checks accuracy, completeness, flags issues

### Demo 3: Content Pipeline (Marketing — Phase 2)
**Audience:** Marketing teams, content creators.

4 agents:
1. **Trend Scout** — Scans competitors, identifies trending topics
2. **Writer** — Drafts blog post / social media content
3. **Editor** — Refines tone, grammar, brand voice
4. **SEO Optimizer** — Keywords, meta descriptions, readability score

### Demo 4: Code Review (Engineering — Phase 2)
**Audience:** Development teams.

3 agents:
1. **Architect** — Reads PR diff, assesses structural impact
2. **Reviewer** — Line-by-line code review for bugs and style
3. **Summarizer** — Produces concise review comment with categorized findings

### Demo 5: Meeting → Action Items (Operations — Phase 3)
**Audience:** Project managers, team leads.

3 agents:
1. **Transcriber** — Processes meeting notes/transcript
2. **Extractor** — Identifies action items, decisions, owners, deadlines
3. **Dispatcher** — Creates Jira tickets, sends Slack messages

---

## Open Questions (To Resolve During Development)

1. **Workflow versioning** — How do we handle version history? Git-like branching for workflows? Or simpler "save as copy"?

2. **Credit pricing** — How many credits per token for each model? Need competitive analysis. Credits should abstract away model pricing complexity.

3. **Sandbox security** — Code execution tool needs robust sandboxing. Container-per-execution? WASM? Firecracker?

4. **Knowledge base scale** — How much document storage per user? Embedding compute cost? RAG retrieval latency targets?

5. **Model routing** — For managed model access, do we route through a single provider (e.g., OpenRouter) or build direct integrations?

6. **Mobile experience** — Is a mobile app needed at launch? Or responsive web + push notifications sufficient?

7. **Offline/local-first** — Some users want everything local (data privacy). How much of the platform works without cloud? (Deferred — Cloud SaaS first.)

8. **Agent testing framework** — How do users validate that their agent configuration works correctly before deploying to production workflows?

9. **Rate limiting** — How to handle concurrent sessions per user? Free tier limits? Burst capacity?

10. **Data retention** — How long do we keep session data, event logs, and workspace artifacts? Configurable per plan?

---

## Knowledge Graphs — Deep Exploration

> Outcome of a dedicated exploration session evaluating how knowledge graphs fit into the AgentOS platform. Covers use cases, technology choices, architecture, and a phased integration plan.

### Why Knowledge Graphs Matter for AgentOS

Traditional agent memory (key-value stores, embedding-based retrieval) can recall *facts* but cannot reason about *relationships*. A knowledge graph stores entities and the connections between them — enabling agents to answer questions like "What sources have I used before for this topic?" or "Which findings contradict each other?" that flat memory cannot.

For a multi-agent platform, knowledge graphs unlock:
- **Cross-session learning** — agents accumulate structured knowledge over time
- **Information provenance** — trace any claim back to its source through the graph
- **Relational reasoning** — agents understand how entities connect, not just what they are
- **Shared understanding** — multiple agents read/write a common knowledge structure

### Five Integration Points

#### 1. Agent Memory Graph (replaces key-value memory)

Instead of flat facts, agents build entity-relationship graphs across sessions.

**Example — after 10 Research Report runs:**
```
(Company: Tesla) --[competitor_of]--> (Company: Rivian)
(Source: Reuters) --[reliability: 0.95]--> (Topic: EV Market)
(Source: BlogX) --[reliability: 0.3]--> (Topic: EV Market)
(Finding: "EV sales grew 40%") --[supported_by]--> (Source: Reuters)
```

Follows the **AriGraph** architecture (IJCAI 2025): combines semantic memory (entity-relation triples) with episodic memory (specific observations linked to semantic nodes via episodic edges). The **Zep/Graphiti** bitemporal model adds temporal awareness — facts have event time (when it happened) and ingestion time (when observed), enabling point-in-time queries and fact supersession.

**Value:** Agents get smarter over time. Switching cost becomes very high — your knowledge graph doesn't export to a competitor. This is the primary moat.

**Complexity:** Medium-high. LLM-based entity extraction adds cost. Entity resolution (deduplication) across runs is hard. Start with structured outputs first, add LLM extraction later.

#### 2. GraphRAG Knowledge Base

When users upload documents, build both embeddings (vector search) AND a knowledge graph (entity-relationship extraction). Combine both for retrieval.

**How it works:**
1. Document upload → chunk + embed (standard RAG)
2. Also extract entities and relationships from chunks → build knowledge graph
3. Agent query → vector similarity finds relevant chunks + graph traversal finds connected entities
4. Merged results fed to agent

**Research backing:** Microsoft GraphRAG (arXiv 2404.16130) shows up to 35% precision improvement over vector-only retrieval. **LightRAG** (EMNLP 2025) achieves this with faster, cheaper implementation and supports incremental graph updates without full reindexing.

**Value:** Better retrieval quality, especially for multi-hop questions ("Which authors published on both X and Y?"). Vector search alone cannot answer relational questions.

**Complexity:** High at ingestion time (LLM extraction is expensive). Low at query time (graph traversal is fast). Amortized cost is acceptable since ingestion happens once per document.

#### 3. Workflow Provenance Graph

Track information lineage through workflows. Every claim in the final output traces back to its source.

```
(WebSearch: "EV market") --> (Source: Reuters) --> (Agent: Researcher)
    --> (Finding: "sales grew 40%") --> (Agent: Writer) --> (Section: "Overview")
        --> (Agent: Reviewer) [approved] --> (Report: final.md)
```

**Value:** Trust, auditability, compliance. Click any statement → see the full chain. This is what makes the platform usable for real business work, not just demos.

**Complexity:** Low — this is a derived view on top of the existing event log. No new data collection needed, just a graph query layer.

#### 4. Platform Intelligence Graph (long-term)

Aggregate anonymized usage data across all users to learn what works.

```
(Model: GPT-4o) --[best_for]--> (Role: Writer) [quality: 8.5]
(Template: Research Report) --[improved_by]--> (Adding: "reviewer agent")
```

**Value:** Network effects. More users → smarter recommendations for everyone. VCs love data flywheels.

**Complexity:** Requires scale (thousands of users). Privacy-sensitive. Target for post-launch.

#### 5. Cross-Agent Entity Resolution

Maintain a shared entity graph so all agents in a workflow refer to the same concepts consistently.

**Value:** Conceptually elegant — prevents agents from treating "AI in healthcare" and "artificial intelligence in medicine" as different things.

**Complexity:** Very high for free-text outputs. The inter-agent data contracts (v0.0.1) solve the practical version of this. Full entity resolution is a research problem.

### Technology Recommendations

#### Embedded Graph Database: Kuzu

| Criterion | Kuzu |
|-----------|------|
| Install | `pip install kuzu` |
| Query language | Cypher (industry standard) |
| Storage | File-backed directory (like SQLite) |
| Performance | 280M nodes, 1.7B edges tested; 18x faster ingestion than Neo4j |
| Vector search | Built-in (as of v0.11.3) |
| Full-text search | Built-in extension |
| License | MIT |
| Python bindings | First-class, typed |

**Why Kuzu over alternatives:**
- **vs Neo4j**: Embeddable (no server), MIT license, faster ingestion. Neo4j is better at scale but requires JVM server process.
- **vs CozoDB**: Cypher is widely known; Datalog (CozoDB's query language) is niche. Both are embeddable with vector search.
- **vs SQLite recursive CTEs**: Far more expressive for graph queries. SQLite graph support is alpha-quality.
- **vs NetworkX**: Kuzu persists to disk and has a query language. NetworkX is in-memory only.

**Fits AgentOS architecture:** File-backed (like SQLite event log), runs in-process, no external server. A Kuzu database directory sits alongside the SQLite event log in the workspace.

#### GraphRAG Pipeline: LightRAG

For the GraphRAG knowledge base feature, use **LightRAG** (EMNLP 2025) or its predecessor **nano-graphrag**:
- ~1,100 lines of code — simple, hackable, fully typed
- Incremental graph updates (no full reindexing)
- Faster and cheaper than Microsoft's GraphRAG
- Can be adapted to use Kuzu as the graph backend

#### Agent Memory Architecture: Zep/Graphiti Pattern

Follow the **Graphiti** architecture (arXiv 2501.13956) for agent memory:
- **Bitemporal model**: facts track event time + ingestion time
- **Incremental updates**: new observations update the graph without recomputation
- **Fact supersession**: new facts can replace old ones with provenance trail
- **18.5% accuracy improvement** over MemGPT on Deep Memory Retrieval benchmark

Graphiti currently requires Neo4j as backend. The AgentOS version would adapt this pattern to use Kuzu instead.

### Phased Integration Roadmap

#### v0.0.2 — Plant the Seeds
- Add `KnowledgeStore` abstraction to the kernel with a triple-store interface
- Backend: SQLite tables (`entities`, `relations`, `triples`) with recursive CTEs for basic traversal
- Triples come from structured agent outputs only (no LLM extraction yet)
- API surface: `add_triple()`, `query()`, `traverse(start, depth)`

#### v0.0.3 — Agent Memory Graph
- Add Kuzu as the graph backend (replace SQLite triples)
- LLM-based entity and relationship extraction from agent outputs
- Entity resolution (deduplication) using embedding similarity
- Memory injection: relevant graph context loaded into agent prompts at session start
- Follow AriGraph's episodic + semantic memory model
- UI: simple graph viewer showing what agents have learned
- Bitemporal fact tracking (Graphiti pattern)

#### v0.0.4 — GraphRAG Knowledge Base
- Document upload → chunking + embedding + graph extraction pipeline
- Hybrid retrieval: Kuzu graph traversal + vector similarity
- LightRAG-style incremental updates when documents change
- Access controls: which agents/workflows can query which knowledge bases

#### v0.0.5+ — Provenance + Intelligence
- Provenance graph derived from event log (low-cost, high-value)
- Platform intelligence graph (requires user scale)
- Cross-user analytics (anonymized)
- Workflow optimization recommendations from graph patterns

### What NOT to Do

1. **Don't build a custom graph database.** Use Kuzu. Graph DBs are deep infrastructure.
2. **Don't make knowledge graphs mandatory.** Opt-in per workflow. Simple workflows (file organizer) don't need graphs.
3. **Don't impose a fixed ontology.** Let graphs be freeform triples. Users and agents define their own entity types.
4. **Don't extract from every token.** Extract from structured outputs first (cheap). Use LLM extraction only for unstructured text and only when enabled.
5. **Don't start with GraphRAG.** Start with simple memory triples (v0.0.2), add graph DB (v0.0.3), then GraphRAG (v0.0.4).

### Key Research References

| Paper/Project | Relevance |
|--------------|-----------|
| **AriGraph** (IJCAI 2025) — arXiv 2407.04363 | Episodic + semantic memory graph for LLM agents |
| **Zep/Graphiti** (Jan 2025) — arXiv 2501.13956 | Bitemporal knowledge graph for agent memory, 18.5% improvement |
| **Microsoft GraphRAG** (Apr 2024) — arXiv 2404.16130 | Reference GraphRAG implementation with community detection |
| **LightRAG** (EMNLP 2025) | Lightweight GraphRAG, incremental updates, cost-efficient |
| **KARMA** (2025) | Multi-agent collaborative knowledge graph enrichment |
| **Kuzu** — github.com/kuzudb/kuzu | MIT embedded graph DB with Cypher + vector search |

---

*This document captures the ideation session outcomes and will inform the development plan.*
