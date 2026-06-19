# PostHog Engineering Impact Dashboard — Design (v3, data-informed)

**Date:** 2026-06-20
**Author:** Joseph (Weave take-home)
**Status:** Approved design, revised after a second data-reconnaissance pass, pending implementation plan

> **v3 changes vs v2:** (1) *reach/criticality* is now a **measured** signal — distinct-author
> co-touch per area — instead of a subjective LLM 1–5; (2) added the **AI-assistance finding**
> (~82% of PRs carry agent signatures) as unscored context; (3) added an explicit **"outcome we
> do NOT claim"** disclosure; (4) added the **CODEOWNERS critical-path boost** and explicit
> **generated-file exclusion** from centrality. Everything else carries over from v2.

## Context

Weave (YC W25) builds a platform that runs **LLMs on every pull request** to tell
engineering leaders how much real work gets done — explicitly rejecting lines-of-code,
commits, and story points as "vanity metrics." This take-home asks us to identify the
**top 5 most impactful engineers** in the `PostHog/posthog` repository over at least the
last 90 days, on a **single-page, interactive, hosted dashboard**.

The assignment's central instruction — *"creative analysis beats a metric based on lines
of code / commits / files changed"* — is Weave's thesis restated. Strategy: reproduce it
in miniature — an LLM reads *what each engineer actually shipped*, scored on **substance**
and **measured reach**, and the dashboard presents **evidence**, not a black-box number.

**Audience:** a busy PostHog engineering leader who understands the work but won't read
every PR. They must understand the dashboard at a glance and be able to **validate** any
finding by clicking through to the underlying PRs.

## Data reconnaissance (measured 2026-06-20)

These numbers drove the architecture:

- **~8,976 PRs merged in the last 90 days** in `PostHog/posthog` — *thousands*, not
  hundreds. ~4–5% are bots (`author.is_bot`), leaving ~8,500 human-authored PRs. 100+
  distinct human authors.
- **PR count is actively misleading.** Two compounding causes: (a) PostHog uses **Graphite
  stacked PRs** — one engineer merged **257 PRs in a single week** (~37/day); (b) heavy
  **AI-agent automation** — e.g. `Gilbert09` merged **562 PRs in 90 days**, a sample of which
  are near-identical formulaic reliability fixes (`fix(snowflake)…`, `fix(hubspot)…`, ~2
  files each) in one isolated product area. A "most PRs/commits" ranking crowns this account
  #1. Defeating this is the central analytical challenge.
- **~82% of sampled PR bodies carry AI-generation signatures** (`Co-Authored-By: Claude/
  Cursor/Copilot`, 🤖, "Generated with"). PostHog is heavily agent-driven (`pr-approval-agent`,
  `AGENTS.md`, `AI`/`codex` labels). This is exactly Weave's "how much is AI?" thesis and the
  strongest argument for reach×substance over volume. **The exact % must be re-verified on the
  full census before it is published** (a standard PR-template footer could inflate it).
- **Co-touch centrality discriminates real core code.** Ranking 2-level directories by the
  number of **distinct** engineers who touched them (over the window) surfaced exactly the
  shared core: `frontend/src` (44 engineers), `services/mcp` (30), `posthog/temporal` (16),
  `posthog/api` (10), `posthog/models` (8), `posthog/hogql_queries` (7), `posthog/hogql` (6),
  while isolated single-team product work stayed low. **Caveat:** generated/CI files inflate
  this (`pnpm-lock.yaml`, `frontend/snapshots.yml`, `.github/workflows`) and must be excluded.
- **CODEOWNERS is deliberately minimal** ("adding entries is anti-PostHog") so it is *not* a
  general ownership map — but it explicitly flags a few **known-critical paths** we use as a
  boost: `posthog/api/authentication.py`, `posthog/auth.py`, `posthog/clickhouse/migrations/**`,
  `posthog/hogql/**`, `rust/persons_migrations/**`.
