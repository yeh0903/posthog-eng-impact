# PostHog Engineering Impact Dashboard — Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax. Execution is inline in this
> session (user directed an autonomous end-to-end run). TDD on pure scoring logic;
> verification (run + inspect / browser) on data, LLM, and UI phases.

**Goal:** Ship a hosted single-page dashboard ranking the top-5 most impactful engineers in
`PostHog/posthog` over the last 90 days, by **measured reach × LLM-read substance**, not volume.

**Architecture:** Offline Python funnel (census → features → bounded LLM classification →
aggregate) emits a static `dashboard.json`; a vanilla static page renders it; hosted on
Vercel CDN. Decoupled so the page loads instantly and the render layer is swappable.

**Tech Stack:** Python 3.13 (stdlib only), `gh` CLI, Workflow tool (LLM fan-out), vanilla
HTML/CSS/JS + Chart-less hand-rolled SVG bars, Vercel Hobby static deploy.

**Source of truth:** `docs/superpowers/specs/2026-06-20-...-design.md` (v4).
**Data already gathered:** `data/prs_raw.json` (8,976 PRs, verified == search total).

---

## File Structure

- `scripts/fetch_prs.py` — census fetcher (DONE).
- `scripts/areas.py` — pure functions: path→area, generated-file test, work-type, critical
  boost, trivial test, denylists. **Testable.**
- `scripts/features.py` — load census, filter bots, per-PR features, measured area centrality,
  review graph, heuristic engineer scores, candidate selection. Emits `data/features.json`,
  `data/candidates.json`. **Core logic testable.**
- `scripts/classify_prep.py` — build LLM batches (candidate PRs + truncated diffs) →
  `data/to_classify.json`.
- `workflows/classify.js` — Workflow fan-out → `data/llm_classifications.json`.
- `scripts/aggregate.py` — merge heuristic+LLM, concave substance, review-credit split,
  winsorize+minmax, composite, emit `data/dashboard.json`. **Core logic testable.**
- `workflows/narratives.js` — top-5 narratives from real diffs → merged into dashboard.json.
- `tests/test_areas.py`, `tests/test_features.py`, `tests/test_aggregate.py` — pytest.
- `public/index.html`, `public/app.js`, `public/styles.css` — the dashboard.
- `public/dashboard.json` — built artifact (stub first, real later).
- `vercel.json` — static config.

---

## Phase 0 — Stub deploy (de-risk the public URL FIRST)

### Task 0.1: Scaffold the static page against a stub

**Files:** Create `public/index.html`, `public/app.js`, `public/styles.css`,
`public/dashboard.json` (stub), `vercel.json`.

- [ ] **Step 1:** Write `public/dashboard.json` stub with `meta` (per schema) + 5 fake
  engineers (rank, login, composite, narrative, dimensions, stats, 2 evidence PRs each).
- [ ] **Step 2:** Write `index.html` + `styles.css` + `app.js` that `fetch('./dashboard.json')`
  and render: header (title, definition, counts, AI-assist headline, methodology `<details>`),
  then 5 collapsed rows (rank, login, composite bar, narrative) that expand on click to show a
  dimension stacked bar, context chips, and linked evidence PRs.
- [ ] **Step 3:** Write `vercel.json`: `{ "cleanUrls": true, "outputDirectory": "public" }`
  (static; no build).
- [ ] **Step 4:** Verify locally.

Run: `cd public && python3 -m http.server 8765 &` then `curl -s localhost:8765 | head -5`
Expected: HTML returned; open in browser later for visual check.

- [ ] **Step 5: Commit.** `git add -A && git commit -m "feat: stub dashboard + static scaffold"`

### Task 0.2: Confirm Vercel account, then stub-deploy

- [ ] **Step 1:** `vercel whoami`. If not `joseph.ycx@gmail.com`, **pause and ask the user to
  `vercel login`** as that account (interactive — cannot be done for them). Re-check whoami.
- [ ] **Step 2:** Deploy: `vercel deploy --prod --yes public` (or `vercel --prod` from a
  linked project). Capture the public URL.
