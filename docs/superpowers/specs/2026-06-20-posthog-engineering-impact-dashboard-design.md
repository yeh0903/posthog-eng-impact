# PostHog Engineering Impact Dashboard — Design (v4, review-hardened)

**Date:** 2026-06-20
**Author:** Joseph (Weave take-home)
**Status:** Approved design; hardened by an adversarial multi-lens spec review; pending implementation plan

> **v4 changes vs v3** (from the verified spec review, 21 confirmed findings):
> (1) **Generous UNION candidate gate** with a quantity-neutral deep-work safety net — a
> few-but-deep engineer can never be cut before the LLM reads them; the cut is recorded and
> disclosed. (2) **Concave substance aggregation** (Σ√sᵢ) so volume cannot beat depth.
> (3) **Review credit is split across a PR's reviewers** (no multiplying one PR across many
> reviewers). (4) **GraphQL truncation handled** — `files`/`reviews` cap at 100 entries:
> `core_areas` computed as set-presence, truncation flagged + counted. (5) **Reviewer-bot
> exclusion via a login denylist** (review authors have no `is_bot`). (6) **LLM reads real
> diffs**, not just metadata, for classified PRs (truncated) and all evidence PRs.
> (7) **Stub-deploy-first** so a working public URL exists before the expensive data work.
> (8) **LLM partial-failure contract** (fallback to heuristic, never crash). (9) Scores are
> disclosed as **relative within the analyzed cohort**. v3's measured-reach, AI-assist
> finding, CODEOWNERS boost, generated-file exclusion, and outcome-honesty all carry over.

## Context

Weave (YC W25) builds a platform that runs **LLMs on every pull request** to tell
engineering leaders how much real work gets done — explicitly rejecting lines-of-code,
commits, and story points as "vanity metrics." This take-home asks us to identify the
**top 5 most impactful engineers** in `PostHog/posthog` over at least the last 90 days, on a
**single-page, interactive, hosted dashboard**.

The assignment's central instruction — *"creative analysis beats a metric based on lines of
code / commits / files changed"* — is Weave's thesis restated. Strategy: reproduce it in
miniature — an LLM reads *what each contender actually shipped (the diff)*, scored on
**substance** and **measured reach**, with the dashboard presenting **evidence**, not a
black-box number.

**Audience:** a busy PostHog engineering leader who understands the work but won't read
every PR. They must understand the dashboard at a glance and **validate** any finding by
clicking through to the underlying PRs.

## Data reconnaissance (measured 2026-06-20)

- **8,976 PRs merged in the last 90 days** (search `total_count`). ~4–5% are bots
  (`author.is_bot`), leaving ~8,500 human PRs across **100+ distinct human authors**.
- **PR count is actively misleading.** (a) PostHog uses **Graphite stacked PRs** — one
  engineer merged **257 PRs in a single week**; (b) heavy **AI-agent automation** — e.g.
  `Gilbert09` merged **562 PRs in 90 days**, many near-identical formulaic single-area fixes.
  A "most PRs/commits" ranking crowns this account #1. Defeating this is the central problem.
- **~82% of sampled PR bodies carry AI-generation signatures.** Surfaced as **unscored
  context**, not a score input. **Must be re-verified on the full census before publishing**
  (a template footer could inflate it).
- **Reach is measured, not assumed.** Co-touch centrality — distinct human authors per
  2-level directory over the window — surfaced the shared core (`frontend/src` 44 engineers,
  `services/mcp` 30, `posthog/temporal` 16, `posthog/api` 10, `posthog/models` 8,
  `posthog/hogql_queries` 7, `posthog/hogql` 6) while isolated single-team work stayed low.
  **Generated/lock/CI/snapshot/docs files are excluded** (`pnpm-lock.yaml`, `*snapshots*`,
  `.github/workflows`, generated dirs) so they don't inflate centrality.
- **CODEOWNERS is deliberately minimal** — used only as a small ×1.5 **critical-path boost**
  for known-critical paths (`posthog/api/authentication.py`, `posthog/auth.py`,
  `posthog/clickhouse/migrations/**`, `posthog/hogql/**`, `rust/persons_migrations/**`).
