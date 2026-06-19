from scripts.features import (
    normalize, compute_area_centrality, reach_of, review_credit, select_candidates,
)


def _pr(number, login, files, title="feat: x", reviews=None, body="", additions=50, deletions=10,
        is_bot=False, changedFiles=None):
    return {
        "number": number, "title": title, "body": body,
        "author": {"login": login, "is_bot": is_bot},
        "files": [{"path": p} for p in files],
        "additions": additions, "deletions": deletions,
        "changedFiles": changedFiles if changedFiles is not None else len(files),
        "reviews": reviews or [], "labels": [], "url": f"u/{number}",
    }


def test_area_centrality_distinct_authors_excludes_generated():
    prs = [
        normalize(_pr(1, "alice", ["posthog/hogql/a.py"])),
        normalize(_pr(2, "bob", ["posthog/hogql/b.py"])),
        normalize(_pr(3, "alice", ["posthog/hogql/c.py", "pnpm-lock.yaml"])),
    ]
    c = compute_area_centrality(prs)
    assert c["posthog/hogql"] == 2          # alice + bob, distinct
    assert "pnpm-lock.yaml" not in c         # generated file produced no area


def test_reach_monotonic_in_centrality():
    c = {"frontend/src": 44, "products/x": 2}
    assert reach_of(["frontend/src"], c) > reach_of(["products/x"], c)


def test_review_credit_splits_and_excludes_bots_and_self():
    c = {"posthog/hogql": 10}
    pr = normalize(_pr(1, "author", ["posthog/hogql/a.py"], reviews=[
        {"author": {"login": "rev1"}, "state": "APPROVED"},
        {"author": {"login": "rev2"}, "state": "CHANGES_REQUESTED"},
        {"author": {"login": "copilot-pull-request-reviewer"}, "state": "COMMENTED"},
        {"author": {"login": "author"}, "state": "APPROVED"},  # self-review ignored
    ]))
    cr = review_credit([pr], c)
    assert "copilot-pull-request-reviewer" not in cr  # bot excluded
    assert "author" not in cr                          # self excluded
    # 2 real reviewers => credit split by 2; CHANGES_REQUESTED weighted higher than APPROVED
    assert cr["rev2"] > cr["rev1"] > 0


def test_select_candidates_admits_few_but_deep():
    # prolific shallow engineer vs an engineer with ONE very high-substance PR
    stats = {
        "prolific": {"login": "prolific", "heuristic_substance": 50.0, "review_credit": 5.0,
                     "best_pr_substance": 2.0, "has_critical": False},
        "deep": {"login": "deep", "heuristic_substance": 3.0, "review_credit": 0.0,
                 "best_pr_substance": 40.0, "has_critical": True},
    }
    # pad with low-substance others so 'deep' is NOT in top-20-by-substance
    for i in range(25):
        stats[f"e{i}"] = {"login": f"e{i}", "heuristic_substance": 5.0 + i, "review_credit": 1.0,
                          "best_pr_substance": 1.0, "has_critical": False}
    cands = select_candidates(stats)
    assert "deep" in cands   # admitted via deep-work / critical-path safety net, not volume
