# Week 0 Spike Findings

**Date:** 2026-03-02
**Branch:** `feature/week0-spikes`
**Status:** Complete — all three spikes answered, decision gates passed

---

## Spike 1: Claude Code CLI Integration Surface

**Goal:** Determine if Claude Code can be orchestrated programmatically.

**Result: 10/10 — PROCEED with Tier 2 adapter.**

### Test Results

| Run | Status | Time (s) | JSON Output | File Created |
|-----|--------|----------|-------------|--------------|
| 0   | OK     | 6.74     | Yes         | hello.py     |
| 1   | OK     | 6.05     | Yes         | hello.py     |
| 2   | OK     | 6.24     | Yes         | hello.py     |
| 3   | OK     | 5.94     | Yes         | hello.py     |
| 4   | OK     | 6.21     | Yes         | hello.py     |
| 5   | OK     | 6.69     | Yes         | hello.py     |
| 6   | OK     | 6.76     | Yes         | hello.py     |
| 7   | OK     | 6.41     | Yes         | hello.py     |
| 8   | OK     | 7.92     | Yes         | hello.py     |
| 9   | OK     | 9.84     | Yes         | hello.py     |

- **Mean execution time:** 6.88s
- **Programmatic termination:** Clean (SIGTERM, returncode -15)

### Questions Answered

| Question | Answer | Notes |
|----------|--------|-------|
| Headless launch? | Yes | `claude --print` works reliably, no TTY needed |
| Task input method? | `-p` flag | Positional args do NOT work — must use `-p "task"` |
| Structured JSON output? | Yes | `--output-format json` — all 10 runs parsed successfully |
| Token monitoring? | Yes | JSON output includes usage metrics |
| Programmatic termination? | Yes | `subprocess.terminate()` returns cleanly (SIGTERM) |
| Consistency? | Yes | 10/10 identical behavior, 5.9–9.8s range |
| Rate limits? | None observed | No 429s or auth failures across 10 sequential runs |

### Discoveries for Tier 2 Adapter

These must be encoded in `agentos/adapters/tier2_claude_code.py` (Phase 2, weeks 9-10):

1. **Prompt flag:** Use `-p "task description"`, not a bare positional argument. The CLI errors with "Input must be provided either through stdin or as a prompt argument when using --print" if the task is passed as a positional arg.

2. **Anti-nesting guard:** Claude Code sets a `CLAUDECODE` environment variable. Child `claude` processes inherit it and refuse to start ("Claude Code cannot be launched inside another Claude Code session"). The adapter must strip `CLAUDECODE` from the subprocess environment:
   ```python
   env = os.environ.copy()
   env.pop("CLAUDECODE", None)
   ```

3. **Tool scoping works:** `--allowedTools Write,Read` successfully restricts available tools — this maps directly to AgentOS capability grants.

4. **Overhead is acceptable:** ~6-7s per simple task. This includes CLI startup, API round-trip, and file write. For real tasks (research, implementation), the API time will dominate and this overhead becomes negligible.

---

## Spike 2: Task Output Schema v0.1

**Goal:** Produce a concrete Pydantic schema for structured inter-agent handoffs.

**Result: Schema finalized and validated.**

### Implementation

File: `agentos/schemas/task.py`

Models implemented:
- `TaskStatus` (StrEnum): pending, running, succeeded, failed, waiting
- `Confidence` (StrEnum): high, medium, low
- `Finding`: finding text + confidence + sources
- `FileReference`: path + description + role (primary/supporting/log)
- `TaskMetrics`: tokens_consumed, api_calls_made, execution_time_seconds, estimated_cost_usd
- `TaskOutput`: full manifest with schema_version, task_id, agent_id, status, summary, key_findings, files_produced, open_questions, metrics, timestamp

### Validation

- 16 unit tests covering round-trip serialization for 3 task types (research, implementation, failed)
- All models serialize cleanly to JSON and deserialize back with full fidelity
- Default values work correctly (schema_version="0.1", empty lists, auto-timestamp)

### Design Notes

- `TaskOutput.timestamp` uses naive `datetime.now()` (local time) — differs from Event timestamps which use UTC. This is intentional: task output is agent-authored, events are system-authored.
- `TaskMetrics` defaults all fields to 0/0.0 — allows partial reporting by agents that don't track all metrics.
- The `WAITING` status (new in V1) supports gate-blocked tasks without overloading `PENDING`.

---

## Spike 3: Event Schema + SeqCounter

**Goal:** Design the event envelope, all V1 event types, and fix V0's sequence counter bug.

**Result: Schema finalized, DDL validated against SQLite, SeqCounter thread-safe.**

### Event Schema

File: `agentos/schemas/events.py`

- 15 event types covering all V1 subsystems (workflow, task, agent, gate, budget, file, security, error)
- `Event` model with envelope fields: event_id (UUID), event_type, workflow_id, seq (>=0), timestamp (UTC), schema_version, payload (dict), metadata (dict)
- `EVENT_TABLE_DDL` constant with CREATE TABLE + 3 indexes + UNIQUE(workflow_id, seq)
- DDL uses `IF NOT EXISTS` / `IF NOT EXISTS` for idempotent initialization

### SeqCounter

File: `agentos/kernel/seq.py`

- Thread-safe via `threading.Lock`
- `next()` returns current value and increments atomically
- `current` property for read-only access without incrementing
- Accepts custom `start` value for resumed workflows

### Validation

- 14 unit tests for event schema (round-trip, auto-generated UUIDs, UTC timestamps, payload variations, seq non-negative constraint, DDL structure)
- 7 unit tests for SeqCounter (basic counting, custom start, thread safety with 50 threads x 100 calls = 5000 unique values, monotonicity, no gaps)
- DDL tested against in-memory SQLite: table creation, event insertion, and query-back all work

### Cross-Spike Consistency Check

Per the Week 0 exit gate requirement: `task.output_produced` event payload references `output_path` (path to the TaskOutput manifest.json). The TaskOutput schema includes `files_produced` with workspace-relative paths. These are consistent — the event points to the manifest, and the manifest lists all files. No gaps that would force a redesign.

---

## Test Summary

| Suite | Tests | Result |
|-------|-------|--------|
| Schema round-trips (task + event) | 30 | All pass |
| SeqCounter (correctness + thread safety) | 7 | All pass |
| **Total** | **37** | **All pass** |

---

## Decision Summary

| Spike | Decision | Impact on Plan |
|-------|----------|----------------|
| Spike 1 (Claude Code CLI) | **PROCEED** — 10/10 | Tier 2 adapter confirmed for Phase 2 (weeks 9-10). No contingency needed. |
| Spike 2 (Task Output) | **LOCKED** | `TaskOutput` schema is the contract for all downstream components. |
| Spike 3 (Event + Seq) | **LOCKED** | Event schema + SeqCounter ready for Sprint 1 (EventLog + StateMachine). |

**Week 0 is complete. Phase 1 Sprint 1 (Event Log + Task State Machine) can begin.**