- [ ] **Step 3:** Verify the public URL loads <10s with the stub via Playwright (screenshot,
  no console errors). Fallback if Vercel auth blocked: `npx surge ./public`.
- [ ] **Step 4: Commit** any config. The deliverable (a working link) now exists.

---

## Phase 1 — Pure classification logic (`scripts/areas.py`) — TDD

### Task 1.1: Path/area + generated-file + work-type + critical-boost + trivial

**Files:** Create `scripts/areas.py`, `tests/test_areas.py`.

- [ ] **Step 1: Write failing tests** (`tests/test_areas.py`):

```python
from scripts.areas import (area_for_path, is_generated_file, classify_work_type,
                           critical_boost, is_trivial)

def test_area_for_path_two_level():
    assert area_for_path("posthog/hogql/parser.py") == "posthog/hogql"
    assert area_for_path("frontend/src/scenes/X.tsx") == "frontend/src"
    assert area_for_path("README.md") == "README.md"

def test_is_generated_file():
    assert is_generated_file("pnpm-lock.yaml")
    assert is_generated_file("frontend/__snapshots__/a.snap")
    assert is_generated_file(".github/workflows/ci.yml")
    assert not is_generated_file("posthog/api/foo.py")

def test_classify_work_type():
    assert classify_work_type("fix(snowflake): retry", []) == "fix"
    assert classify_work_type("feat: add cohort filter", []) == "feat"
    assert classify_work_type("Revert \"feat: x\"", []) == "revert"
    assert classify_work_type("chore: bump deps", []) == "chore"

def test_critical_boost():
    assert critical_boost(["posthog/hogql/parser.py"]) == 1.5
    assert critical_boost(["posthog/api/authentication.py"]) == 1.5
    assert critical_boost(["frontend/src/x.tsx"]) == 1.0

def test_is_trivial():
    # only generated files -> trivial
    assert is_trivial({"work_type":"chore","additions":2,"deletions":0,"changedFiles":1},
                      effective_files=[])
    # one-line non-core -> trivial
    assert is_trivial({"work_type":"fix","additions":1,"deletions":1,"changedFiles":1},
                      effective_files=["frontend/src/x.tsx"]) is False  # has real file; not auto-trivial
```

- [ ] **Step 2: Run, expect fail.** `python3 -m pytest tests/test_areas.py -q` → fail (no module).
- [ ] **Step 3: Implement `scripts/areas.py`:**

```python
import re

def area_for_path(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")

_GEN = ["pnpm-lock.yaml", "yarn.lock", "package-lock.json", "poetry.lock", "uv.lock",
        "cargo.lock", ".github/workflows", "snapshot", "__snapshots__", ".snap",
        "/generated/", "mypy-baseline", ".test_durations", "/dist/", ".min.js"]
def is_generated_file(path: str) -> bool:
    p = path.lower()
    return any(g in p for g in _GEN)

_WT = [("revert", r"^revert"), ("deps", r"(bump |dependabot|upgrade .* to |deps\b)"),
       ("docs", r"^docs|documentation"), ("test", r"^test\b|adds? tests"),
       ("chore", r"^chore|^ci\b|^build\b"), ("perf", r"^perf|performance|optimi[sz]"),
       ("refactor", r"^refactor"), ("fix", r"^fix|bug|hotfix"),
       ("feat", r"^feat|^add |implement|introduce|support ")]
_WT = [(k, re.compile(rx, re.I)) for k, rx in _WT]
def classify_work_type(title: str, labels) -> str:
    t = title or ""
    for k, rx in _WT:
        if rx.search(t):
            return k
    return "other"

_CRIT = ["posthog/api/authentication.py", "posthog/auth.py",
         "posthog/clickhouse/migrations/", "posthog/hogql/", "rust/persons_migrations/"]
def critical_boost(paths) -> float:
    for p in paths:
        if any(p.startswith(c) or c in p for c in _CRIT):
            return 1.5
    return 1.0

def is_trivial(pr: dict, effective_files: list) -> bool:
    if len(effective_files) == 0:               # only generated/lock/CI changes
        return True
    if pr.get("work_type") == "deps":
        return True
    size = pr.get("additions", 0) + pr.get("deletions", 0)
    if pr.get("changedFiles", 0) <= 1 and size <= 5:   # one-liner noise
        return True
    return False

# Bot/author + reviewer denylists (seeded; reviewer logins have no is_bot flag)
REVIEWER_BOT_DENYLIST = {"copilot-pull-request-reviewer", "posthog-bot",
                         "sourcery-ai[bot]", "graphite-app[bot]"}
def is_bot_login(login: str) -> bool:
    l = (login or "").lower()
    return l in {x.lower() for x in REVIEWER_BOT_DENYLIST} or l.endswith("[bot]") \
        or l.endswith("-bot") or l.endswith("-app") or l.startswith("app/")
```

