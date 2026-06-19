"""Stage 2: filter bots, derive per-PR features, measure area centrality (reach),
build the review graph, score engineers heuristically, and select LLM candidates.

Emits:
  data/features.json            — per-engineer stats for ALL engineers (+ meta)
  data/candidates.json          — candidate logins + their top-30 non-trivial PR numbers
  data/candidate_pr_features.json — one row per candidate PR (join target for aggregate.py)
  data/area_centrality.json     — {area: distinct_human_authors}

No LLM here — all heuristic. The harsh complexity weighting is applied later in
aggregate.py with LLM-read complexity; here we use a *generous* size-proxy so the
candidate net is wide (review finding: don't let the cheap gate cut deep work).
"""
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict

from scripts.areas import (
    area_for_path, classify_work_type, critical_boost, is_bot_login,
    is_generated_file, is_trivial, size_proxy,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "prs_raw.json")

DEPTH = {"CHANGES_REQUESTED": 1.6, "COMMENTED": 1.3, "APPROVED": 1.0}
AI_SIG = re.compile(
    r"co-authored-by:\s*(claude|cursor|copilot|devin|codex|sweep)|🤖|"
    r"generated with (\[?claude|cursor|copilot)|\bclaude code\b",
    re.I,
)
CORE_CENTRALITY_MIN = 3   # an area counts as "core" if >= this many distinct authors
TOP_K_PRS = 30            # substance counts each engineer's top-30 PRs (anti-volume cap)


# --------------------------------------------------------------------------- #
def _author(pr):
    return (pr.get("author") or {}).get("login") or ""


def _is_human(pr):
    a = pr.get("author") or {}
    return not a.get("is_bot") and not is_bot_login(a.get("login", ""))


def normalize(pr: dict) -> dict:
    files = [f.get("path", "") for f in (pr.get("files") or [])]
    eff = [p for p in files if p and not is_generated_file(p)]
    areas = sorted({area_for_path(p) for p in eff})
    wt = classify_work_type(pr.get("title", ""), pr.get("labels"))
    n = {
        "number": pr["number"], "login": _author(pr), "title": pr.get("title", "") or "",
        "url": pr.get("url", ""), "work_type": wt,
        "areas": areas, "effective_files": eff,
        "additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0),
        "changedFiles": pr.get("changedFiles", 0),
        "files_truncated": pr.get("changedFiles", 0) > len(files),
        "reviews_truncated": len(pr.get("reviews") or []) == 100,
        "ai_assisted": bool(AI_SIG.search(pr.get("body") or "")),
        "size_proxy": size_proxy(pr.get("additions", 0), pr.get("deletions", 0)),
        "critical_boost": critical_boost(eff),
        "reviews": [
            {"login": (r.get("author") or {}).get("login", "") or "", "state": r.get("state", "")}
            for r in (pr.get("reviews") or [])
        ],
    }
    n["trivial"] = is_trivial(n, eff)
    return n


def compute_area_centrality(norm_prs) -> dict:
    a2authors = defaultdict(set)
    for p in norm_prs:
        for ar in p["areas"]:
            a2authors[ar].add(p["login"])
    return {ar: len(s) for ar, s in a2authors.items()}


def reach_of(areas, centrality) -> float:
    if not areas:
        return 0.0
    return math.log1p(max((centrality.get(ar, 0) for ar in areas), default=0))


def _primary_area(areas, centrality):
    return max(areas, key=lambda a: centrality.get(a, 0)) if areas else ""


def heuristic_substance(p, centrality) -> float:
    """Generous (linear in size_proxy) — for casting a wide candidate net."""
    if p["trivial"]:
        return 0.0
    return p["size_proxy"] * reach_of(p["areas"], centrality) * p["critical_boost"]


def review_credit(norm_prs, centrality) -> dict:
    credit = defaultdict(float)
    for p in norm_prs:
        if p["trivial"]:
            continue
        r = reach_of(p["areas"], centrality)
        best = {}
        for rv in p["reviews"]:
            lg = rv["login"]
            if not lg or lg == p["login"] or is_bot_login(lg):
                continue
            w = DEPTH.get(rv["state"])
            if w is None:
                continue
            if w > best.get(lg, 0):
                best[lg] = w
        n = len(best)
        if n == 0:
            continue
        for lg, w in best.items():
            credit[lg] += r * w / n
    return dict(credit)


def reviews_given_count(norm_prs) -> dict:
    cnt = defaultdict(int)
    for p in norm_prs:
        if p["trivial"]:
            continue
        seen = set()
        for rv in p["reviews"]:
            lg = rv["login"]
            if lg and lg != p["login"] and not is_bot_login(lg) and DEPTH.get(rv["state"]) and lg not in seen:
                cnt[lg] += 1
                seen.add(lg)
    return dict(cnt)