- **PR labels and issue-linking are unusable as signals.** In the window: `P0`/`P1`/`P2`,
  `tech-debt`, `highlight` = **0** PRs; `performance` = 1; only **1 / 20** PRs close an issue.
  The rich label taxonomy lives on *issues*, not PRs. (This is why "outcome" cannot be read
  from labels — see the honesty note below.)
- **Fetch mechanics:** GitHub search caps results at **1000 per query**; a single week can
  exceed 1000. Fetch must be **chunked into ≤2-day windows** and deduped, then verified
  against the search `total_count`. Per-file `additions/deletions/changeType` and per-review
  `author/state` are reliably populated. Review lists contain **bot reviewers** (e.g.
  `copilot-pull-request-reviewer`) that must be excluded from review credit.

## Definition of impact (the thesis)

> **Impact = how much an engineer's work moves the product and the team forward,
> weighted by the substance and reach of that work — not its volume.**

Raw line/commit/PR counts are never the metric. An LLM reads what each contender's PRs
*did*; reach is measured from the codebase itself; the score is three transparent dimensions:

| Dimension | Captures | Measured by |
|---|---|---|
| **Shipped substance** (primary) | The real weight of merged work — a critical ingestion fix ≫ a stacked one-line refactor | Per-PR `substance = complexity × reach × critical_boost`. **complexity** 1–5 from LLM reading title/body/paths/size (finalists only; heuristic size proxy otherwise). **reach** = measured co-touch centrality (max distinct-author count among the touched *code* areas, log-scaled), **excluding generated/lock/CI/snapshot/docs files**. **critical_boost** = ×1.5 if it touches a CODEOWNERS-critical path. Trivial PRs score ~0. |
| **Review leverage** (force-multiplier) | Enabling *others'* work — substantive reviews, not rubber-stamps | Reviews given on others' non-trivial PRs, weighted by depth (CHANGES_REQUESTED / COMMENTED > bare APPROVED) **and by the reach of the PR reviewed**. Bot reviewers and self-reviews excluded. |
| **Durability & breadth** (light) | Breadth of ownership; work that sticks | **Primary:** count of distinct core areas the engineer meaningfully touched. **Modifier:** small, conservative, LLM-adjudicated penalty for *faulty* self-reverts only (uncertain → zero penalty). Noisy and sparse (60 reverts repo-wide); never dominates. |

**Composite = 0.6 · Substance + 0.3 · ReviewLeverage + 0.1 · DurabilityBreadth.**
Weights are displayed on the dashboard, never hidden.

### Outcome — what we deliberately do NOT claim

We have **no production-outcome data** from GitHub (no incidents, usage, revenue), and the
repo's would-be proxies are absent on PRs (severity/`highlight` labels = 0; issue-linking
1/20). So we do **not** claim to measure business outcome. Instead we proxy *"did
high-leverage work"* with three things we *can* measure reliably — **reach** (co-touch
centrality), **substance** (LLM reads the PR), and a minor **durability** modifier — and we
**say so explicitly** in the methodology panel. Honest disclosure directly serves the "Can we
validate the findings?" criterion.

### Substance aggregation — defeating the volume trap

For each engineer: `substance_raw = Σ sᵢ` over their **non-trivial** PRs (trivial PRs
contribute ~0, so 257 stacked one-liners ≈ 0). Because `reach` down-weights isolated work,
562 formulaic single-area fixes accumulate little. To further stop one hyper-prolific account
from swamping the chart, `substance_raw` is **winsorized at the 95th percentile** before
min-max scaling, and per-engineer contribution from any single area gets **diminishing
returns** (sqrt of within-area count). The dashboard also shows raw context — **PR count,
AI-assisted %, work-type mix, median per-PR substance** — so a "high volume, low substance"
profile is *visible*, not hidden.

> **Built-in correctness test:** if `Gilbert09` (562 automated PRs) ranks in the top 5, the
> metric is broken. Validate against this known case before shipping.

## Analysis pipeline (the funnel; decoupled, runs once offline)

The expensive analysis runs during the build and emits a small static artifact. The
dashboard only reads that artifact.

