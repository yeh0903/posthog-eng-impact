"""Stage 5a: build per-engineer narrative inputs for the top 5 (their best PRs + diffs)."""
import json
import os

from scripts.aggregate import per_pr_substance

DATA = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/data"


def main():
    dash = json.load(open(f"{DATA}/dashboard.json"))
    cand = json.load(open(f"{DATA}/candidate_pr_features.json"))
    cent = json.load(open(f"{DATA}/area_centrality.json"))
    llm = {int(c["number"]): c for c in json.load(open(f"{DATA}/llm_classifications.json"))}

    rows_by_login = {}
    for r in cand:
        rows_by_login.setdefault(r["login"], []).append(r)

    os.makedirs(f"{DATA}/narr", exist_ok=True)
    paths = []
    for i, eng in enumerate(dash["engineers"]):
        lg = eng["login"]
        scored = []
        for r in rows_by_login.get(lg, []):
            c = llm.get(int(r["number"]))
            comp = c["complexity"] if c else r["size_proxy"]
            summ = c["one_line_summary"] if c else r["title"]
            primary = max(r["areas"], key=lambda a: cent.get(a, 0)) if r["areas"] else ""
            s = per_pr_substance(comp, r["reach"], r["critical_boost"])
            diff_path = f"{DATA}/diffs/{r['number']}.txt"
            diff = open(diff_path, encoding="utf-8", errors="replace").read()[:4000] if os.path.exists(diff_path) else ""
            scored.append({
                "number": r["number"], "title": r["title"], "summary": summ,
                "complexity": comp, "area": primary, "reach_authors": cent.get(primary, 0),
                "s": round(s, 3), "diff": diff,
            })
        scored.sort(key=lambda x: -x["s"])
        obj = {"login": lg, "stats": eng["stats"], "prs": scored[:6]}
        p = os.path.abspath(f"{DATA}/narr/n{i}.json")
        json.dump(obj, open(p, "w"))
        paths.append(p)
    print(f"wrote {len(paths)} narrative inputs -> {DATA}/narr/")


if __name__ == "__main__":
    main()
