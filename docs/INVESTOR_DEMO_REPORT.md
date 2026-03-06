# AgentOS — Live Demo Report

**For:** Investors and technical advisors
**Date:** March 6, 2026
**Author:** Lucas Lobo

---

## Executive Summary

This report documents two live workflow runs executed with AgentOS — a governance and orchestration platform for autonomous AI agents. Both workflows ran end-to-end with real Claude Code instances (no stubs, no mocks), demonstrating that AgentOS can coordinate multiple independent AI agents across different domains, enforce structured collaboration, and produce substantive, usable outputs.

| | News Aggregator | Quant Research Pipeline |
|--|----------------|------------------------|
| **Domain** | Journalism / editorial | Financial analysis |
| **Tasks** | 7 | 8 |
| **Agents** | 6 (5 workers + 1 manager) | 7 (5 workers + 1 manager + 1 reviewer) |
| **Teams** | 1 (editorial team) | 1 (research team) |
| **Wall time** | 14.5 min | 14 min (6.4 min compute + 7.8 min manager) |
| **Total cost** | ~$3.20 | ~$2.41 |
| **Result** | SUCCEEDED (7/7) | SUCCEEDED (8/8) |
| **Code executed** | No (research + writing) | Yes (Python: data fetch, Monte Carlo, charts) |

**Key takeaway:** Both pipelines completed without human intervention beyond topic input and approval gates. Every agent produced structured, high-quality output. The manager agents made independent delegation and quality-review decisions. No agent knew about AgentOS or the other agents — AgentOS handled all coordination invisibly.

---

## What AgentOS Does

AgentOS takes AI agents that already exist — Claude Code sessions, API-based models, any autonomous runtime — and makes them work together under structured workflows with:

- **DAG-based task scheduling** — parallel execution, fan-in/fan-out, conditional branching
- **Human-in-the-loop gates** — approval and input gates that pause execution for human decisions
- **Team-based delegation** — manager agents that plan, delegate, review quality, and reassign
- **Budget enforcement** — per-agent, per-team, per-workflow token and cost limits
- **Capability scoping** — each agent only has access to the tools it needs
- **Structured handoffs** — every agent produces a manifest.json that downstream agents consume
- **Complete audit trail** — append-only event log records every action, transition, and decision
- **Workflow resume** — restart from any task without re-running completed work

**It is not a prompt-chaining framework.** The agents are real running processes with their own tool access, file systems, and decision-making. AgentOS does not replace them. It coordinates them.

---

## Run 1: News Aggregator — Caso Banco Master

### Workflow Design

```
Human provides topic (input gate)
    → Topic curator scans web for key stories
        → Web researcher deep-dive ──┐  (parallel)
        → Social analyst sentiment ──┘
            → Human reviews research (approval gate)
                → Editor-in-chief (manager) delegates:
                    → fact_checker verifies claims
                    → copywriter drafts briefing
                    → editor reviews, consolidates
                        → Human final approval (approval gate)
```

### What Happened

**Topic:** "Caso Banco Master, Brasil" — a major ongoing financial scandal in Brazil involving R$12 billion in fraud, arrests, political implications, and systemic banking risk.

**Phase 1 — Research (parallel):**
The topic curator identified 8 key stories in 92 seconds, tagging each as BREAKING, DEVELOPING, or BACKGROUND. Two agents then ran in parallel:

- The **web researcher** (281s) produced a 221-line deep-dive report with primary sources from Bloomberg, AP, Reuters, and Brazilian press. It built a complete timeline from 2018 to March 2026, identified key figures, and documented the R$40+ billion financial hole.

- The **social analyst** (143s) found overwhelmingly negative public sentiment (70% anger/distrust), identified coordinated astroturfing campaigns, tracked comparisons to the Lava Jato scandal, and analyzed coverage across major Brazilian newspapers and international press.

**Phase 2 — Editorial production (manager delegation):**
The editor-in-chief read both research outputs, then delegated two parallel workstreams:

1. **Fact-checker** — verified 22 major claims against primary sources. Result: 14 "Likely Accurate", 6 "Unverified", 2 critical flags on STF minister allegations requiring independent verification. The fact-checker could not independently access some sources and noted this limitation transparently.

