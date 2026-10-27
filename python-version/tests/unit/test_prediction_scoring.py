from copy import deepcopy
import math

import pytest

from experiment_planner.application.prediction_scoring import evaluate_record, make_prediction_snapshot, summarize_evaluations
from experiment_planner.domain.template import Template


@pytest.fixture
def score_template():
    return Template({"schema_version": 2, "template_version": 1, "parameters": [{"name": "x", "bounds": [0, 1]}],
        "measurements": [{"name": "y", "is_response": True}, {"name": "flag", "value_type": "bool"}],
        "derived_metrics": [{"name": "double_y", "expression": "y * 2"}],
        "objectives": [{"metric": "y", "direction": "maximize"}], "optimization": {"mode": "single"},
        "ratio_policy": {"mode": "remove"}})


def example(template, value=10., mean=10., lower=9., upper=11., **item_kwargs):
    record = {"id": 1, "actual": {"x": .5}, "status": "completed", "observations": {"y": {"value": value}}, "derived": {}}
    prediction = {"y": {"mean": mean, "quantiles": [lower, (lower+upper)/2, upper], **item_kwargs}}
    snapshot = make_prediction_snapshot(template.data, record["actual"], prediction, model="test_model")
    return record, snapshot


@pytest.mark.parametrize("mean,lower,upper,error,score", [(10.,9.,11.,0.,2.), (10.,0.,20.,0.,20.), (9.7,9.6,9.8,.3,8.2),
    (8.,8.,10.,2.,2.), (10.,10.,10.,0.,0.), (12.,12.,14.,2.,82.)])
def test_standard_measurement_scores_and_inclusive_endpoints(score_template, mean, lower, upper, error, score):
    record, snapshot = example(score_template, mean=mean, lower=lower, upper=upper)
    before = deepcopy((record, snapshot))
    [row] = evaluate_record(score_template, record, snapshot)["rows"]
    assert row["absolute_error"] == pytest.approx(error)
    assert row["squared_error"] == pytest.approx(error**2)
    assert row["interval_score95"] == pytest.approx(score)
    assert row["covered95"] == (lower <= 10 <= upper)
    assert row["prediction_center"] == mean
    assert (record, snapshot) == before


def test_missing_mean_uses_median_and_zero_is_real_measurement(score_template):
    record, snapshot = example(score_template, value=0., mean=None, lower=-1., upper=1.)
    [row] = evaluate_record(score_template, record, snapshot)["rows"]
    assert row["prediction_center"] == 0. and row["absolute_error"] == 0.
    assert row["center_kind"] == "中位数" and row["interval_score95"] == 2.


@pytest.mark.parametrize("quantiles", [None, [1., 2.], [3., 2., 1.], [1., 2., float("nan")]])
def test_invalid_interval_keeps_point_score_but_not_coverage(score_template, quantiles):
    record, snapshot = example(score_template, quantiles=quantiles)
    result = evaluate_record(score_template, record, snapshot)
    [row] = result["rows"]
    assert row["absolute_error"] == 0. and row["interval_score95"] is None and row["covered95"] is None
    [summary] = summarize_evaluations([result])
    assert summary["point_count"] == 1 and summary["interval_count"] == 0 and summary["coverage95"] is None


@pytest.mark.parametrize("case", ["missing", "partial_samples", "failed", "cancelled", "invalid_actual", "changed_conditions", "missing_center"])
def test_unscorable_results_never_become_zero_scores(score_template, case):
    record, snapshot = example(score_template)
    if case == "missing": record["observations"]["y"]["value"] = None
    elif case == "partial_samples": snapshot["prediction"]["y"]["nonfinite_sample_count"] = 1
    elif case in ("failed", "cancelled"): record["status"] = case
    elif case == "invalid_actual": record["observations"]["y"]["status"] = "unstable"
    elif case == "changed_conditions": record["actual"]["x"] = .6
    else: snapshot["prediction"]["y"] = {"mean": None, "quantiles": None}
    result = evaluate_record(score_template, record, snapshot)
    [row] = result["rows"]
    assert row["absolute_error"] is None and row["interval_score95"] is None
    assert summarize_evaluations([result]) == []


def test_formula_changes_exclude_only_affected_derived_metrics(score_template):
    record, snapshot = example(score_template)
    snapshot["prediction"]["double_y"] = {"mean": 20., "quantiles": [18.,20.,22.]}
    record["derived"]["double_y"] = {"value": 30., "status": "valid"}
    changed = score_template.revised(derived_metrics=[{"name": "double_y", "expression": "y * 3"}])
    rows = {r["metric"]: r for r in evaluate_record(changed, record, snapshot)["rows"]}
    assert rows["y"]["status"] == "scored"
    assert rows["double_y"]["status"] == "unavailable" and "公式" in rows["double_y"]["reason"]


def test_boolean_probabilities_use_brier_without_probability_interval_coverage(score_template):
    record, snapshot = example(score_template)
    record["observations"] = {"flag": {"value": True}}
    snapshot["prediction"] = {"flag": {"mean": .8, "quantiles": [.6,.8,.95]}}
    result = evaluate_record(score_template, record, snapshot)
    [row] = result["rows"]
    assert row["brier_score"] == pytest.approx(.04) and row["interval_score95"] is None
    [summary] = summarize_evaluations([result])
    assert summary["brier_count"] == 1 and summary["mean_brier_score"] == pytest.approx(.04)
    assert summary["point_count"] == summary["interval_count"] == 0


def test_summaries_keep_models_separate_and_do_not_average_missing_as_zero(score_template):
    evaluations = []
    for y, model in ((9.,"A"),(13.,"A"),(None,"A"),(10.,"B")):
        record, snapshot = example(score_template, value=y)
        snapshot["model"] = model
        evaluations.append(evaluate_record(score_template, record, snapshot))
    results = {s["model"]: s for s in summarize_evaluations(evaluations)}
    assert results["A"]["mae"] == 2. and results["A"]["rmse"] == pytest.approx(math.sqrt(5))
    assert results["A"]["coverage95"] == .5 and results["A"]["point_count"] == 2
    assert results["A"]["mean_interval_score95"] == 42.
    assert results["B"]["mae"] == 0.


def test_large_scores_and_rmse_do_not_emit_nonfinite_values(score_template):
    record, snapshot = example(score_template, value=1e200, mean=0., lower=-1., upper=1.)
    result = evaluate_record(score_template, record, snapshot)
    [row] = result["rows"]
    assert row["absolute_error"] == 1e200 and row["squared_error"] is None
    [summary] = summarize_evaluations([result, result])
    assert summary["rmse"] == pytest.approx(1e200)
