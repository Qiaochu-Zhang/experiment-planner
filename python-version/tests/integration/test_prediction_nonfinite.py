"""Regressions for nonfinite formula samples reaching prediction displays."""
import copy
import json

import numpy as np
import pytest
import torch

from experiment_planner.domain.errors import ValidationError
from experiment_planner.engine.models import Encoder
from experiment_planner.engine.objectives import prediction_summary
from experiment_planner.io.exchange import export_analysis
from experiment_planner.plots.trends import plot_slice
from experiment_planner.ui.messages import analysis_text, batch_text


class FixedSamples:
    def __init__(self, values):
        self.values = torch.tensor(values, dtype=torch.double)

    def posterior(self, X):
        self.count = len(X)
        return self

    def rsample(self, shape):
        assert shape[0] == len(self.values)
        return self.values.unsqueeze(1).expand(-1, self.count, -1)


def configured(template, mode="valid_region", digits=2):
    metrics = copy.deepcopy(template.metrics)
    for metric in metrics:
        metric["display_digits"] = digits
    return template.revised(derived_metrics=metrics, ratio_policy={
        **template.data["ratio_policy"], "mode": mode, "epsilon_nm": 1.0})


def summarize(template, conditions, draws):
    return prediction_summary(FixedSamples(draws), Encoder(template),
                              ["sio2_loss_nm", "sin_loss_nm"], template,
                              [conditions], samples=len(draws))[0]


@pytest.mark.parametrize("digits", [None, 2])
@pytest.mark.parametrize("fixture", ["template", "legacy_template"])
@pytest.mark.parametrize("mode", ["valid_region", "stabilized", "remove", "require_configuration"])
def test_zero_denominator_retains_finite_statistics_and_reports_omissions(request, conditions, mode, fixture, digits):
    template = configured(request.getfixturevalue(fixture), mode, digits)
    summary = summarize(template, conditions, [[2., 0.], [4., 2.], [9., 3.], [16., 4.]])
    original = template.data["ratio_policy"]["original_metric"]
    raw = summary[original]
    assert raw["mean"] is None
    np.testing.assert_allclose(raw["quantiles"], np.quantile([2., 3., 4.], [.025, .5, .975]))
    assert (raw["finite_sample_count"], raw["nonfinite_sample_count"]) == (3, 1)
    assert raw["summary_status"] == "partial"
    assert raw["nonfinite_counts"] == {"nan": 0, "positive_infinity": 1, "negative_infinity": 0}
    if mode in ("valid_region", "require_configuration"):
        objective = summary["objective_predictions"][-1]
        assert objective["mean"] is None
        assert objective["quantiles"] == raw["quantiles"]
        assert objective["finite_sample_count"] == 3
    if mode == "stabilized":
        assert summary["objective_predictions"][-1]["summary_status"] == "ok"
        np.testing.assert_allclose(summary["selectivity_stable"]["quantiles"],
                                   np.quantile([2., 2., 3., 4.], [.025, .5, .975]))
    if mode == "valid_region":
        assert summary["feasibility_probability"] == .75
    json.dumps(summary, allow_nan=False)
    text = analysis_text({"predictions": [summary]}, template)
    assert "3/4" in text and "有限样本" in text
    assert "nan" not in text.lower()  # no invalid numeric interval is presented
    batch = {"stage": "model_driven", "request": {"n": 1}, "candidates": [
        {"arrangement": "new", "conditions": conditions, "prediction": summary}]}
    batch_text(batch, template)