def engineer_stats(norm_prs, centrality, rcredit, rgiven) -> dict:
    by_eng = defaultdict(list)
    for p in norm_prs:
        by_eng[p["login"]].append(p)

    # universe = authors UNION reviewers (a pure reviewer can still be impactful)
    universe = set(by_eng) | set(rcredit) | set(rgiven)
    stats = {}
    for lg in universe:
        prs = by_eng.get(lg, [])
        nontriv = [p for p in prs if not p["trivial"]]
        for p in nontriv:
            p["_hs"] = heuristic_substance(p, centrality)
        top = sorted(nontriv, key=lambda p: -p["_hs"])[:TOP_K_PRS]
        area_sums = defaultdict(float)
        for p in top:
            area_sums[_primary_area(p["areas"], centrality)] += p["_hs"]
        heur_sub = sum(math.sqrt(v) for v in area_sums.values())
        core_areas = sorted(
            {a for p in nontriv for a in p["areas"] if centrality.get(a, 0) >= CORE_CENTRALITY_MIN},
            key=lambda a: -centrality.get(a, 0),
        )
        hs_vals = [p["_hs"] for p in nontriv]
        stats[lg] = {
            "login": lg,
            "prs_merged": len(prs),
            "non_trivial_prs": len(nontriv),
            "reviews_given": rgiven.get(lg, 0),
            "heuristic_substance": heur_sub,
            "best_pr_substance": max(hs_vals, default=0.0),
            "review_credit": rcredit.get(lg, 0.0),
            "distinct_core_areas": len(core_areas),
            "core_areas": core_areas[:4],
            "ai_assisted_pct": (sum(p["ai_assisted"] for p in prs) / len(prs)) if prs else 0.0,
            "work_type_mix": dict(Counter(p["work_type"] for p in prs)),
            "median_pr_substance": round(statistics.median(hs_vals), 2) if hs_vals else 0.0,
            "has_critical": any(p["critical_boost"] > 1 for p in nontriv),
            "top_pr_numbers": [p["number"] for p in top],
        }
    return stats


def select_candidates(stats) -> set:
    logins = list(stats)
    if not logins:
        return set()
    by_sub = sorted(logins, key=lambda l: -stats[l]["heuristic_substance"])[:20]
    by_rev = sorted(logins, key=lambda l: -stats[l]["review_credit"])[:10]
    bests = sorted((stats[l]["best_pr_substance"] for l in logins), reverse=True)
    decile = bests[max(0, len(bests) // 10 - 1)] if bests else 0.0
    deep = [l for l in logins if stats[l]["best_pr_substance"] >= decile and stats[l]["best_pr_substance"] > 0]
    crit = [l for l in logins if stats[l].get("has_critical")]
    cand = set(by_sub) | set(by_rev) | set(deep) | set(crit)
    # soft cap at 35, but always keep the substance/review leaders and deep-work admits
    if len(cand) > 35:
        keep = set(by_sub) | set(by_rev) | set(deep[:5])
        extra = sorted(cand - keep, key=lambda l: -stats[l]["heuristic_substance"])
        cand = keep | set(extra[: max(0, 35 - len(keep))])
    return cand


def main():
    raw = json.load(open(RAW))
    human = [pr for pr in raw if _is_human(pr)]
    norm = [normalize(pr) for pr in human]

    centrality = compute_area_centrality(norm)
    rcredit = review_credit(norm, centrality)
    rgiven = reviews_given_count(norm)
    stats = engineer_stats(norm, centrality, rcredit, rgiven)
    candidates = select_candidates(stats)

    # candidate PR feature rows (join target for aggregate.py)
    cand_pr_numbers = set()
    cand_meta = {}
    for lg in candidates:
        nums = stats[lg]["top_pr_numbers"]
        cand_meta[lg] = nums
        cand_pr_numbers.update(nums)
    by_num = {p["number"]: p for p in norm}
    cand_pr_features = []
    for num in sorted(cand_pr_numbers):
        p = by_num[num]
        cand_pr_features.append({
            "number": num, "login": p["login"], "title": p["title"], "url": p["url"],
            "areas": p["areas"], "reach": round(reach_of(p["areas"], centrality), 4),
            "critical_boost": p["critical_boost"], "trivial": p["trivial"],
            "size_proxy": p["size_proxy"], "work_type": p["work_type"],
            "heuristic_substance": round(heuristic_substance(p, centrality), 4),
            "additions": p["additions"], "deletions": p["deletions"],
            "ai_assisted": p["ai_assisted"],
        })

    ai_pct = sum(p["ai_assisted"] for p in norm) / len(norm) if norm else 0.0
    meta = {
        "human_prs": len(human), "bot_prs": len(raw) - len(human),
        "total_prs_analyzed": len(raw), "total_engineers": len(stats),
        "candidates": sorted(candidates),
        "ai_assisted_pct_repo": round(ai_pct, 4),
        "files_truncated_prs": sum(p["files_truncated"] for p in norm),
        "reviews_truncated_prs": sum(p["reviews_truncated"] for p in norm),
        "central_areas": sorted(
            [{"area": a, "distinct_authors": c} for a, c in centrality.items()],
            key=lambda x: -x["distinct_authors"])[:15],
    }

    json.dump({"meta": meta, "engineers": stats}, open(os.path.join(DATA, "features.json"), "w"))
    json.dump(cand_meta, open(os.path.join(DATA, "candidates.json"), "w"))
    json.dump(cand_pr_features, open(os.path.join(DATA, "candidate_pr_features.json"), "w"))
    json.dump(centrality, open(os.path.join(DATA, "area_centrality.json"), "w"))

    print(f"human PRs: {meta['human_prs']}  bots: {meta['bot_prs']}  engineers: {meta['total_engineers']}")
    print(f"AI-assisted: {ai_pct:.1%}  files_truncated: {meta['files_truncated_prs']}  reviews_truncated: {meta['reviews_truncated_prs']}")
    print(f"candidates: {len(candidates)}  candidate PRs to classify: {len(cand_pr_features)}")
    print("central areas:", ", ".join(f"{a['area']}({a['distinct_authors']})" for a in meta["central_areas"][:8]))
    top = sorted(stats.values(), key=lambda s: -s["heuristic_substance"])[:8]
    print("provisional top by heuristic substance:")
    for s in top:
        print(f"  {s['login']:24} hsub={s['heuristic_substance']:7.2f} rev={s['review_credit']:7.2f} "
              f"prs={s['prs_merged']:4} nt={s['non_trivial_prs']:4} areas={s['distinct_core_areas']}")


if __name__ == "__main__":
    main()
