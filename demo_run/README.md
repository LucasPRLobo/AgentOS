# Demo Run: News Digest — The Future of Energy in Brazil

Output from a live AgentOS run using `examples/news_digest.yaml` with 2 Claude Code agents and a human approval gate.

**Command:**
```bash
agentos workflow run examples/news_digest.yaml \
  --db news_demo.db \
  --param topic="The future of energy in Brasil" \
  --live --interactive
```

**Workflow:** 3 tasks, 2 agents, 1 approval gate
**Total time:** 196 seconds
**Total cost:** ~$0.51

## What happened

1. **gather_news** (researcher agent) — Searched the web, found 6 major developments, produced `energy_brazil_news.md` and a structured `manifest.json` with findings, confidence levels, and sources.

2. **review_gate** (human) — Paused for review. Human typed: *"focus more on renewable and alternative energy sources in Brasil"*. This feedback was approved and passed as context to the next task.

3. **analyze_trends** (analyst agent) — Read the researcher's output AND the human's gate feedback. Produced `trend_analysis.md` with 6 interconnected trends, confidence ratings, cross-cutting risk analysis, and open questions. The analyst explicitly followed the human's guidance to focus on renewables.

## Files

```
demo_run/
├── gather_news/
│   ├── energy_brazil_news.md    # Researcher's raw report (6 findings with sources)
│   └── manifest.json            # Structured output (findings, confidence, open questions)
├── review_gate/
│   └── manifest.json            # Human feedback captured as structured data
└── analyze_trends/
    ├── trend_analysis.md        # Analyst's final report (104 lines)
    └── manifest.json            # Structured analysis output
```
