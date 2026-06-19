from scripts.areas import (
    area_for_path, is_generated_file, classify_work_type, critical_boost,
    is_trivial, size_proxy, complexity_weight, is_bot_login,
)


def test_area_for_path_two_level():
    assert area_for_path("posthog/hogql/parser.py") == "posthog/hogql"
    assert area_for_path("frontend/src/scenes/X.tsx") == "frontend/src"
    assert area_for_path("README.md") == "README.md"


def test_is_generated_file_true():
    assert is_generated_file("pnpm-lock.yaml")
    assert is_generated_file("frontend/src/__snapshots__/a.test.tsx.snap")
    assert is_generated_file(".github/workflows/ci.yml")
    assert is_generated_file("rust/Cargo.lock")
    assert is_generated_file("posthog/schema.py")        # PostHog generated
    assert is_generated_file("frontend/snapshots.yml")   # visual-snapshot manifest


def test_is_generated_file_false_for_legit_source():
    # review finding #6: bare-substring 'snapshot' must NOT flag legit source files
    assert not is_generated_file("posthog/api/foo.py")
    assert not is_generated_file("posthog/session_recordings/snapshot_service.py")
    assert not is_generated_file("frontend/src/lib/utils.ts")


def test_classify_work_type_conventional_prefix():
    assert classify_work_type("fix(snowflake): retry", []) == "fix"
    assert classify_work_type("feat: add cohort filter", []) == "feat"
    assert classify_work_type("chore: bump deps", []) == "chore"
    assert classify_work_type('Revert "feat: x"', []) == "revert"
    assert classify_work_type("perf(hogql): faster joins", []) == "perf"


def test_classify_work_type_does_not_misfire_on_bug_substring():
    # review finding #7: 'debug'/'feat ... bug' must not classify as fix
    assert classify_work_type("feat: add debug panel", []) == "feat"
    assert classify_work_type("Add debugging tools", []) == "feat"


def test_critical_boost():
    assert critical_boost(["posthog/hogql/parser.py"]) == 1.5
    assert critical_boost(["posthog/api/authentication.py"]) == 1.5
    assert critical_boost(["frontend/src/x.tsx"]) == 1.0


def test_is_trivial():
    # only generated files -> trivial
    assert is_trivial({"work_type": "chore"}, effective_files=[]) is True
    # dependency bump -> trivial
    assert is_trivial({"work_type": "deps"}, effective_files=["package.json"]) is True
    # a small but real source change is NOT auto-trivial (complexity weighting handles depth)
    assert is_trivial({"work_type": "fix"}, effective_files=["frontend/src/x.tsx"]) is False


def test_size_proxy_band():
    # review finding #9: exact, deterministic, spans 1..5
    assert size_proxy(0, 0) == 1
    assert size_proxy(3, 2) == 1        # 5 lines
    assert size_proxy(10, 10) == 2      # 20 lines
    assert size_proxy(300, 200) == 3    # 500 lines
    assert size_proxy(3000, 2000) == 5  # 5000 lines
    assert 1 <= size_proxy(100, 0) <= 5


def test_complexity_weight_convex():
    # review finding #3: complexity-1 contributes zero; steep growth
    assert complexity_weight(1) == 0.0
    assert complexity_weight(5) == 10.0
    assert complexity_weight(3) > complexity_weight(2) * 2  # convex
    assert complexity_weight(99) == 10.0  # clamps


def test_is_bot_login():
    assert is_bot_login("dependabot[bot]")
    assert is_bot_login("copilot-pull-request-reviewer")
    assert is_bot_login("posthog-bot")
    assert not is_bot_login("fuziontech")


def test_is_bot_login_catches_unflagged_automation():
    # review finding: these leaked into the candidate set (no [bot] suffix / is_bot flag)
    for bot in ["greptile-apps", "github-actions", "veria-ai", "chatgpt-codex-connector", "stamphog"]:
        assert is_bot_login(bot), bot
    assert not is_bot_login("benjackwhite")  # real engineer not caught