2. **Copywriter** — drafted a structured news briefing with headline, TL;DR, key developments, context, public reaction, what to watch, and sources.

The editor then reviewed both outputs, integrated the fact-checker's [UNVERIFIED] tags into the copywriter's draft, and produced the final 139-line briefing.

### Outputs Produced

| File | Lines | Description |
|------|-------|-------------|
| `sources.md` | 85 | 8 key stories with sources, URLs, priority tags |
| `research_report.md` | 221 | Deep-dive with primary sources, timeline, key figures |
| `sentiment_report.md` | 157 | Sentiment analysis by stakeholder, trajectory, narratives |
| `fact_check_report.md` | 273 | 22 claims verified with confidence ratings |
| `news_briefing_draft.md` | 169 | Copywriter's initial draft |
| `news_briefing.md` | 139 | **Final edited briefing with fact-check annotations** |

### Features Demonstrated

| Feature | How It Was Used |
|---------|----------------|
| **Input gate** | Human typed the topic; it was persisted and flowed to all downstream agents |
| **Parallel execution** | Web researcher + social analyst ran simultaneously (saved ~2.5 min) |
| **Fan-in** | Both research streams had to complete before editorial phase |
| **Manager delegation** | Editor-in-chief independently decided to assign fact-checking and copywriting in parallel |
| **Quality review** | Editor integrated fact-checker's flags into the final briefing |
| **Approval gates** | Human reviewed research before editorial phase, and final briefing before "publish" |
| **Structured handoffs** | Every agent read predecessor manifests to understand context |
| **Tool scoping** | Researchers had web_search; editor/copywriter had file_read/file_write only |

---

## Run 2: Quant Research Pipeline — TSLA Momentum Analysis

### Workflow Design

```
Human provides ticker + constraints (input gate)
    → Data engineer fetches market data via Python
        → Quant modeler runs simulations ──┐  (parallel)
        → Chart builder generates PNGs ────┘
            → Code reviewer re-runs and validates models
                → Human reviews computed artifacts (approval gate)
                    → Research director (manager) delegates:
                        → risk_analyst: risk assessment
                        → memo_writer: investment memo
                        → director reviews, finds inconsistency,
                          sends BOTH back for revision
                        → director approves revised outputs
                            → Human final approval (approval gate)
```

### What Happened

**Brief:** TSLA, 2-year period, momentum play thesis, max 3% position in $5M portfolio, 20% drawdown stop-loss.

**Phase 1 — Data collection (49s):**
The data engineer installed `yfinance`, fetched 502 trading days of TSLA data, computed returns/volatility/moving averages, and saved structured CSVs and JSON. All code was executed via `Bash` and outputs were verified programmatically.

**Phase 2 — Quantitative modeling (parallel):**

- The **quant modeler** (93s) wrote and executed Python scripts for:
  - Monte Carlo simulation: 10,000 price paths over 252 trading days. Result: median 12-month price $596, 74.7% probability above current price, P5/P95 range of $211–$1,655.
  - DCF valuation: 3 discount rate scenarios (8/10/12%). Fair value range: $13–$24 vs. current $399 — a 94–97% overvaluation flag.
  - Risk statistics: Sharpe 0.89, annualized volatility 62.6%, max drawdown -53.8%, VaR(95%) -5.3%, beta 1.93, excess kurtosis 4.71 (fat tails).

- The **chart builder** (64s) generated three publication-quality PNG charts:
  - Price history with 20/50/200-day moving average overlays
  - Returns distribution histogram with normal overlay and VaR lines
  - Rolling 30-day volatility over time

**Phase 3 — Code audit (124s):**
The code reviewer independently re-ran all models, then executed 19 validation checks:
- Monte Carlo: prices positive, percentiles ordered, simulation count correct
- Risk stats: Sharpe in reasonable range, VaR negative, volatility positive
- DCF: discount rates produce ordered valuations
- Cross-validation: metrics consistent across files

**Result: 19/19 checks PASSED.** Minor observations noted (Sortino approximation, VaR labeling).

**Phase 4 — Manager-led synthesis (469s, 2 rounds):**

The research director read all outputs and the workspace file index, then delegated:

**Round 1:** Assigned risk_analyst (risk assessment + position sizing) and memo_writer (investment memo) in parallel. Both read the model JSONs, code review report, and fundamentals.