- [ ] **Step 4: Run, expect pass.** `python3 -m pytest tests/test_areas.py -q`
- [ ] **Step 5: Commit.** `git add scripts/areas.py tests/test_areas.py && git commit -m "feat: PR classification primitives + tests"`

---

## Phase 2 — Features + review graph + candidates (`scripts/features.py`) — TDD core

### Task 2.1: Area centrality (measured reach)

**Files:** Create `scripts/features.py`, `tests/test_features.py`.

- [ ] **Step 1: Failing test** for `area_centrality(prs) -> {area: distinct_human_author_count}`,
  excluding generated files. Assert a known area accumulates distinct authors and generated
  files don't create areas.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement `area_centrality`: for each human PR, for each non-generated file,
  add `pr.author.login` to `set` per area; return `{area: len(set)}`. `reach(paths)` =
  `log1p(max centrality among the PR's non-generated areas)`.
- [ ] **Step 4:** Run → pass. **Step 5:** Commit.

### Task 2.2: Review graph with credit-splitting

- [ ] **Step 1: Failing test:** `review_credit(prs, area_centrality)` returns per-reviewer
  credit where a PR with 2 non-bot reviewers splits its review value in half; bot reviewers
  (`copilot-pull-request-reviewer`) and self-reviews excluded; APPROVED < COMMENTED/CHANGES_REQUESTED.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement: for each non-trivial PR, `value = reach(pr) * depth_weight` where
  depth_weight uses the *strongest* review state per reviewer (APPROVED=1.0, COMMENTED=1.3,
  CHANGES_REQUESTED=1.6); split `value` equally across the PR's non-bot, non-author reviewers.
- [ ] **Step 4:** Run → pass. **Step 5:** Commit.

### Task 2.3: Per-PR features + per-engineer heuristic scores + candidate UNION