1. **Census (all PRs, complete):** Fetch every merged PR in the 90-day window via `gh`,
   **chunked into ≤2-day windows** (concurrent where possible), fields:
   `number, title, body, labels, author(is_bot), files, additions, deletions,
   changedFiles, mergedAt, reviews, url`. Dedupe by PR number. Verify the final count
   against the search `total_count`. Write `data/prs_raw.json`.
2. **Filter + features (all PRs, Python, fast, no LLM):** Drop `is_bot` authors + denylist.
   For every human PR derive: `work_type` (title regex: feat/fix/refactor/perf/chore/docs/
   deps/revert), `areas` (file path → 2-level area), a `trivial` flag (snapshot/version-bump/
   generated-file/lockfile/tiny-diff/automated-label), `ai_assisted` flag (body signature),
   and size. **Compute area centrality** = distinct human authors per area over the window
   (excluding generated/lock/CI/snapshot/docs). Derive per-PR `reach` and `critical_boost`.
   Build the **review graph** (reviewer → PR, excluding bot reviewers and self-reviews).
   Compute heuristic per-engineer scores (size-proxy complexity × measured reach).
3. **Candidate selection:** Rank engineers by heuristic substance; take the **top ~20
   candidates** (the only ones who could make the top 5). Keep all engineers' aggregate
   stats for context.