**Round 2 (quality revision):** The director identified a **critical inconsistency** — the risk analyst's position sizing calculation and the memo writer's recommendation didn't align. The director sent both members back with specific revision instructions:
- Risk analyst: fix the haircut chain to arrive at 2–3% position (not the initial 10–15%)
- Memo writer: update the risk assessment section and position sizing to match

Both members revised their outputs. The director reviewed and approved the consolidated result.

### Computed Artifacts Produced

| File | Type | Description |
|------|------|-------------|
| `data/price_history.csv` | CSV | 502 rows of OHLCV + computed columns |
| `data/metrics.json` | JSON | Returns, volatility, moving averages, drawdown |
| `data/fundamentals.json` | JSON | P/E, market cap, margins, growth, beta |
| `models/monte_carlo.json` | JSON | 10K-path simulation results with percentiles |
| `models/dcf_valuation.json` | JSON | 3-scenario DCF with fair values |
| `models/risk_stats.json` | JSON | Sharpe, Sortino, VaR, drawdown, skew, kurtosis |
| `charts/price_history.png` | PNG | Price + MA overlays |
| `charts/returns_distribution.png` | PNG | Histogram + normal + VaR lines |
| `charts/volatility.png` | PNG | Rolling 30-day vol |
| `code_review_report.md` | MD | 19/19 validation checks |
| `risk_assessment.md` | MD | Risk rating: HIGH, position sizing framework |
| `investment_memo.md` | MD | **Final: HOLD, medium conviction, 2–3% allocation** |

### Features Demonstrated

| Feature | How It Was Used |
|---------|----------------|
| **Code execution** | 4 agents ran Python via Bash: data fetch, Monte Carlo, matplotlib, validation |
| **Computed outputs** | Real numbers: $596 median price, 62.6% vol, -53.8% drawdown, $13–24 DCF |
| **Chart generation** | 3 PNG files generated by matplotlib, verified non-empty |
| **Independent code audit** | Reviewer re-ran models and validated 19 numerical checks |
| **Manager with revision** | Director found inconsistency, sent both members back for a second round |
| **Parallel execution** | Quant modeling + chart generation ran simultaneously |
| **Structured data flow** | JSON model outputs flowed from data_engineer → quant_modeler → code_reviewer → risk_analyst |
| **Workspace file index** | Manager received a full file listing — no wasted turns exploring |

---

## What the Manager Pattern Demonstrated

The most significant architectural feature tested across both runs is the **manager-as-agent** pattern. The manager is not a router or keyword matcher — it's a real Claude Code instance that:

1. **Reads context** and decides what to delegate
2. **Assigns work** to specific team members with detailed instructions
3. **Reviews quality** of member outputs
4. **Identifies issues** and requests revisions
5. **Consolidates** the final output

### Evidence of Intelligent Supervision

**News run:** The editor-in-chief delegated fact-checking and copywriting in parallel, then integrated the fact-checker's [UNVERIFIED] tags into the final briefing — a judgment call about how to present uncertain claims.

**Quant run:** The research director found that the risk analyst recommended 10–15% position sizing while the memo writer used 2–3%. Rather than accepting the inconsistency, the director sent both back with specific instructions: "fix the haircut chain" and "update to match." Both members revised, and the final output was internally consistent.

This is not scripted. The manager LLM independently decided what was wrong and how to fix it. This is the core value proposition: **AI agents are already capable; what's missing is the infrastructure to make them work together with quality control.**

---

## Issues Encountered and Fixes Applied

### During Development (Before These Runs)

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Post-hoc verifier false positives | Workspace files flagged as unauthorized | Workspace files now implicitly authorized |
| Budget shows $0 for manager tasks | Member tokens not aggregated | Manager adapter now sums all member + planning metrics |
| Sandbox crashes without root | `unshare` requires CAP_SYS_ADMIN | Fallback detection at creation time; NoopSandbox with warning |
| Stale files on resume | Previous outputs confuse re-running agents | Clear re-executing task workspaces on resume |
| Gates lose context on resume | Input/approval gates didn't persist manifests | Gates now write manifest.json for replay |
| Sequence collision on resume | SeqCounter started at 0 with existing DB events | Resume reads last_seq from DB and continues from there |