- [ ] **Step 1: Failing test:** `select_candidates(engineers)` returns the UNION of (a) top-20
  by heuristic substance, (b) top-10 by review credit, (c) anyone with a critical/top-quartile-
  reach non-trivial PR, (d) anyone whose best single-PR substance is top-decile. Assert a
  synthetic "few-but-deep" engineer (1 high-reach critical PR, low volume) IS selected.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement `build_features()`:
  - load `data/prs_raw.json`; drop `author.is_bot` and `is_bot_login(author)`.
  - per PR: `work_type`, `effective_files` (non-generated), `areas` (set), `files_truncated`
    = `changedFiles > len(files)`, `ai_assisted` (body matches `Co-Authored-By: (Claude|
    Cursor|Copilot)|🤖|Generated with`), `trivial`, `reach`, `critical_boost`,
    `heuristic_substance` = `size_proxy(complexity) * reach * critical_boost` for non-trivial
    else 0, where `size_proxy` ∈ [1..5] from `log` of changed lines (capped).
  - per engineer aggregate: heuristic substance (concave per Phase 4), review credit, distinct
    core areas, pr counts, ai pct, work_type mix, best single-PR substance.
  - `select_candidates`; write `data/features.json` (all engineers' stats) +
    `data/candidates.json` (candidate logins + their top-30 non-trivial PR numbers).
  - print: human PRs, distinct engineers, ai_assisted_pct_repo, files/reviews truncated counts,
    candidate count, central_areas top 12.
- [ ] **Step 4:** Run tests → pass. Then run `python3 -m scripts.features` and **inspect**:
  ai% in 40–95% range, central_areas match recon (frontend/src high), candidates ~20–30 incl.
  expected names; **Gilbert09 present as candidate but flag to watch**.
- [ ] **Step 5: Commit.**

---

## Phase 3 — LLM classification (reads diffs), bounded fan-out

### Task 3.1: Prepare classification batches with truncated diffs

**Files:** Create `scripts/classify_prep.py`.

- [ ] **Step 1:** Load `data/prs_raw.json` and build a `{int(number) -> record}` index (each
  record carries `title`, `body`, `labels`, `files`, `additions`, `deletions`). Load
  `data/candidates.json` (candidate logins + their top-30 non-trivial PR numbers) and join its
  PR numbers against that index. For each candidate PR, assemble a record:
  `{number, title, body[:1500], labels, files[:40] paths, additions, deletions}` from the joined
  `prs_raw` record (`number` is an int in `prs_raw.json`, so keying by int is safe). Fetch a
  **truncated diff**: `gh pr diff <n> --repo PostHog/posthog | head -c 6000` (cap per PR;
  skip on error). Write `data/to_classify.json` (list of records). Batch into groups of ~20.
- [ ] **Step 2:** Run; inspect count (~600–900) and that diffs are populated for most.
- [ ] **Step 3: Commit.**

### Task 3.2: Workflow fan-out classification

**Files:** Create `workflows/classify.js` (invoked via the Workflow tool).

- [ ] **Step 1:** Workflow reads `data/to_classify.json`, pipelines batches to subagents with a
  strict schema `{classifications: [{number, work_type, complexity:1-5, one_line_summary}]}`.
  Prompt: "Read each PR's title/body/paths/diff. Rate complexity 1–5 (1=trivial/mechanical,
  5=deep architectural/algorithmic). Summarize what it accomplished in one line. Judge from the
  CODE, not the description's claims."
- [ ] **Step 2:** **Partial-failure contract:** validate each item; missing/out-of-range →
  omit (aggregate falls back to heuristic). Write `data/llm_classifications.json` +
  `{prs_llm_classified, prs_failed}`.
- [ ] **Step 3:** Run via Workflow tool; inspect classified count and fallback rate.
- [ ] **Step 4: Commit.**

---

## Phase 4 — Aggregate → `dashboard.json` (`scripts/aggregate.py`) — TDD core

### Task 4.1: Concave substance + winsorize + minmax + composite

**Files:** Create `scripts/aggregate.py`, `tests/test_aggregate.py`.

- [ ] **Step 1: Failing tests:**

```python
from scripts.aggregate import concave_substance, winsorize, minmax, composite

def test_concave_diminishing_returns_within_area():
    # 4 PRs in ONE area give less than 4x a single PR (sqrt diminishing returns)
    assert concave_substance({"A":[1,1,1,1]}) < 4 * concave_substance({"A":[1]})

def test_concave_breadth_beats_concentration():
    # same total substance spread over 4 areas beats it concentrated in 1 area
    spread = concave_substance({"A":[1],"B":[1],"C":[1],"D":[1]})   # 4 * sqrt(1) = 4
    concentrated = concave_substance({"A":[1,1,1,1]})               # sqrt(4) = 2
    assert spread > concentrated

def test_winsorize_caps_outlier():
    vals=[1,1,1,1,100]
    w=winsorize(vals, pct=0.95)
    assert max(w) < 100 and max(w) >= 1

def test_minmax_unit_range():
    assert minmax([2,4,6]) == [0.0,0.5,1.0]

def test_composite_weights():
    c=composite(sub=1.0, rev=0.0, dur=0.0, w=(0.6,0.3,0.1))
    assert abs(c-0.6) < 1e-9
```

- [ ] **Step 2:** Run → fail.
- [ ] **Step 3: Implement:**

