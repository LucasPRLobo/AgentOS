# Token Efficiency & Output Quality — Plan

## The Two Problems

### Problem 1: Agents produce stubs, not working code

A 15-task workspace run consumed 30% of the Claude Code plan limit
and produced placeholder components ("will appear here"). The agents
spent most of their tokens reading files and exploring, then output
minimal actual code. The work/output ratio is terrible.

**Root causes:**
- Task descriptions are too vague: "Build the team chat view" doesn't
  specify what "build" means
- Agents spend 80% of turns reading context, 20% writing output
- No verification that output is substantive (our verifier checks
  for output existence, not quality)
- Agents don't have examples of what good output looks like
- The coordinator decomposes into too many tasks (15 tasks for one
  frontend → each task gets a thin slice)

### Problem 2: Token consumption is too high

~400-500K tokens per workspace run. With a Claude Code plan limit,
this means 2-3 runs per day maximum.

**Root causes:**
- Each agent reads the same files independently (mitigated by repo
  map, but agents still explore beyond the map)
- Coordinator decomposition reads the codebase (~50-100K)
- 15 tasks × ~25K tokens each = ~375K just on task execution
- DM responses and coordinator chat add ~50-100K
- Agents use opus for everything (even simple research tasks)

## Solutions

### A. Make agents produce real work (quality)

#### A1: Specific task prompts with output requirements

Instead of:
```
"Build the team chat view"
```

The task should say:
```
"Build the TeamChat component in src/pages/TeamChat.tsx.
It must:
1. Fetch messages via getMessages() from api/client.ts
2. Render messages in a scrollable list with sender name and timestamp
3. Include an input field that sends messages via sendMessage()
4. Auto-scroll to bottom on new messages
5. Show loading state while fetching

The component should be a complete, working implementation — NOT a
placeholder. If you can't implement a feature, document what's missing
and why in a comment."
```

**Implementation:** Modify the coordinator prompt to generate specific,
measurable task descriptions with explicit output requirements.

#### A2: Output quality verification

The current `TaskVerifier` checks:
- Output exists ✓
- Summary present ✓
- Spec alignment (keyword check) ✓

Add:
- **File size check**: If the task says "build a component", the output
  file should be >50 lines. A 10-line stub fails.
- **Placeholder detection**: Grep for "will appear here", "TODO",
  "placeholder", "coming soon" in output files. Flag as low quality.
- **Code validity**: For .tsx/.ts files, run `tsc --noEmit` to verify
  the code compiles.
- **Mandatory content check**: If the task spec says "must include
  scrollable list", check that the output contains scroll-related code.

**Implementation:** Extend `TaskVerifier.verify()` with content quality checks.

#### A3: Fewer, bigger tasks

15 tasks for one frontend is too many. Each task gets ~25K tokens but
produces thin output because the scope is narrow. Better:

- 3-5 substantial tasks instead of 15 thin ones
- Each task produces a complete, working feature (not just a file)
- The coordinator should aim for tasks that take 8-10 turns of real work,
  not tasks that take 3 turns of reading + 1 turn of writing a stub

**Implementation:** Update coordinator decomposition prompt:
"Create 3-5 substantial tasks, not 10-15 thin ones. Each task should
produce a complete, working feature. Prefer fewer tasks with more scope
over many tasks with thin scope."

#### A4: Example-driven output

Give agents an example of what good output looks like. In the task prompt:

```
"Here is an example of a well-implemented component for reference:

[include a real component from the codebase, e.g., Sidebar.tsx]

Your output should be at the same level of completeness — functional
code with real data fetching, not stubs."
```

**Implementation:** The `ContextCurator` can select a representative
example from the codebase based on the task type (React component →
include an existing good component).

### B. Reduce token consumption (efficiency)

#### B1: Model routing per task complexity

| Task Type | Model | Max Turns | Expected Tokens |
|---|---|---|---|
| Research (web search, read docs) | sonnet | 8 | ~15K |
| Design (write specs, plans) | sonnet | 8 | ~15K |
| Code (implement features) | opus | 10 | ~25K |
| Review (check output quality) | sonnet | 5 | ~10K |
| DM response | sonnet | 3 | ~5K |
| Coordinator response | sonnet | 5 | ~5K |

**Implementation:** The coordinator assigns a `model_tier` to each task.
The supervisor uses this when building the agent command. Already
partially implemented (model_tier field exists on BacklogTask) but
not wired to the agent launch.

#### B2: Coordinator decomposition without codebase access

The coordinator should decompose using ONLY the repo map + CLAUDE.md.
No `--add-dir`, no file reads. The map has everything it needs for
planning. This reduces coordinator decomposition from ~50-100K to ~10K.

**Implementation:** Remove `--add-dir` from coordinator decomposition
invocations. The repo map is already injected into the prompt.

#### B3: Strict turn limits per task type

Current: all tasks get 10-15 turns. Most agents spend the first 5 turns
reading files and the last 5 actually working.

New: tasks declare their expected turn count. The supervisor enforces it.

