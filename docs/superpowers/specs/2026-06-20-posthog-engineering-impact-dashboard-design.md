# PostHog Engineering Impact Dashboard — Design

**Date:** 2026-06-20
**Author:** Joseph (Weave take-home)
**Status:** Approved design, pending implementation plan

## Context

Weave (YC W25) builds a platform that runs **LLMs on every pull request** to tell
engineering leaders how much real work gets done — explicitly rejecting lines-of-code,
commits, and story points as "vanity metrics." This take-home asks us to identify the
**top 5 most impactful engineers** in the `PostHog/posthog` repository over at least the
last 90 days, on a **single-page, interactive, hosted dashboard**.

The assignment's central instruction — *"creative analysis beats a metric based on lines
of code / commits / files changed"* — is Weave's product thesis restated. The strategy
is therefore to reproduce that thesis in miniature: use an LLM to read *what each
engineer actually shipped*, score it on substance and reach, and present **evidence**, not
a black-box number.

**Audience:** a busy PostHog engineering leader who understands the work but won't read
every PR. They must understand the dashboard at a glance and be able to **validate** any
finding by clicking through to the underlying PRs.

## Definition of impact (the thesis)

> **Impact = how much an engineer's work moves the product and the team forward,
> weighted by the substance and reach of that work — not its volume.**

Raw line/commit counts are never the metric. An LLM reads what each PR *did*, and the
score is composed of three transparent dimensions:

| Dimension | Captures | Measured by |
|---|---|---|
| **Shipped substance** (primary) | The real weight of merged work — a critical ingestion fix ≫ a dependency bump | LLM classifies each PR: work-type, complexity (1–5), and **criticality/reach** (1–5) — does it touch core systems (ingestion, query engine, HogQL, billing, plugin-server) vs. peripheral (docs, config, isolated)? |
| **Review leverage** (force-multiplier) | Enabling *others'* work — substantive reviews, not rubber-stamps | Reviews given, weighted by depth (changes-requested / commented > bare approve) and by the substance of the PR reviewed |
| **Follow-through** (reliability, light) | Breadth of ownership; work that sticks | **Primary:** count of distinct core areas the engineer touched (range of ownership). **Best-effort:** small penalty for self-reverts (PRs titled `Revert ...` referencing their own merged work). Self-revert detection is noisy, so it is optional and never dominates this dimension. |

**Composite score = 0.6 · Substance + 0.3 · ReviewLeverage + 0.1 · FollowThrough.**
Weights are displayed on the dashboard, never hidden.

## Data collection

- **Scope:** `PostHog/posthog` only. All PRs **merged within the last 90 days** (clean
  90-day cutoff from the build date; the assignment requires *at least* 90 days).
- **Tool:** `gh` CLI (authenticated as `yeh0903`). Fields pulled per PR:
  `number, title, body, labels, author (with is_bot), files, additions, deletions,
  changedFiles, mergedAt, reviews`.
- **Completeness guard (named red flag — "incomplete data"):** GitHub search caps at
  1000 results per query and PostHog may merge >1000 PRs in 90 days. Mitigation: **chunk
  the 90-day range into sub-windows** (e.g. ~2-week buckets) using
  `merged:>=A merged:<B`, paginate each, and **dedupe by PR number**. Verify the final
  count against `gh` totals.
- **Bot filtering:** drop authors where `is_bot == true`, plus a denylist
  (`dependabot`, `posthog-bot`, `github-actions`, `renovate`, `snyk`, `sentry-io`).

## Analysis pipeline (decoupled; runs once, offline)

The expensive analysis runs during the build and emits a small static artifact. The
dashboard only reads that artifact, so presentation is fast and the render layer is
swappable.

1. **Fetch** → write raw PRs to `data/prs.json` (after bot filtering + dedupe).
2. **Classify** → batch PRs (~50 per batch) to **parallel subagents** (via the Workflow
   tool) that emit structured JSON per PR: `{work_type, complexity, criticality,
   one_line_summary}`. Classification uses **metadata only** (title, body, labels, file
   paths, size) — cheap, no external API key, mirrors Weave's "read the PR" approach.
