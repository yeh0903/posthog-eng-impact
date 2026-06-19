# PostHog Engineering Impact Dashboard

**Live:** https://posthog-eng-impact.vercel.app

Identifies the **top 5 most impactful engineers** in [`PostHog/posthog`](https://github.com/PostHog/posthog)
over the last 90 days (2026-03-22 → 2026-06-20) — by the **substance and reach of what
they shipped, not their volume**.

---

## The problem with counting

PostHog merged **8,976 PRs in 90 days**. Two things make a "most PRs / commits / lines"
ranking actively *misleading*:

1. **Graphite stacked PRs** — one engineer merged 257 PRs in a single week.
2. **AI-agent automation** — **64% of PRs carry AI-generation signatures**; one account
   (`Gilbert09`) merged 562 near-identical formulaic integration fixes.

A naive ranking crowns the highest-volume bot-like account. Ours ranks it **#27**.

## What we mean by "impact"

> **Impact = how much an engineer's work moves the product and the team forward, weighted
> by the substance and reach of that work — not its volume.**

An LLM reads the **actual diff** of each contender's PRs; reach is **measured from the
codebase itself**. The score is three transparent dimensions:

| Dimension | Weight | How it's measured |
|---|---|---|
| **Shipped substance** | 0.6 | Per PR: `cw(complexity) × reach × critical_boost`. An LLM rates complexity 1–5 *from the diff*; `cw` is **convex** (`{1:0, 2:1, 3:3, 4:6, 5:10}`) so a complexity-1 change scores **zero**. Counted over each engineer's **top-30 PRs**, aggregated concavely (breadth rewarded, within-area volume damped). |
| **Review leverage** | 0.3 | Substantive reviews on others' non-trivial PRs (changes-requested > comment > approve), weighted by the reach of the reviewed PR. A PR's review value is **split across its reviewers** so it can't multiply credit. Bots & self-reviews excluded. |
| **Durability & breadth** | 0.1 | Distinct core areas the engineer meaningfully touched. |

**`reach` is measured, not assumed:** the number of *distinct engineers* who touch a code
area over the window (co-touch centrality). The shared core scores high (`frontend/src` 139
authors, `posthog/api` 103, `posthog/temporal` 82); isolated single-team work scores low.
Generated/lock/CI/snapshot files are excluded.

Scores are min-max scaled **within the analyzed cohort** (100 = highest among analyzed) and
every claim links to the PRs, so a leader can validate any ranking in one click.

### What we deliberately do **not** claim
GitHub has no production-outcome data (incidents, usage, revenue), and PostHog's PR labels
/ issue-links are unused — so we do **not** claim to measure business outcome. We measure
*doing high-leverage engineering work*, and we say so on the dashboard.

## The result

| # | Engineer | What they shipped |
|---|---|---|
| 1 | **benjackwhite** | Drove the Agent Platform from scaffold to prod-readiness + infra reaching 100+ engineers (Kafka routing, CDP Valkey dual-write, ClickHouse metrics). |
| 2 | **rnegron** | Built the `engineering_analytics` product end-to-end (curated warehouse read layer, typed MCP tools, CI analytics scene). |
| 3 | **haacked** | Hardened the feature-flags serving path (lazy per-token auth cache, cohort hypercache preload) — **2% AI-assisted**, mostly hand-written. |
| 4 | **aspicer** | Deep HogQL query-engine work (rebuilt the ClickHouse funnel UDF, re-architected predicate pushdown) — **just 38 PRs, ranked #4**: depth over volume. |
| 5 | **ablaszkiewicz** | Error-tracking V3 query rewrite (denormalized ClickHouse table, optimized HogQL joins). |

`aspicer` (#4, 38 PRs) over `Gilbert09` (#27, 562 PRs) is the thesis working.

## How it's built (decoupled pipeline → static site)

```
fetch_prs.py    → complete 90-day census (8,976 PRs, chunked + deduped, count-asserted)
features.py     → bot filter, per-PR features, measured area centrality, review graph,
                  35 candidates (generous UNION so few-but-deep engineers are never cut)
classify_prep   → fetch truncated diffs for 877 candidate PRs
classify.js     → LLM rates complexity 1–5 from the diff (parallel fan-out, strict schema,
                  fallback to heuristic on failure)
aggregate.py    → convex weighting, top-30 cap, concave aggregation, winsorize, composite
narratives.js   → grounded 1–2 sentence narrative per top-5 engineer
                → data/dashboard.json → public/  (vanilla static, Vercel CDN)
```

The dashboard is a **precomputed static page** (no server, no cold-start) → sub-second loads.

## Reproduce

```bash
python3 -m scripts.fetch_prs          # census  -> data/prs_raw.json
python3 -m scripts.features           # features + candidates
python3 -m scripts.classify_prep      # fetch candidate diffs
# run workflows/classify.js (LLM fan-out) -> data/llm_classifications.json
python3 -m scripts.aggregate          # -> data/dashboard.json  (asserts Gilbert09 not top-5)
python3 -m scripts.narrate_prep
# run workflows/narratives.js, then scripts.merge_narratives
cp data/dashboard.json public/ && vercel deploy public --prod
python3 -m pytest -q                  # 23 tests
```

## Trust & correctness
- **Complete data:** census count asserted against GitHub's authoritative `total_count` (8,976 == 8,976).
- **Validatable:** every score links to the underlying PRs; spot-checked against GitHub.
- **Built-in guard:** the build *fails* if `Gilbert09` (562 automated PRs) reaches the top 5.
- **23 unit tests** on the scoring logic (anti-volume properties, the Gilbert09 case, review splitting).

**Design docs:** [`docs/superpowers/specs/`](docs/superpowers/specs/) (spec, hardened by an
adversarial review) and [`docs/superpowers/plans/`](docs/superpowers/plans/).

**Tech:** Python 3 (stdlib), `gh` CLI, parallel LLM fan-out, vanilla HTML/CSS/JS, Vercel.