4. **LLM complexity classification (bounded subset, Workflow fan-out):** For each candidate,
   take their **top ~30 non-trivial PRs by heuristic substance**, and have **parallel
   subagents** read each PR's metadata (title, body, labels, file paths, size) → `{work_type,
   complexity 1–5, one_line_summary}`. (Reach/criticality stay *measured*, not LLM-guessed.)
   Bounds LLM work to ~600 PRs (≤20 × 30); no external API key. Recompute candidate substance.
5. **Revert adjudication (≤60 PRs):** detect reverts (merge-commit `This reverts commit <sha>`
   or `Revert "<title>"`); a subagent judges *faulty vs. strategic*; apply conservative,
   capped penalty to the original author only when faulty and unambiguous.
6. **Aggregate + composite:** Min-max scale each dimension (substance winsorized at p95);
   apply 0.6/0.3/0.1 weights; scale composite to **0–100** for display.
7. **Narratives (top 5 only):** A subagent writes a 1–2 sentence "what they accomplished"
   summary per top-5 engineer from their classified PRs, plus picks 2–3 evidence PRs.
8. **Emit** `data/dashboard.json`.

### `dashboard.json` schema (draft)

```json
{
  "meta": {
    "repo": "PostHog/posthog",
    "window_days": 90, "window_start": "2026-03-22", "window_end": "2026-06-20",
    "total_prs_analyzed": 0, "human_prs": 0, "bot_prs": 0, "total_engineers": 0,
    "candidates_llm_classified": 0, "prs_llm_classified": 0,
    "ai_assisted_pct_repo": 0.0,
    "weights": { "substance": 0.6, "review_leverage": 0.3, "durability_breadth": 0.1 },
    "central_areas": [ { "area": "frontend/src", "distinct_authors": 44 } ],
    "generated_at": "2026-06-20"
  },
  "engineers": [
    {
      "rank": 1, "login": "string", "avatar_url": "string",
      "composite": 0, "narrative": "what they accomplished, in 1-2 sentences",
      "dimensions": { "substance": 0.0, "review_leverage": 0.0, "durability_breadth": 0.0 },
      "stats": { "prs_merged": 0, "non_trivial_prs": 0, "reviews_given": 0,
                 "ai_assisted_pct": 0.0,
                 "core_areas": ["ingestion"], "work_type_mix": {"feature": 0, "bugfix": 0},
                 "median_pr_substance": 0.0 },
      "evidence": [
        { "pr": 12345, "url": "https://github.com/PostHog/posthog/pull/12345",
          "title": "string", "summary": "LLM one-liner", "work_type": "feature",
          "reach": 44, "critical": true }
      ]
    }
  ]
}
```

## Dashboard (single screen, static, interactive)

- **Header:** title, the one-sentence impact definition, data scope + date range, counts
  (PRs analyzed / engineers / PRs LLM-classified), **one headline AI-assist stat**
  ("AI-assisted authorship is the norm — ~X% of PRs — which is why we rank by reach, not
  volume"), and an expandable **"How this was computed"** panel showing the formula, the
  measured-centrality method, and the explicit outcome-honesty note. Directly answers the
  "Score with no explanation" red flag.
- **Top 5 ranked rows/cards:** name + avatar, composite (0–100) with a bar, the
  **dimension breakdown** (stacked bar: substance / review / durability), the **narrative**,
  key **context chips** — PR count, **AI-assisted %**, work-type mix (making volume-vs-impact
  visible) — and **evidence highlights**: 2–3 real PRs with LLM one-liners, each **linked to
  GitHub** so the leader can click through and validate every claim.
- **Interactivity:** expand a card for full evidence; **stretch:** sliders to re-weight the
  three dimensions and watch the ranking reorder live (shows the score is transparent).
- **Single-screen:** the top-5 summary fits one laptop screen; drill-down expands in place.

## Tech stack

- **Pipeline:** Python + `gh` CLI; LLM classification fan-out via the Workflow tool.
- **Frontend:** **vanilla static** — `index.html` + vanilla JS + one CDN chart lib,
  reading `dashboard.json`. No build step to break on deploy.
- **Hosting:** **Vercel free (Hobby) tier**, static deploy → CDN, no cold-start,
  sub-second load. **Account:** deploy under `joseph.ycx@gmail.com` (CLI may currently be
  another account; switch via `vercel login` before deploy).

## Validation & trust

Every score traces to underlying PRs via clickable GitHub links; the methodology panel
shows the exact formula, the measured-centrality basis, and what we deliberately do not
claim. A leader can independently verify any ranking. Serves the "Can we validate the
findings?" criterion directly.

## Time budget (target; quality prioritized over the 90-min clock per user direction)

| Phase | Target |
|---|---|
| Complete heavy census (parallel windows) | ~8–12 min |
| Filter + features + centrality + review graph | ~5 min |
| LLM classification (Workflow fan-out, ~600 PRs) | ~15 min |
| Revert adjudication + aggregate + narratives + emit JSON | ~8 min |
| Dashboard build | ~25 min |
| Deploy + browser verification | ~10 min |

## Scope / YAGNI

Cuts if time runs short, in order:
1. Re-weight sliders (keep static breakdown bars).
2. Durability/breadth dimension (renormalize to 0.65·Substance + 0.35·ReviewLeverage).
3. Avatars / polish.

Non-negotiable core: complete 90-day data, measured reach + LLM-read substance for
contenders, top-5 ranking with clickable PR evidence, visible methodology, volume-vs-impact
made legible.

## Risk → red-flag mitigation

| Red flag | Mitigation |
|---|---|
| Link doesn't load / >10s | Static site on Vercel CDN; no server/cold-start. |
| Incorrect / incomplete data | Complete heavy census, ≤2-day chunked pagination + dedupe, count verification, bot author/reviewer filtering. |
| Buggy / broken UI | Vanilla static, minimal JS; browser-verify before submit. |
| Doesn't answer "who's most impactful" | Top-5 ranked list is the page's primary content. |
| Score with no explanation | Methodology panel + per-engineer dimension breakdown + clickable PR evidence + context chips. |
| Misleading via volume | Trivial-PR zeroing, measured-reach weighting, per-area diminishing returns, p95 winsorization, explicit PR-count + AI-% context shown. |
| Overclaiming AI-% | Re-verify the signature rate on the full census before publishing the headline number. |

## Deliverables

- Dashboard URL (Vercel, `joseph.ycx@gmail.com`).
- Short approach description (measured reach + LLM-read substance, not volume; AI-aware).
- Timer duration. Export of the coding-agent session.
