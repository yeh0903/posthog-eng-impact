#!/usr/bin/env python3
"""Fetch a complete census of merged PRs in PostHog/posthog over the last 90 days.

Strategy: GitHub search caps at 1000 results/query and a single week can exceed that,
so we fetch in disjoint 2-day windows, with an automatic split to 1-day (then 12h) if a
window hits the 1000 cap. Per-window results are cached to data/windows/ so the run is
resumable. Final merged + deduped output -> data/prs_raw.json.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

REPO = "PostHog/posthog"
START = datetime(2026, 3, 22, tzinfo=timezone.utc)
END = datetime(2026, 6, 20, tzinfo=timezone.utc)  # inclusive day
FIELDS = "number,title,body,labels,author,files,additions,deletions,changedFiles,mergedAt,reviews,url"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN_DIR = os.path.join(ROOT, "data", "windows")
OUT = os.path.join(ROOT, "data", "prs_raw.json")
MAX_WORKERS = 8

os.makedirs(WIN_DIR, exist_ok=True)


def run_gh(date_query: str, retries: int = 3):
    """Run gh pr list for a search date query.

    Returns list of PRs on success, or None if the query keeps timing out
    (504/502/timeout) so the caller can split it into a lighter sub-query.
    Raises only on non-timeout hard failures.
    """
    import time
    cmd = [
        "gh", "pr", "list", "--repo", REPO, "--state", "merged",
        "--search", f"merged:{date_query} sort:created-asc",
        "--limit", "1000", "--json", FIELDS,
    ]
    last_err = ""
    for attempt in range(retries):
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode == 0:
            try:
                return json.loads(p.stdout or "[]")
            except json.JSONDecodeError as e:
                last_err = f"json error: {e}"
        else:
            last_err = p.stderr.strip()
        timeout_like = any(s in last_err for s in ("504", "502", "Gateway")) or "timeout" in last_err.lower()
        if attempt < retries - 1:
            time.sleep(4 * (attempt + 1))
            continue
        if timeout_like:
            return None  # signal: too heavy, split me
        raise RuntimeError(f"gh failed for {date_query}: {last_err}")
    return None


def _floor_day(d: datetime) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def fetch_range(start: datetime, end: datetime, depth: int = 0):
    """Fetch a [start, end] inclusive date range, splitting on the 1000 cap OR timeouts."""
    q = f"{start.date()}..{end.date()}"
    prs = run_gh(q)

    if prs is None:  # timeout -> split smaller
        if start.date() != end.date():
            mid = _floor_day(start + (end - start) / 2)
            return fetch_range(start, mid, depth + 1) + fetch_range(mid + timedelta(days=1), end, depth + 1)
        # single day timed out -> split into 6h quarters
        out = []
        for lo, hi in [("00:00:00", "05:59:59"), ("06:00:00", "11:59:59"),
                       ("12:00:00", "17:59:59"), ("18:00:00", "23:59:59")]:
            sub = run_gh(f"{start.date()}T{lo}..{start.date()}T{hi}")
            if sub is None:
                raise RuntimeError(f"timeout even at 6h granularity for {start.date()} {lo}..{hi}")
            out += sub
        return out

    if len(prs) >= 1000 and start.date() != end.date():
        mid = _floor_day(start + (end - start) / 2)
        return fetch_range(start, mid, depth + 1) + fetch_range(mid + timedelta(days=1), end, depth + 1)
    if len(prs) >= 1000:  # single day still capped -> 12h split
        out = []
        for lo, hi in [("00:00:00", "11:59:59"), ("12:00:00", "23:59:59")]:
            sub = run_gh(f"{start.date()}T{lo}..{start.date()}T{hi}")
            out += (sub or [])
        return out
    return prs


def window_starts():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=2)


def fetch_window(ws: datetime):
    we = min(ws + timedelta(days=1), END)
    cache = os.path.join(WIN_DIR, f"win_{ws.date()}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return ws, json.load(f), True
    prs = fetch_range(ws, we)
    with open(cache, "w") as f:
        json.dump(prs, f)
    return ws, prs, False


def main():
    windows = list(window_starts())
    print(f"Fetching {len(windows)} 2-day windows {START.date()}..{END.date()}", flush=True)
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_window, ws): ws for ws in windows}
        done = 0
        for fut in as_completed(futs):
            ws, prs, cached = fut.result()
            results[ws] = prs
            done += 1
            tag = "cached" if cached else "fetched"
            print(f"[{done}/{len(windows)}] {ws.date()}: {len(prs)} PRs ({tag})", flush=True)

    # merge + dedupe by number
    by_num = {}
    for prs in results.values():
        for pr in prs:
            by_num[pr["number"]] = pr
    merged = sorted(by_num.values(), key=lambda x: x["number"])
    with open(OUT, "w") as f:
        json.dump(merged, f)
    print(f"\nTOTAL unique merged PRs: {len(merged)} -> {OUT}", flush=True)

    bots = sum(1 for p in merged if (p.get("author") or {}).get("is_bot"))
    print(f"bots: {bots}  humans: {len(merged) - bots}", flush=True)


if __name__ == "__main__":
    main()