3. **Aggregate** → transparent Python computes per-engineer raw dimension values, then
   **min-max scales each dimension to [0, 1]** (top engineer in a dimension = 1.0) before
   applying the 0.6/0.3/0.1 weights. The weighted composite is **scaled to 0–100 for
   display**. Min-max is chosen for interpretability (the stacked bar reads as "share of
   the leader"); we sanity-check that no single outlier collapses the rest of the field.
4. **Emit** `data/dashboard.json` consumed by the frontend.

### `dashboard.json` schema (draft)

```json
{
  "meta": {
    "repo": "PostHog/posthog",
    "window_days": 90,
    "window_start": "2026-03-22",
    "window_end": "2026-06-20",
    "total_prs_analyzed": 0,
    "total_engineers": 0,
    "weights": { "substance": 0.6, "review_leverage": 0.3, "follow_through": 0.1 },
    "generated_at": "2026-06-20"
  },
  "engineers": [
    {
      "rank": 1,
      "login": "string",
      "avatar_url": "string",
      "composite": 0.0,
      "dimensions": {
        "substance": 0.0,
        "review_leverage": 0.0,
        "follow_through": 0.0
      },
      "stats": { "prs_merged": 0, "reviews_given": 0, "core_areas": ["ingestion"] },
      "evidence": [
        { "pr": 12345, "url": "https://github.com/PostHog/posthog/pull/12345",
          "title": "string", "summary": "LLM one-liner: what this accomplished",
          "work_type": "feature", "criticality": 5 }
      ]
    }
  ]
}
```

## Dashboard (single screen, static, interactive)

- **Header:** title, the one-sentence impact definition, data scope + date range, count of
  PRs/engineers analyzed, and an expandable **"How this was computed"** panel showing the
  formula + that classification was LLM-based on PR metadata. Directly answers the
  "Score with no explanation" red flag.
- **Top 5 ranked rows/cards:** name + avatar, composite score with a bar, the **dimension
  breakdown** (stacked bar showing substance / review / follow-through contributions), and
  **evidence highlights** — 2–3 actual PRs with LLM one-liners, each **linked to GitHub**
  so the leader can click through and validate every claim.
- **Interactivity:** expand a card to reveal full evidence (top PRs, review activity).
  **Stretch:** sliders to re-weight the three dimensions and watch the ranking reorder
  live — demonstrates the score is transparent, not a black box.
- **Single-screen:** the top-5 summary fits one laptop screen by default; drill-down
  expands in place.

## Tech stack

- **Pipeline:** Python + `gh` CLI; classification fan-out via the Workflow tool (parallel
  subagents).
- **Frontend:** **vanilla static** — `index.html` + vanilla JS + one CDN chart lib,
  reading `dashboard.json`. No build step to break on deploy.
- **Hosting:** **Vercel free (Hobby) tier**, static deploy. Served from CDN → no
  cold-start, sub-second load, clean public URL. Strictly better than Streamlit on the
  load-time red flags.

## Validation & trust

Every score traces to underlying PRs via clickable GitHub links, and the methodology
panel shows the exact formula. A leader can independently verify any engineer's ranking.
This directly serves the "Can we validate the findings?" evaluation criterion.

## Time budget (90 min)

| Phase | Target |
|---|---|
| Fetch + bot filter + dedupe | ~10 min |
| Classify (parallel subagents) | ~20 min |
| Aggregate + emit JSON | ~10 min |
| Dashboard build | ~30 min |
| Deploy + verify | ~10 min |
| Buffer | ~10 min |

The timer starts at implementation and is reported at the end (assignment requirement).

## Scope / YAGNI

Cuts if time runs short, in this order:
1. Re-weight sliders (keep static breakdown bars).
2. Follow-through dimension (renormalize to 0.65·Substance + 0.35·ReviewLeverage).
3. Avatars / polish.

The non-negotiable core: complete 90-day data, LLM-based substance classification,
top-5 ranking with clickable PR evidence, and a visible methodology.

## Risk → red-flag mitigation

| Red flag | Mitigation |
|---|---|
| Link doesn't load / >10s | Static site on Vercel CDN; no server/cold-start. |
| Incorrect / incomplete data | Date-chunked pagination + dedupe; bot filtering; verify counts. |
| Buggy / broken UI | Vanilla static, minimal JS; verify in browser before submit. |
| Doesn't answer "who's most impactful" | Top-5 ranked list is the page's primary content. |
| Score with no explanation | Methodology panel + per-engineer dimension breakdown + clickable PR evidence. |

## Deliverables

- Dashboard URL (Vercel).
- Short approach description (this thesis: LLM-read substance & reach, not volume).
- Timer duration (start at implementation, stop at finish).
- Export of the coding-agent session.
