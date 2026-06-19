"""Stage 4: combine measured features + LLM complexity into the final ranking.

Per-PR substance uses the CONVEX complexity weight (complexity-1 => 0) so shallow
work scores ~0; substance counts only each engineer's top-30 PRs (serialized by
features.py); aggregation is concave (breadth rewarded, within-area volume damped);
dimensions are min-max scaled WITHIN the candidate cohort; composite scaled to 0-100.

Emits data/dashboard.json. Built-in guard: Gilbert09 must not reach the top 5.
"""
import json
import math
import os
import statistics
from collections import defaultdict

from scripts.areas import complexity_weight

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WEIGHTS = (0.6, 0.3, 0.1)
GITHUB = "https://github.com/PostHog/posthog/pull/"


# ---- pure math helpers (tested) ------------------------------------------- #
def concave_substance(area_to_scores: dict) -> float:
    return sum(math.sqrt(sum(scores)) for scores in area_to_scores.values() if scores)


def per_pr_substance(complexity, reach, critical_boost) -> float:
    return complexity_weight(complexity) * reach * critical_boost


def engineer_substance(pr_rows) -> float:
    area_scores = defaultdict(list)
    for r in pr_rows:
        area_scores[r["area"]].append(per_pr_substance(r["complexity"], r["reach"], r["critical_boost"]))
    return concave_substance(area_scores)


def winsorize(vals, pct=0.95):
    if not vals:
        return vals
    if len(vals) < 10:                       # tiny cohort: don't clamp (review finding #8)
        return list(vals)
    s = sorted(vals)
    cap = s[min(len(s) - 1, round(pct * (len(s) - 1)))]
    return [min(v, cap) for v in vals]


def minmax(vals):
    if not vals:
        return vals
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [0.0 for _ in vals]
    return [(v - lo) / (hi - lo) for v in vals]


def composite(sub, rev, dur, w=WEIGHTS):
    return w[0] * sub + w[1] * rev + w[2] * dur


# ---- build ---------------------------------------------------------------- #
def _load(name):
    return json.load(open(os.path.join(DATA, name)))


