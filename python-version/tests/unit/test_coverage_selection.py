from types import SimpleNamespace

import pytest

from experiment_planner.engine.coverage import BatchCoverage, different, retain_coverage


def tracker(*fields):
    return BatchCoverage(SimpleNamespace(parameters=list(fields)), [p["name"] for p in fields])


@pytest.mark.parametrize("first", [0, 5])
def test_coverage_overrides_repeated_favorite_then_returns_to_scores(first):
    coverage = tracker(*[{"name": name, "bounds": [0, 10]} for name in "abc"])
    coverage.add({"a": first, "b": 0, "c": 0})
    pool = [{"a": 9, "b": 0, "c": 0}, {"a": 0, "b": 1, "c": 0}, {"a": 0, "b": 1, "c": 2}]
    assert coverage.choose(pool, [100, 90, -100]) == 2
    coverage.add(pool[2])
    assert coverage.choose(pool, [100, 90, -100]) == 0
    coverage.add(pool[0])
    assert coverage.report()["complete"]
    assert coverage.choose(pool, [-5, 10, 0]) == 1


def test_first_row_and_equal_coverage_follow_scores():
    coverage = tracker({"name": "a", "bounds": [0, 10]})
    pool = [{"a": 1}, {"a": 2}, {"a": 3}]
    assert coverage.choose(pool, [1, 2, 3]) == 2
    coverage.add(pool[2])
    assert coverage.choose(pool, [2, 1, 100]) == 0


def test_extremes_detect_span_even_when_each_is_close_to_first():
    coverage = tracker({"name": "x", "bounds": [0, 1]})
    coverage.add({"x": .5})
    coverage.add({"x": .5 + 7e-11})
    assert not coverage.report()["complete"]
    assert coverage.gain({"x": .5 - 7e-11}) == 1
    coverage.add({"x": .5 - 7e-11})
    assert coverage.report()["complete"]


def test_grids_categories_booleans_and_text_use_real_values():
    coverage = tracker({"name": "x", "bounds": [0, 1], "execution_rounding": {"mode": "digits", "digits": 12}},
                       {"name": "gas", "value_type": "category"}, {"name": "flag", "value_type": "bool"},
                       {"name": "note", "value_type": "text"})
    coverage.add({"x": .5, "gas": "A", "flag": False, "note": "原条件"})
    coverage.add({"x": .500000000001, "gas": "B", "flag": True, "note": "新条件"})
    assert coverage.report()["complete"]
    assert not different({"bounds": [0, 1]}, .5, .500000000001)


def test_pool_trimming_keeps_rare_variables_within_budget():
    template = SimpleNamespace(parameters=[{"name": name, "bounds": [0, 200]} for name in "abc"])
    original = [{"a": i, "b": 0, "c": 0} for i in range(100)] + [{"a": 0, "b": 1, "c": 1}]
    kept = retain_coverage(template, list("abc"), original.copy(), 3)
    assert len(kept) == 3
    assert all(len({c[name] for c in kept}) > 1 for name in "abc")
    assert all(c in original for c in kept)