```python
import math

def concave_substance(area_to_scores: dict) -> float:
    # inner per-area sqrt of summed per-PR substance; sum across areas
    return sum(math.sqrt(sum(scores)) for scores in area_to_scores.values() if scores)

def winsorize(vals, pct=0.95):
    if not vals: return vals
    s=sorted(vals); cap=s[min(len(s)-1, int(pct*(len(s)-1)))]
    return [min(v,cap) for v in vals]

def minmax(vals):
    if not vals: return vals
    lo,hi=min(vals),max(vals)
    if hi==lo: return [0.0 for _ in vals]
    return [(v-lo)/(hi-lo) for v in vals]

def composite(sub, rev, dur, w=(0.6,0.3,0.1)):
    return w[0]*sub + w[1]*rev + w[2]*dur
```

- [ ] **Step 4:** Run → pass. **Step 5:** Commit.

### Task 4.2: Assemble dashboard.json + the Gilbert09 correctness guard

- [ ] **Step 1: Failing test** `test_gilbert_not_top5_smoke`: a synthetic dataset where one
  engineer has 500 trivial single-area PRs and another has 5 high-reach critical PRs — assert
  the deep engineer outranks the prolific one after full aggregation.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement `build_dashboard()`: merge LLM complexity (fallback to size proxy),
  recompute per-PR substance = `complexity * reach * critical_boost`, group by engineer→area,
  `concave_substance`, winsorize across candidates, minmax each dimension within the candidate
  cohort, composite, scale 0–100, rank, take top 5. Attach stats + evidence (top PRs by
  substance) + placeholder narrative. Write `data/dashboard.json` with full `meta`.
- [ ] **Step 4:** Run tests → pass. Run `python3 -m scripts.aggregate`; **inspect top 5 and
  ASSERT Gilbert09 is NOT #1–#5** (the built-in correctness test). If he is, stop and debug
  trivial-filtering / concavity / reach before proceeding.
- [ ] **Step 5: Commit.**

---

## Phase 5 — Narratives from real diffs (top 5)

**Files:** Create `workflows/narratives.js`.

- [ ] **Step 1:** For each top-5 engineer, gather their 2–3 evidence PRs; fetch truncated
  diffs; a subagent writes a 1–2 sentence narrative ("what they accomplished") + refined
  evidence one-liners grounded in the diff. Strict schema; on failure keep placeholder.
- [ ] **Step 2:** Run via Workflow tool; merge into `data/dashboard.json`.
- [ ] **Step 3:** Inspect narratives read accurately. **Commit.**

---

## Phase 6 — Real data into the page + polish + redeploy

- [ ] **Step 1:** Copy `data/dashboard.json` → `public/dashboard.json`.
- [ ] **Step 2:** Open the deployed/local page in Playwright; verify: top-5 render, collapsed
  view fits one 1366×768 screen, expand shows breakdown + chips + working GitHub links, AI-%
  headline present, methodology panel complete, **0 console errors**, load <10s.
- [ ] **Step 3:** Polish spacing/typography only as needed to fit one screen.
- [ ] **Step 4:** Redeploy to Vercel prod; re-verify the public URL.
- [ ] **Step 5: Commit.**

---

## Phase 7 — Final verification + writeup

- [ ] **Step 1:** Run all tests: `python3 -m pytest -q`. Expected: all pass.
- [ ] **Step 2:** Re-confirm `meta` counts in published JSON match census (8,976) and the
  AI-% is the re-verified full-census number.
- [ ] **Step 3:** Write `README.md`: approach (measured reach × LLM-read substance, AI-aware),
  how to reproduce, the public URL.
- [ ] **Step 4:** Final Playwright pass on the production URL from a cold load. **Commit.**

---

## Self-review notes (filled after drafting)

- Spec coverage: census ✓(done), bot filter ✓(1.1/2.3), measured reach ✓(2.1), review split
  ✓(2.2), generous candidate gate ✓(2.3), concave substance ✓(4.1), LLM-from-diffs ✓(3.x/5),
  truncation handling ✓(2.3 flags), partial-failure ✓(3.2), Gilbert09 guard ✓(4.2),
  stub-deploy-first ✓(Phase 0), relative-scaling disclosure ✓(UI 0.1/6), fallback host ✓(0.2).
- Revert adjudication (spec step 5) folded into durability as a light modifier; deferred as a
  YAGNI cut if time-short (reverts are sparse, ~60 repo-wide, 0.1 weight).
