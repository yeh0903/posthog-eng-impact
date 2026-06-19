import math

from scripts.aggregate import (
    concave_substance, winsorize, minmax, composite, engineer_substance, per_pr_substance,
)


def test_concave_diminishing_returns_within_area():
    # 4 PRs in ONE area give less than 4x a single PR (sqrt diminishing returns)
    assert concave_substance({"A": [1, 1, 1, 1]}) < 4 * concave_substance({"A": [1]})


def test_concave_breadth_beats_concentration():
    spread = concave_substance({"A": [1], "B": [1], "C": [1], "D": [1]})  # 4 * 1 = 4
    concentrated = concave_substance({"A": [1, 1, 1, 1]})                  # sqrt(4) = 2
    assert spread > concentrated


def test_winsorize_caps_outlier():
    vals = [1] * 20 + [100]  # 21 points: the single 100 is above the 95th percentile
    w = winsorize(vals, pct=0.95)
    assert max(w) < 100 and max(w) >= 1


def test_winsorize_tiny_cohort_unchanged():
    vals = [1, 2, 100]
    assert winsorize(vals) == [1, 2, 100]  # < 10 -> returned as-is


def test_minmax_unit_range():
    assert minmax([2, 4, 6]) == [0.0, 0.5, 1.0]


def test_composite_weights():
    assert abs(composite(1.0, 0.0, 0.0) - 0.6) < 1e-9
    assert abs(composite(0.0, 1.0, 0.0) - 0.3) < 1e-9
    assert abs(composite(0.0, 0.0, 1.0) - 0.1) < 1e-9


def test_complexity1_formulaic_scores_zero():
    # complexity-1 work contributes nothing, even in a max-reach area (cw(1)=0)
    formulaic = [{"complexity": 1, "reach": math.log1p(44), "critical_boost": 1.0,
                  "area": "frontend/src"} for _ in range(100)]
    assert engineer_substance(formulaic) == 0.0


def test_gilbert_guard_deep_beats_prolific_formulaic():
    # THE correctness test: 30 non-trivial formulaic PRs (complexity 2, high-reach area, capped at 30)
    # must NOT out-score 6 genuinely deep (complexity 5, critical) PRs.
    prolific = [{"complexity": 2, "reach": math.log1p(44), "critical_boost": 1.0,
                 "area": "frontend/src"} for _ in range(30)]
    deep = [{"complexity": 5, "reach": math.log1p(10), "critical_boost": 1.5,
             "area": "posthog/hogql"} for _ in range(6)]
    assert engineer_substance(deep) > engineer_substance(prolific)


def test_per_pr_substance_uses_convex_weight():
    # a complexity-5 PR is worth far more than several complexity-2 PRs at equal reach
    s5 = per_pr_substance(5, 2.0, 1.0)
    s2 = per_pr_substance(2, 2.0, 1.0)
    assert s5 == 10 * 2.0 and s2 == 1 * 2.0
