"""Pure, testable PR-classification primitives.

No I/O. Used by features.py and aggregate.py. The review hardened the
generated-file and work-type matching (anchored, not bare-substring) and added
the convex complexity weighting that makes shallow work score ~0.
"""
import math
import re

# --------------------------------------------------------------------------- #
# Area extraction
# --------------------------------------------------------------------------- #
def area_for_path(path: str) -> str:
    """Two-level directory key, e.g. 'posthog/hogql/parser.py' -> 'posthog/hogql'."""
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else "")


# --------------------------------------------------------------------------- #
# Generated / non-substantive file detection (anchored — review finding #6)
# --------------------------------------------------------------------------- #
_GEN_BASENAMES = {
    "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "poetry.lock", "uv.lock",
    "cargo.lock", "mypy-baseline.txt", ".test_durations", "go.sum",
    "snapshots.yml", "snapshots.yaml",
}
# PostHog-specific generated artifacts (auto-generated from other sources, touched by many)
_GEN_PATHS = {
    "posthog/schema.py",
    "frontend/src/queries/schema/schema-general.json",
    "frontend/src/queries/schema.json",
}
_GEN_SEGMENTS = {"__snapshots__", "__mocks__", "node_modules", "vendor"}
_GEN_SUFFIXES = (".snap", ".min.js", ".lock", ".lockb")


def is_generated_file(path: str) -> bool:
    p = path.lower()
    if p in _GEN_PATHS:
        return True
    base = p.rsplit("/", 1)[-1]
    if base in _GEN_BASENAMES:
        return True
    if set(p.split("/")) & _GEN_SEGMENTS:
        return True
    if p.endswith(_GEN_SUFFIXES):
        return True
    if ".github/workflows/" in p:
        return True
    return False


# --------------------------------------------------------------------------- #
# Work type (conventional-commit aware — review finding #7)
# --------------------------------------------------------------------------- #
_CC_MAP = {
    "feat": "feat", "feature": "feat", "fix": "fix", "hotfix": "fix", "bugfix": "fix",
    "perf": "perf", "refactor": "refactor", "docs": "docs", "doc": "docs",
    "test": "test", "tests": "test", "chore": "chore", "build": "chore", "ci": "chore",
    "style": "refactor", "revert": "revert", "deps": "deps", "dep": "deps",
}
_CC_RE = re.compile(r"^(\w+)(\([^)]*\))?!?:")


def classify_work_type(title: str, labels=None) -> str:
    t = (title or "").strip()
    m = _CC_RE.match(t)
    if m:
        tok = m.group(1).lower()
        if tok in _CC_MAP:
            return _CC_MAP[tok]
    tl = t.lower()
    if tl.startswith("revert"):
        return "revert"
    if re.search(r"\bbugfix\b|\bbug fix\b|^hotfix\b", tl):
        return "fix"
    if tl.startswith(("add ", "implement", "introduce", "support ")):
        return "feat"
    if "refactor" in tl:
        return "refactor"
    if re.search(r"\bperf\b|performance|optimi[sz]", tl):
        return "perf"
    return "other"


# --------------------------------------------------------------------------- #
# CODEOWNERS critical-path boost
# --------------------------------------------------------------------------- #
_CRIT = [
    "posthog/api/authentication.py", "posthog/auth.py",
    "posthog/clickhouse/migrations/", "posthog/hogql/", "rust/persons_migrations/",
]


def critical_boost(paths) -> float:
    for p in paths:
        if any(p.startswith(c) or c in p for c in _CRIT):
            return 1.5
    return 1.0


# --------------------------------------------------------------------------- #
# Triviality (catches generated-only + dependency PRs; depth handled by cw)
# --------------------------------------------------------------------------- #
def is_trivial(pr: dict, effective_files: list) -> bool:
    if len(effective_files) == 0:        # only generated/lock/CI/snapshot files
        return True
    if pr.get("work_type") == "deps":
        return True
    return False


# --------------------------------------------------------------------------- #
# Size proxy (exact — review finding #9). Per-PR fallback only.
# --------------------------------------------------------------------------- #
def size_proxy(additions, deletions) -> int:
    lines = max(0, (additions or 0) + (deletions or 0))
    if lines == 0:
        return 1
    return max(1, min(5, round(math.log(1 + lines, 6))))


# --------------------------------------------------------------------------- #
# Convex complexity weight (review finding #3): complexity-1 => 0 substance
# --------------------------------------------------------------------------- #
_CW = {1: 0.0, 2: 1.0, 3: 3.0, 4: 6.0, 5: 10.0}


def complexity_weight(c) -> float:
    try:
        c = int(round(float(c)))
    except (TypeError, ValueError):
        c = 1
    return _CW.get(max(1, min(5, c)), 0.0)


# --------------------------------------------------------------------------- #
# Bot detection (reviewer logins expose no is_bot flag — review finding #8)
# --------------------------------------------------------------------------- #
REVIEWER_BOT_DENYLIST = {
    "copilot-pull-request-reviewer", "posthog-bot", "sourcery-ai[bot]",
    "graphite-app[bot]", "github-actions[bot]", "dependabot[bot]",
    "sentry-io[bot]", "codecov[bot]", "vercel[bot]",
    # automation accounts whose review-author login exposes no is_bot flag and
    # doesn't match the suffix rules (verified leaking into the candidate set)
    "greptile-apps", "github-actions", "veria-ai", "chatgpt-codex-connector",
    "stamphog",
}


def is_bot_login(login: str) -> bool:
    l = (login or "").lower()
    if l in {x.lower() for x in REVIEWER_BOT_DENYLIST}:
        return True
    return (l.endswith("[bot]") or l.endswith("-bot") or l.endswith("-app")
            or l.endswith("-apps") or l.startswith("app/"))