### During These Runs

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| Web researcher + social analyst timed out (Run 1, attempt 1) | 120s timeout too short for deep web research | Increased agent timeouts to 300s |
| Manager failed in 40s (Quant, attempt 1) | max_turns=5 exhausted on filesystem exploration | Increased to max_turns=15; added workspace file index to planning prompt |
| Fact-checker intermittent web access | CC tool name recognition inconsistency | Agent recovered and produced report; tool expansion system handles most cases |

**Pattern:** Every failure was a configuration or plumbing issue, not an agent competence issue. When agents had the right tools, context, and time, they produced high-quality output every time.

---

## Architecture Decisions Open for Discussion

### 1. Manager Cost vs. Quality

The manager pattern adds 2–4 extra CC invocations per managed task (planning + member execution + review, potentially revision rounds). In the quant run, the manager phase cost $1.31 (54% of total) and took 469s. But it caught a real inconsistency and fixed it.

**Question:** Is intelligent quality review worth 2x the cost? Should there be a "light" mode where the manager delegates without reviewing?

### 2. Manifest Protocol Resilience

Every Tier 2 agent must write a `manifest.json` with a specific schema. This works well when agents comply (100% compliance in these runs), but the protocol depends on prompt instructions. If an agent fails to write a valid manifest, the task fails after 2 retries.

**Potential improvement:** Extract structure from the agent's natural output as a fallback — parse the last markdown file for summary and findings if manifest.json is missing.

### 3. Workspace Discovery

Agents still spend 1–3 turns discovering files via Glob. The workspace file index (added for managers) significantly reduced this. Extending it to all agents would eliminate guessing entirely.

### 4. Tool Scoping Enforcement

Tool restrictions are enforced via `--allowedTools` CLI flags, which is orchestration-layer enforcement. We observed one case where a CC instance appeared to use Bash despite it not being in the allowed list. For the governance positioning to hold in enterprise, sandbox-level enforcement (container isolation) needs to work reliably.

### 5. Gate Context Depth

Approval gates forward predecessor summaries, but context loses fidelity at each hop. The quant run's manager got a file index which compensated, but a universal "workspace artifact registry" would solve this systematically.

---

## What Ships Next

### Immediate (This Week)
- Run each workflow 5 times without intervention to establish reliability baseline
- Validate the Aider adapter with a code review workflow
- Add cost summary to CLI output (per-agent, per-team breakdown)

### Short Term (Next 2 Weeks)
- Workspace artifact browser: `agentos workspace browse <run-id>`
- Manifest extraction fallback (parse natural output if JSON fails)
- Workspace file index for all agents (not just managers)
- Getting Started guide + 3-minute demo video

### Medium Term
- Container-based sandbox enforcement (bubblewrap or Docker)
- Compliance artifact export from event log
- `dependency_mode: any` for conditional convergence
- Three delegation modes: managed (current), static (pre-assigned), direct (manager does work itself)

---

## How to Try It

```bash
# Install
git clone <repo> && cd AgentOS
pip install -e .

# Verify a workflow (static analysis, no agents needed)
agentos workflow verify examples/quant_research.yaml

# Run with stub agents (no API key needed, instant)
agentos workflow run examples/news_aggregator.yaml

# Run with real Claude Code agents
export ANTHROPIC_API_KEY=...
agentos workflow run examples/news_aggregator.yaml --live --interactive
agentos workflow run examples/quant_research.yaml --live --interactive --db quant.db

# Resume from a specific task after a failure
agentos workflow run examples/quant_research.yaml --live --interactive \
  --start-from investment_synthesis --reuse-workspace run-<id> --db quant.db
```

---

## Codebase Metrics

| Metric | Value |
|--------|-------|
| Python source files | 71 |
| Source lines of code | ~12,000 |
| Test files | 61 |
| Test lines of code | ~19,000 |
| Tests (all passing) | 1,198 |
| Example workflows | 17 YAML files |
| Live-validated workflows | 3 (hedge fund, news aggregator, quant research) |

---

*Both workflows ran on March 6, 2026. Total compute cost: ~$5.61. All outputs are available in the run workspaces for inspection.*

*Built with Claude Code on AgentOS.*