- **PR labels & issue-linking are unusable signals** (`P0/P1/P2`, `tech-debt`, `highlight`
  = 0 PRs; only 1/20 PRs close an issue). The label taxonomy lives on *issues*, not PRs.
- **GraphQL truncation (review finding):** `gh pr list --json files,reviews` caps each array
  at **100 entries**. → `core_areas` is computed as **set-presence of core path prefixes**
  (robust: the first 100 paths of a cross-cutting PR almost always cover every area), and
  `files_truncated`/`reviews_truncated` (= `changedFiles > len(files)` / `len(reviews)==100`)
  are flagged and counted in `meta`.
- **Reviewer bots have no flag (review finding):** `reviews[].author` exposes only `{login}`
  (no `is_bot`, unlike PR authors). Reviewer exclusion uses a **login denylist** seeded from
  the data (observed: `copilot-pull-request-reviewer`, `posthog-bot`, `sourcery-ai[bot]`, +
  any `*[bot]`/`*-app`/`*-agent` login found on the full census). The denylist also backstops
  author filtering (PAT-based automation isn't flagged `is_bot`).
- **Binding API limit (review finding):** `gh pr list --search` runs on GraphQL; the real
  throttle is **secondary/abuse detection on sustained concurrency**, not the primary 5000/hr.
  Fetch uses **bounded concurrency (≤6–8 in-flight) + exponential backoff + auto-split** any
  window that times out (504) or approaches the 1000 cap. (Verified: one 504 on a busy recent
  window; the splitting fetcher handles it.)
- **Window math:** the inclusive UTC range `2026-03-22..2026-06-20` spans **91 calendar
  days** (≥ the required 90). Windows tile **disjoint whole UTC days** (no shared endpoint);
  dedupe by PR number; **assert deduped count == search `total_count`** (±small tolerance).

## Definition of impact (the thesis)

> **Impact = how much an engineer's work moves the product and the team forward, weighted by
> the substance and reach of that work — not its volume.**

Raw line/commit/PR counts are never the metric. An LLM reads what each contender's PRs *did*
(from the diff); reach is measured from the codebase; the score is three transparent dimensions:

| Dimension | Captures | Measured by |
|---|---|---|
| **Shipped substance** (primary) | The real weight of merged work — a critical ingestion fix ≫ a stacked one-line refactor | Per-PR `sᵢ = cw(complexity) × reach × critical_boost`, **convex** `cw={1:0,2:1,3:3,4:6,5:10}` (complexity-1 ≈ 0). **complexity** 1–5 from an LLM **reading the diff** (finalists' top-30 PRs; size-proxy only as a per-PR fallback). **reach** = measured co-touch centrality of the PR's areas (distinct-author count, log-scaled), excluding generated/lock/CI/snapshot files. **critical_boost** = ×1.5 on CODEOWNERS-critical paths. Counted over each engineer's **top-30 PRs**, aggregated concavely (below). |
| **Review leverage** (force-multiplier) | Enabling *others'* work — substantive reviews | For each non-trivial PR, each non-bot non-author reviewer earns `reach(pr) × depth_weight ÷ n_reviewers` (depth: APPROVED 1.0, COMMENTED 1.3, CHANGES_REQUESTED 1.6 — strongest state per reviewer). Dividing by reviewer count stops a much-reviewed PR from multiplying credit. Bot reviewers (login denylist) and self-reviews excluded. |
| **Durability & breadth** (light) | Breadth of ownership across the codebase | Count of **distinct core areas** the engineer meaningfully touched (non-trivial PRs), min-max scaled. *(The faulty-self-revert penalty from earlier drafts is cut — reverts are sparse (~60 repo-wide) and noisy; YAGNI for a 0.1-weight dimension.)* |

**Composite = 0.6 · Substance + 0.3 · ReviewLeverage + 0.1 · DurabilityBreadth.** Weights
shown on the dashboard. **All scores are min-max scaled *within the analyzed cohort*** —
100 = highest among engineers analyzed, *not* an absolute score (disclosed in the panel).

### Outcome — what we deliberately do NOT claim

We have **no production-outcome data** from GitHub (no incidents, usage, revenue), and the
repo's would-be proxies are absent on PRs. So we do **not** claim to measure business
outcome. We proxy *"did high-leverage work"* with what we *can* measure reliably — **reach**
(co-touch centrality), **substance** (LLM reads the diff), and a minor **durability**
modifier — and we **say so explicitly** in the methodology panel. Honest disclosure serves
the "Can we validate the findings?" criterion.

### Substance aggregation — defeating the volume trap

Three mechanisms, applied in order, make volume unable to win (the plan review proved that
concavity alone is too weak — `reach` is an *area* property, so even formulaic PRs in a busy
area inherit high reach):

1. **Convex complexity weighting drives shallow work to ~0.** Each PR's
   `sᵢ = cw(complexity) × reach × critical_boost`, with `cw = {1:0, 2:1, 3:3, 4:6, 5:10}`.
   A complexity-1 change contributes **nothing**, however central the file; complexity rises
   steeply so genuine depth dominates. The LLM rates complexity from the **diff**, so a
   formulaic 2–3-file fix reads as 1.
2. **Substance counts only each engineer's top-30 PRs (by heuristic substance) — the exact set
   the LLM deep-reads.** A hyper-prolific account's long tail (Gilbert09's other ~532 PRs)
   feeds the PR-*count* context chip but **not** the score. Natural anti-volume cap: you're
   scored on your 30 most substantial contributions, deeply analyzed — not raw output.
3. **Concave aggregation** then rewards breadth and damps within-area volume:
   `substance_raw = Σ over areas [ √( Σ_{counted PRs in area} sᵢ ) ]`, **p95-winsorized** before
   min-max scaling.

We do **not** claim "few-but-deep always beats high-volume" (any sum can be out-summed); we
**guarantee formulaic / trivial / isolated volume cannot win** — `cw(1)=0`, reach down-weights
isolated areas, and the top-30 cap bounds count. The dashboard shows **PR count, AI-assisted %,
work-type mix, median per-PR substance** so a "high volume, low depth" profile is visible.

> **Built-in correctness test:** if `Gilbert09` (562 formulaic single-area PRs) ranks in the
> top 5, the metric is broken — validate before shipping. The unit guard models a prolific
> engineer whose top-30 PRs are *non-trivial but formulaic* (complexity 1–2) vs a deep engineer
> with ~6 complexity-5 PRs (a guard using *trivial* PRs would pass vacuously).

## Analysis pipeline (the funnel; decoupled, runs once offline)

1. **Census (all PRs, complete):** `gh pr list` heavy fields (`number,title,body,labels,
   author,files,additions,deletions,changedFiles,mergedAt,reviews,url`), **disjoint whole-UTC-day
   windows**, bounded concurrency + backoff + auto-split on 504/1000-cap. Dedupe by number;
   **assert deduped == search `total_count` (8976 ± small)**, fail loud otherwise.
   → `data/prs_raw.json`. *(Done: 8,976 expected.)*
2. **Filter + features (Python, no LLM):** drop `is_bot` authors + denylist. Per PR derive
   `work_type` (title regex), `areas` (path→2-level, set-presence; `files_truncated` flag),
   `trivial` flag, `ai_assisted` flag, size. **Measure area centrality** (distinct human
   authors/area, excluding generated/lock/CI/snapshot/docs). Derive per-PR `reach`,
   `critical_boost`. Build **review graph** (reviewer→PR; exclude denylisted bot reviewers +
   self-reviews; `reviews_truncated` flag + `meta` count). Compute heuristic engineer scores.
3. **Candidate selection (generous UNION — no silent cut):** candidate set =
   (a) top ~20 by heuristic substance ∪ (b) top ~10 by heuristic review leverage ∪
   (c) any engineer with ≥1 non-trivial PR on a CODEOWNERS-critical path **or** in
   top-quartile measured reach ∪ (d) any engineer whose **best single-PR** heuristic
   substance is top-decile (quantity-neutral deep-work path). Cap ~30. Record
   `total_engineers` vs `candidates_llm_classified` in `meta`; the panel notes the cut.
4. **LLM classification (bounded fan-out, reads the diff):** per candidate, top ~30
   non-trivial PRs by heuristic substance; parallel subagents read **title/body/labels/paths +
   a truncated diff** (`gh pr diff`, capped per-file/token budget) → `{work_type, complexity
   1–5, one_line_summary}`. **Partial-failure contract:** strict JSON validation; on timeout/
   malformed/out-of-range → **fall back to heuristic substance** (never zero, never crash),
   flag `classified:false`; `meta` records `prs_llm_classified` vs `prs_heuristic_fallback`.
   Reach/criticality stay measured. (~600–900 PRs; absorbed by the budget.)
5. **Revert adjudication (≤60 PRs):** detect reverts; subagent judges faulty vs. strategic;
   conservative capped penalty to the original author only when faulty and unambiguous.
6. **Aggregate + composite:** concave substance (winsorized p95), review credit split across
   reviewers, min-max **within the candidate cohort**, weights 0.6/0.3/0.1, scaled 0–100.
7. **Narratives (top 5 only, reads diffs):** a subagent reads each top-5 engineer's 2–3
   evidence PRs' **actual diffs** (`gh pr diff`, truncated) → a 1–2 sentence "what they
   accomplished" + evidence one-liners that reflect the code.
8. **Emit** `data/dashboard.json`.

### `dashboard.json` schema (draft)

```json
{
  "meta": {
    "repo": "PostHog/posthog", "window_days": 91,
    "window_start": "2026-03-22", "window_end": "2026-06-20",
    "total_prs_analyzed": 0, "human_prs": 0, "bot_prs": 0, "total_engineers": 0,
    "candidates_llm_classified": 0, "prs_llm_classified": 0, "prs_heuristic_fallback": 0,
    "files_truncated_prs": 0, "reviews_truncated_prs": 0,
    "ai_assisted_pct_repo": 0.0,
    "weights": { "substance": 0.6, "review_leverage": 0.3, "durability_breadth": 0.1 },
    "scoring_note": "min-max scaled within analyzed cohort; 100 = highest among analyzed",
    "central_areas": [ { "area": "frontend/src", "distinct_authors": 44 } ],
    "generated_at": "2026-06-20"
  },
  "engineers": [
    {
      "rank": 1, "login": "string", "avatar_url": "string",
      "composite": 0, "narrative": "what they accomplished, in 1-2 sentences",
      "dimensions": { "substance": 0.0, "review_leverage": 0.0, "durability_breadth": 0.0 },
      "stats": { "prs_merged": 0, "non_trivial_prs": 0, "reviews_given": 0,
                 "ai_assisted_pct": 0.0, "core_areas": ["..."],
                 "work_type_mix": {"feature": 0, "bugfix": 0}, "median_pr_substance": 0.0 },
      "evidence": [
        { "pr": 12345, "url": "https://github.com/PostHog/posthog/pull/12345",
          "title": "string", "summary": "LLM one-liner from the diff",
          "work_type": "feature", "reach": 44, "critical": true }
      ]
    }
  ]
}
```

## Dashboard (single screen, static, interactive)

- **Header:** title, the one-sentence impact definition, scope + date range, counts (PRs
  analyzed / engineers / PRs LLM-classified), **one headline AI-assist stat** ("AI-assisted
  authorship is the norm — ~X% of PRs — which is why we rank by reach, not volume"), and an
  expandable **"How this was computed"** panel: the formula, the measured-centrality method,
  the **relative-scaling** disclosure, the **candidate-cut** note, and the outcome-honesty note.
- **Top 5 — collapsed rows fit one screen.** *Collapsed:* rank, name + avatar, composite
  (0–100) bar, the 1–2 sentence narrative. *Expanded (click):* dimension breakdown stacked
  bar, context chips (PR count, AI-assisted %, work-type mix, median substance), and 2–3
  **GitHub-linked** evidence PRs with LLM one-liners. This resolves the fit-on-one-screen
  constraint while keeping full validation one click away.
- **Interactivity:** expand/collapse; **stretch:** sliders to re-weight the three dimensions
  and watch the ranking reorder live.

## Tech stack

- **Pipeline:** Python + `gh` CLI; LLM fan-out via the Workflow tool.
- **Frontend:** **vanilla static** — `index.html` + vanilla JS + one CDN chart lib reading
  `dashboard.json`. No build step to break on deploy.
- **Hosting:** **Vercel Hobby (free)** static deploy → CDN, no cold-start, sub-second load.
  **Account: deploy under `joseph.ycx@gmail.com`** (user requirement; CLI is currently
  `joseph@gr33n.ai` → run `vercel login` and **verify `vercel whoami` is the target before
  deploying**). **Fallback if Vercel auth is blocked:** `npx surge ./public` or GitHub Pages
  (public repo) — both static, both <10s.
- **Stub-deploy-first (review finding):** build `index.html` against the schema using a
  hand-stubbed `dashboard.json`, **deploy + browser-verify the public URL loads FIRST**, then
  swap in real data. The non-negotiable deliverable (a working link) exists before the
  expensive data work.

## Validation & trust

Every score traces to underlying PRs via clickable GitHub links; the panel shows the exact
formula, the measured-centrality basis, the relative-scaling caveat, the candidate-selection
cut, and what we deliberately do not claim. A leader can independently sanity-check any
ranking.

## Time budget (quality prioritized over the 90-min clock, per user direction)

| Phase | Target |
|---|---|
| **Stub-deploy-first:** UI scaffold vs stub JSON, deploy, verify public URL | ~12 min |
| Filter + features + centrality + review graph (census already done) | ~8 min |
| LLM classification (Workflow fan-out, reads diffs) | ~18 min |
| Revert adjudication + aggregate + narratives + emit JSON | ~10 min |
| Dashboard polish on real data | ~15 min |
| Final deploy (real data) + browser verification | ~8 min |

## Scope / YAGNI

Cuts if short, in order: (1) re-weight sliders; (2) durability dimension (renormalize to
0.65·Substance + 0.35·ReviewLeverage); (3) avatars/polish; (4) diff-reading for the full
candidate set (keep it for evidence PRs only — that alone defends the thesis).

Non-negotiable core: complete 90-day data, measured reach + LLM-read substance for
contenders, generous candidate gate, top-5 ranking with clickable PR evidence, visible
methodology, volume-vs-impact made legible, working public URL.

## Risk → red-flag mitigation

| Red flag / risk | Mitigation |
|---|---|
| Link doesn't load / >10s | Static site on Vercel CDN; **stub-deployed + verified first**; surge/Pages fallback. |
| Incorrect / incomplete data | Complete census, disjoint-day tiling + dedupe, **assert count == total_count**, bot author/reviewer filtering, **truncation flagged + counted**. |
| Buggy / broken UI | Vanilla static, minimal JS; browser-verify before submit. |
| Doesn't answer "who's most impactful" | Top-5 ranked list is the page's primary content. |
| Score with no explanation | Panel + per-engineer breakdown + clickable evidence + context chips + **relative-scaling disclosure**. |
| Misleading via volume | Trivial-zeroing, measured reach, **concave aggregation**, p95 winsorization, explicit PR-count + AI-% context. |
| True top-5 silently cut | **Generous UNION candidate gate** + deep-work safety net; cut recorded + disclosed. |
| LLM fan-out flaky/slow | **Partial-failure contract**: fallback to heuristic, never crash; fallback rate in `meta`. |
| Overclaiming AI-% | Re-verify signature rate on full census before publishing. |
| Wrong deploy account | Verify `vercel whoami == joseph.ycx@gmail.com` before deploy; fallback host ready. |

## Deliverables

- Dashboard URL (Vercel, `joseph.ycx@gmail.com`).
- Short approach description (measured reach + LLM-read substance from diffs, not volume; AI-aware).
- Timer duration. Export of the coding-agent session.