def build_dashboard():
    feats = _load("features.json")
    stats = feats["engineers"]
    fmeta = feats["meta"]
    centrality = _load("area_centrality.json")
    cand_rows = _load("candidate_pr_features.json")
    try:
        llm_list = _load("llm_classifications.json")
    except FileNotFoundError:
        llm_list = []
    llm = {int(c["number"]): c for c in llm_list}

    candidates = set(fmeta["candidates"])
    rows_by_login = defaultdict(list)
    for r in cand_rows:
        if r["login"] in candidates:
            rows_by_login[r["login"]].append(r)

    prs_classified = prs_fallback = 0
    eng = {}
    for lg, rows in rows_by_login.items():
        scored = []
        for r in rows:
            c = llm.get(int(r["number"]))
            if c:
                complexity = c["complexity"]
                wt = c.get("work_type", r["work_type"])
                summary = c.get("one_line_summary", r["title"])
                classified = True
                prs_classified += 1
            else:
                complexity = r["size_proxy"]            # per-PR fallback
                wt, summary, classified = r["work_type"], r["title"], False
                prs_fallback += 1
            primary = max(r["areas"], key=lambda a: centrality.get(a, 0)) if r["areas"] else ""
            s = per_pr_substance(complexity, r["reach"], r["critical_boost"])
            scored.append({**r, "complexity": complexity, "work_type": wt, "summary": summary,
                           "classified": classified, "area": primary,
                           "reach_authors": centrality.get(primary, 0),
                           "critical": r["critical_boost"] > 1, "s": s})
        substance_raw = engineer_substance(scored)
        st = stats[lg]
        s_vals = [x["s"] for x in scored]
        eng[lg] = {
            "login": lg, "substance_raw": substance_raw,
            "review_credit": st["review_credit"], "distinct_core_areas": st["distinct_core_areas"],
            "scored": scored, "stats": st,
            "median_pr_substance": round(statistics.median(s_vals), 2) if s_vals else 0.0,
        }

    logins = list(eng)
    sub_w = winsorize([eng[l]["substance_raw"] for l in logins])
    sub_n = dict(zip(logins, minmax(sub_w)))
    rev_n = dict(zip(logins, minmax([eng[l]["review_credit"] for l in logins])))
    dur_n = dict(zip(logins, minmax([float(eng[l]["distinct_core_areas"]) for l in logins])))

    for l in logins:
        eng[l]["dimensions"] = {"substance": round(sub_n[l], 4),
                                "review_leverage": round(rev_n[l], 4),
                                "durability_breadth": round(dur_n[l], 4)}
        eng[l]["composite_raw"] = composite(sub_n[l], rev_n[l], dur_n[l])

    ranked = sorted(logins, key=lambda l: -eng[l]["composite_raw"])
    max_c = eng[ranked[0]]["composite_raw"] if ranked else 1.0
    for l in ranked:
        eng[l]["composite"] = round(eng[l]["composite_raw"] / max_c * 100) if max_c else 0

    # built-in correctness guard
    gilbert_rank = ranked.index("Gilbert09") + 1 if "Gilbert09" in ranked else None

    engineers_out = []
    for i, lg in enumerate(ranked[:5], 1):
        e = eng[lg]
        st = e["stats"]
        evidence = sorted(e["scored"], key=lambda x: -x["s"])[:3]
        engineers_out.append({
            "rank": i, "login": lg,
            "avatar_url": f"https://github.com/{lg}.png",
            "composite": e["composite"],
            "narrative": "",   # filled by narratives workflow
            "dimensions": e["dimensions"],
            "stats": {
                "prs_merged": st["prs_merged"], "non_trivial_prs": st["non_trivial_prs"],
                "reviews_given": st["reviews_given"],
                "ai_assisted_pct": round(st["ai_assisted_pct"], 2),
                "core_areas": st["core_areas"],
                "work_type_mix": st["work_type_mix"],
                "median_pr_substance": e["median_pr_substance"],
            },
            "evidence": [{
                "pr": x["number"], "url": GITHUB + str(x["number"]),
                "title": x["title"], "summary": x["summary"], "work_type": x["work_type"],
                "reach": x["reach_authors"], "critical": x["critical"],
            } for x in evidence],
        })

    meta = {
        "repo": "PostHog/posthog", "window_days": 91,
        "window_start": "2026-03-22", "window_end": "2026-06-20",
        "total_prs_analyzed": fmeta["total_prs_analyzed"], "human_prs": fmeta["human_prs"],
        "bot_prs": fmeta["bot_prs"], "total_engineers": fmeta["total_engineers"],
        "candidates_llm_classified": len(candidates),
        "prs_llm_classified": prs_classified, "prs_heuristic_fallback": prs_fallback,
        "files_truncated_prs": fmeta["files_truncated_prs"],
        "reviews_truncated_prs": fmeta["reviews_truncated_prs"],
        "ai_assisted_pct_repo": fmeta["ai_assisted_pct_repo"],
        "weights": {"substance": WEIGHTS[0], "review_leverage": WEIGHTS[1], "durability_breadth": WEIGHTS[2]},
        "scoring_note": "min-max scaled within the analyzed candidate cohort; 100 = highest among analyzed, not an absolute score",
        "central_areas": fmeta["central_areas"][:8],
        "generated_at": "2026-06-20",
    }
    out = {"meta": meta, "engineers": engineers_out}
    json.dump(out, open(os.path.join(DATA, "dashboard.json"), "w"), indent=2)

    # report
    print(f"classified PRs: {prs_classified}  fallback: {prs_fallback}")
    print("TOP 12 by composite:")
    for i, lg in enumerate(ranked[:12], 1):
        d = eng[lg]["dimensions"]
        print(f"  {i:2}. {lg:22} comp={eng[lg]['composite']:3}  "
              f"sub={d['substance']:.2f} rev={d['review_leverage']:.2f} dur={d['durability_breadth']:.2f}  "
              f"prs={eng[lg]['stats']['prs_merged']}")
    print(f"\nGilbert09 rank: {gilbert_rank}  (guard: must be > 5 or absent)")
    assert gilbert_rank is None or gilbert_rank > 5, "GUARD FAILED: Gilbert09 in top 5 — metric is broken"
    print("✅ correctness guard passed")
    return out


if __name__ == "__main__":
    build_dashboard()