def test_all_undefined_ratio_keeps_other_responses_and_exports_notice(template, conditions, tmp_path):
    template = configured(template)
    summary = summarize(template, conditions, [[0., 0.], [2., 0.], [-2., 0.], [1., 0.]])
    ratio = summary["selectivity"]
    assert ratio["mean"] is None and ratio["quantiles"] is None
    assert ratio["summary_status"] == "unavailable"
    assert ratio["nonfinite_counts"] == {"nan": 1, "positive_infinity": 2, "negative_infinity": 1}
    assert summary["objective_predictions"][-1]["quantiles"] is None
    assert summary["sio2_loss_nm"]["quantiles"] is not None
    assert summary["feasibility_probability"] == 0
    report = {"revision": 1, "template_version": 1, "model": "gp_rbf_v1",
              "conditions": [conditions], "predictions": [summary]}
    text = analysis_text(report, template)
    assert "0/4" in text and "不可用" in text and "SiO2" in text
    json.dumps(report, allow_nan=False)
    path = tmp_path / "prediction.csv"
    export_analysis(report, template, path)
    assert "0/4" in path.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_invalid_base_posterior_fails_with_response_and_condition(template, conditions, bad):
    with pytest.raises(ValidationError, match="sin_loss_nm") as error:
        summarize(configured(template), conditions, [[1., 2.], [2., bad]])
    assert "条件 1" in str(error.value) and "非有限" in str(error.value)
    assert any("cl2_sccm" in note for note in error.value.__notes__)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("digits", [None, 2])
def test_existing_invalid_report_is_named_without_crashing(template, bad, digits):
    template = configured(template, digits=digits)
    item = {"quantiles": [1., 2., bad]}
    summary = {"selectivity": item, "objective_predictions": [
        {**item, "definition": {"metric": "selectivity"}}]}
    text = analysis_text({"predictions": [summary]}, template)
    assert "刻蚀量比值" in text and "非有限" in text and "不可用" in text
    assert "[1.00, " not in text and "[1, " not in text


def test_generic_formula_failure_is_reported_with_its_expression(template, conditions):
    metric = {"name": "undefined", "label": "零分母示例", "unit": "1",
              "expression": "sio2_loss_nm / (sin_loss_nm - sin_loss_nm)", "display_digits": 2}
    template = template.revised(derived_metrics=[*template.metrics, metric],
                                objectives=[{"metric": "undefined", "direction": "maximize"}],
                                optimization={"mode": "single"}, ratio_policy={"mode": "remove"})
    summary = summarize(template, conditions, [[1., 2.], [2., 3.]])
    item = summary["undefined"]
    assert item["quantiles"] is None and item["mean"] is None
    assert item["expression"] == metric["expression"]
    assert summary["objective_predictions"][0]["quantiles"] is None
    assert "零分母示例" in analysis_text({"predictions": [summary]}, template)
    json.dumps(summary, allow_nan=False)


@pytest.mark.parametrize("values", [[-1e308, 1e308], [1e308, 1e308]])
def test_statistics_overflow_is_reported_without_nonfinite_json(template, conditions, values):
    summary = summarize(configured(template), conditions, [[v, 1.] for v in values])
    item = summary["sio2_loss_nm"]
    assert item["finite_sample_count"] == 2 and item["nonfinite_sample_count"] == 0
    assert "溢出" in item["summary_notice"]
    if values[0] < 0:
        assert item["quantiles"] is None
    else:
        assert item["mean"] is None
    json.dumps(summary, allow_nan=False)


def test_plot_reports_missing_interval_with_metric_and_conditions(template, conditions, tmp_path):
    template = configured(template)
    with pytest.raises(ValidationError, match="selectivity") as error:
        plot_slice(FixedSamples([[2., 0.]] * 512), Encoder(template),
                   ["sio2_loss_nm", "sin_loss_nm"], template, conditions,
                   ["cl2_sccm"], "selectivity", tmp_path / "invalid.png", 1, points=2)
    assert "条件 1" in str(error.value)
    assert not (tmp_path / "invalid.png").exists()


def test_partial_plot_marks_finite_sample_intervals(template, conditions, tmp_path):
    template = configured(template)
    result = plot_slice(FixedSamples([[2., 0.], [4., 2.]] * 256), Encoder(template),
                        ["sio2_loss_nm", "sin_loss_nm"], template, conditions,
                        ["cl2_sccm"], "selectivity", tmp_path / "partial.png", 1, points=2)
    assert "有限样本" in result["notices"][0]
    assert (tmp_path / "partial.png").is_file()
    json.dumps(result, allow_nan=False)