```python
# In BacklogTask:
max_turns: int = 8  # Set by coordinator based on task complexity
```

#### B4: Agent workspace pre-seeding

Instead of each agent discovering the project structure independently,
pre-seed the workspace with:
- CLAUDE.md (already done)
- repo-map.md (already done)
- Predecessor output summaries (already done via ContextCurator)
- **NEW:** Relevant code snippets pre-extracted and placed in workspace

Example: For "Build TeamChat component", pre-extract and place in the
workspace:
- `_context/existing_sidebar.tsx` — working example component
- `_context/api_types.ts` — relevant type definitions
- `_context/api_endpoints.txt` — relevant API endpoints

The agent reads these local files instead of exploring the codebase.

**Implementation:** Extend `ContextCurator` to extract and write relevant
code files to the workspace before agent launch.

#### B5: Cache-aware session management

With `--continue`, Claude Code caches the conversation. Each subsequent
turn is cheaper because the prefix is cached. But we currently kill and
restart for DM interrupts, which invalidates the cache.

Optimization: Don't interrupt agents for non-urgent DMs. Queue the DM
and deliver it when the agent finishes the current task. Only interrupt
for urgent/critical messages.

**Implementation:** Add priority-based interrupt logic:
```python
if msg.priority == "critical":
    self._interrupt_for_messages(agent)
elif msg.priority == "high":
    # Interrupt only if agent has been working >2 min
    if agent.elapsed > 120:
        self._interrupt_for_messages(agent)
else:
    # Queue — agent will see it on next task or check_messages
    pass
```

## Implementation Priority

| Fix | Impact | Effort | Priority |
|---|---|---|---|
| A3: Fewer, bigger tasks | HIGH | LOW (prompt change) | P0 |
| B1: Model routing | HIGH | LOW (wire existing field) | P0 |
| B2: No codebase access for coordinator | HIGH | LOW (remove --add-dir) | P0 |
| A1: Specific task prompts | HIGH | MEDIUM (prompt engineering) | P1 |
| B3: Strict turn limits | MEDIUM | LOW | P1 |
| A2: Output quality verification | MEDIUM | MEDIUM | P1 |
| B4: Workspace pre-seeding | MEDIUM | MEDIUM | P2 |
| A4: Example-driven output | MEDIUM | MEDIUM | P2 |
| B5: Cache-aware interrupts | LOW | LOW | P2 |

## Research-Backed Techniques (from papers + industry)

### Subprocess Isolation (40-60% base cost reduction)
Each Claude Code subprocess inherits ~50K tokens of config (CLAUDE.md,
plugins, MCP tools, user settings) per turn. Isolation via scoped cwd,
.git boundary, empty plugin dir reduces this to ~5K/turn.
Source: dev.to analysis of Claude Code subagent costs.

### AST-Based Stub Detection (catches 80-90% of placeholders)
Parse output code into AST, check for: `pass` bodies, `# TODO`,
`...` in function bodies, `NotImplementedError`, suspiciously short
implementations. No LLM call needed, runs in <0.2s.
Source: arxiv 2601.19106 (Hallucination Detection via Deterministic AST)

### Supervisor LLM-Free Filter (20-30% token reduction)
Check four conditions without an LLM call: agent completion, errors,
inefficient behavior (loops), excessive observation length (>3K chars).
Only invoke supervisor LLM when filter triggers.
Source: arxiv 2510.26585 (ICLR 2026)

### Code Minification for Context (42% input token reduction)
Strip comments, whitespace, formatting from reference files agents
read but don't edit. 12% drop in resolution rate (acceptable tradeoff
for context files).
Source: TU Wien thesis (Hrubec, 2025)

### Hierarchical Context Compression (80-94% payload reduction)
Instead of sending raw board/messages, compress in stages. Tool
definitions 2000→200 tokens, conversation history 1000→150 tokens.
Source: Medium engineering posts on production LLM optimization.

### Task Decomposition for Quality (23.79% Pass@1 improvement)
Tasks need: explicit file scope, testable acceptance criteria,
reference implementations, forbidden zones. AgentCoder pattern:
separate programmer + test designer + test executor.
Source: codegen.com, Amazon Science, arxiv 2312.13010

### Compaction Tuning (20-40% more useful work per context)
Claude Code auto-compacts at 75-85% of context window. Tune via
CLAUDE_AUTOCOMPACT_PCT_OVERRIDE env var per agent role.
Source: Claude Code documentation.

## Expected Impact

| Metric | Current | After P0 fixes | After all fixes |
|---|---|---|---|
| Tasks per workspace | 10-15 | 3-5 | 3-5 |
| Tokens per task | ~25K | ~15K (sonnet) | ~8-12K |
| Coordinator decomposition | ~50-100K | ~10K | ~10K |
| Base cost per agent turn | ~50K | ~5K (isolated) | ~5K |
| Total per run | ~400-500K | ~100-150K | ~50-80K |
| Plan usage per run | ~30% | ~10% | ~5% |
| Output quality | Stubs | Working code | Verified working code |
| Stub detection | None | AST-based | AST + quality gates |
