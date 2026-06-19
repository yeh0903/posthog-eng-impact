"""Stage 3a: assemble LLM-classification inputs for candidate PRs.

Joins candidate PR numbers against the raw census (for body/labels/files) and
fetches a truncated diff per PR (so the LLM rates complexity from the CODE, not
just the description). Resumable: diffs cached under data/diffs/.

Output: data/to_classify.json — a list of records the classify workflow consumes.
"""
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DIFF_DIR = os.path.join(DATA, "diffs")
REPO = "PostHog/posthog"
DIFF_CAP = 6000        # chars of diff per PR (truncate large diffs)
BODY_CAP = 1500
os.makedirs(DIFF_DIR, exist_ok=True)


def fetch_diff(number: int) -> str:
    cache = os.path.join(DIFF_DIR, f"{number}.txt")
    if os.path.exists(cache):
        return open(cache, encoding="utf-8", errors="replace").read()
    try:
        p = subprocess.run(
            ["gh", "pr", "diff", str(number), "--repo", REPO],
            capture_output=True, text=True, timeout=60,
        )
        diff = p.stdout if p.returncode == 0 else ""
    except Exception:
        diff = ""
    diff = diff[:DIFF_CAP]
    with open(cache, "w", encoding="utf-8") as f:
        f.write(diff)
    return diff


def main():
    cand_features = json.load(open(os.path.join(DATA, "candidate_pr_features.json")))
    raw = json.load(open(os.path.join(DATA, "prs_raw.json")))
    by_num = {int(p["number"]): p for p in raw}

    numbers = [int(r["number"]) for r in cand_features]
    print(f"fetching {len(numbers)} diffs (cached under data/diffs/)…", flush=True)

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_diff, n): n for n in numbers}
        for fut in as_completed(futs):
            fut.result()
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(numbers)} diffs", flush=True)

    records = []
    for r in cand_features:
        n = int(r["number"])
        raw_pr = by_num.get(n, {})
        labels = [l.get("name", "") for l in (raw_pr.get("labels") or [])]
        files = [f.get("path", "") for f in (raw_pr.get("files") or [])][:40]
        diff = fetch_diff(n)
        records.append({
            "number": n,
            "login": r["login"],
            "title": r["title"],
            "body": (raw_pr.get("body") or "")[:BODY_CAP],
            "labels": labels,
            "files": files,
            "additions": r.get("additions", 0),
            "deletions": r.get("deletions", 0),
            "diff": diff,
        })

    out = os.path.join(DATA, "to_classify.json")
    json.dump(records, open(out, "w"))
    have_diff = sum(1 for r in records if r["diff"])
    print(f"wrote {len(records)} records -> {out}  ({have_diff} with non-empty diff)")


if __name__ == "__main__":
    main()
