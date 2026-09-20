"""Independent numeric oracles and regressions for prediction semantics."""
import copy

import numpy as np
import pytest
import torch

from experiment_planner.application.analysis import analyze
from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.engine.models import BayesianLinear, Encoder, fit_models
from experiment_planner.engine.objectives import Objectives, prediction_summary


class FixedSamples:
    """Only isolate posterior summarization; real fitting is checked separately."""

    def __init__(self, draws):
        self.draws = torch.tensor(draws, dtype=torch.double).unsqueeze(1)

    def posterior(self, _):
        return self

    def rsample(self, shape):
        assert shape == torch.Size([len(self.draws)])
        return self.draws


def test_linear_posterior_matches_independent_closed_form():
    x = np.array([[0.0], [0.25], [0.6], [1.0]])
    y = np.array([1.2, 1.8, 2.7, 4.2])
    variance = np.array([0.04, 0.09, 0.16, 0.04])
    prior_mean = np.array([0.5, 1.5])
    precision = np.diag([0.3, 0.7])
    phi = np.column_stack([np.ones(4), x])
    weight = np.diag(1 / variance)
    covariance = np.linalg.solve(precision + phi.T @ weight @ phi, np.eye(2))
    coefficients = covariance @ (precision @ prior_mean + phi.T @ weight @ y)
    query = np.array([[0.1], [0.75], [1.5]])
    design = np.column_stack([np.ones(3), query])
    model = BayesianLinear(*[torch.tensor(v, dtype=torch.double) for v in
                             (x, y[:, None], variance[:, None], prior_mean, precision)])
    posterior = model.posterior(torch.tensor(query, dtype=torch.double))
    np.testing.assert_allclose(posterior.mean.squeeze(-1).numpy(), design @ coefficients, atol=1e-10)
    np.testing.assert_allclose(posterior.distribution.covariance_matrix.numpy(),
                               design @ covariance @ design.T, atol=2e-9)


@pytest.mark.parametrize("mode", ["require_configuration", "remove", "stabilized", "valid_region"])
def test_original_ratio_never_replaced_by_clipped_ratio(template, conditions, mode):
    template = template.revised(ratio_policy={**template.data["ratio_policy"],
                                              "mode": mode, "epsilon_nm": 1.0})
    draws = [[-4.0, 0.1], [2.0, -0.2], [6.0, 2.0], [-8.0, -4.0]]
    summary = prediction_summary(FixedSamples(draws), Encoder(template),
                                 ["sio2_loss_nm", "sin_loss_nm"], template,
                                 [conditions], samples=4)[0]
    expected_raw = np.quantile([40.0, 10.0, 3.0, 2.0], [0.025, 0.5, 0.975])
    for name in ("selectivity_abs", "raw_selectivity_abs"):
        assert summary[name]["mean"] is None
        np.testing.assert_allclose(summary[name]["quantiles"], expected_raw)
    # E|A| != |E A|, using these same posterior draws.
    assert summary["sio2_loss_nm"]["mean"] == -1.0
    assert summary["objective_predictions"][0]["mean"] == 5.0
    assert summary["objective_predictions"][1]["mean"] == pytest.approx(1.575)
    if mode == "valid_region":
        assert summary["feasibility_probability"] == 0.5
        np.testing.assert_allclose(summary["objective_predictions"][2]["quantiles"], expected_raw)
        scores = Objectives(template, ["sio2_loss_nm", "sin_loss_nm"]).transformed(
            torch.tensor(draws, dtype=torch.double).unsqueeze(1))
        assert torch.isfinite(scores).all()  # acquisition still needs bounded off-region scores
    if mode == "stabilized":
        assert summary["selectivity_stable"]["mean"] == 2.75
        assert summary["objective_predictions"][2]["mean"] == 2.75


def test_prediction_formula_converts_nm_and_um_in_both_directions():
    template = Template({
        "schema_version": 2, "template_version": 1, "name": "合成单位测试",
        "parameters": [{"name": "x", "unit": "1", "bounds": [0, 1]}],
        "measurements": [{"name": "a", "unit": "nm", "is_response": True},
                         {"name": "b", "unit": "um", "is_response": True}],
        "derived_metrics": [
            {"name": "delta", "unit": "nm", "expression": "a - b"},
            {"name": "in_um", "unit": "um", "expression": "delta"},
            {"name": "again_nm", "unit": "nm", "expression": "in_um"}],
        "objectives": [{"metric": "delta", "direction": "maximize"}],
        "optimization": {"mode": "single"}, "ratio_policy": {"mode": "remove"}})
    summary = prediction_summary(FixedSamples([[1000, 0.5]] * 4), Encoder(template),
                                 ["a", "b"], template, [{"x": 0.5}], samples=4)[0]
    for name, expected in (("delta", 500), ("in_um", 0.5), ("again_nm", 500)):
        assert template.graph.evaluate({"a": 1000, "b": 0.5})[name].value == expected
        assert summary[name]["mean"] == pytest.approx(expected)


def test_model_uses_actual_conditions_and_separate_valid_response_rows(service, conditions, measurements):
    first = {**conditions, "cl2_sccm": 10.0}
    second = {**conditions, "cl2_sccm": 80.0}
    service.add_record(first, measurements, suggested=second)
    service.add_record(second, measurements)
    partial = {**conditions, "cl2_sccm": 40.0}
    service.add_record(partial, {k: v for k, v in measurements.items() if k.startswith("sio2")},
                       status="partial")
    for state in ("pending", "running", "failed", "cancelled"):
        service.add_record(conditions, {**measurements, "sio2_remaining_nm": -10000.0}, status=state)
    records = service.project.experiments()
    model, encoder, names, datasets, _ = fit_models(service.project.template, records, "bayesian_linear_v1")
    assert datasets["sio2_loss_nm"]["conditions"] == [first, second, partial]
    assert datasets["sin_loss_nm"]["conditions"] == [first, second]
    assert set(encoder.indices) == {p["name"] for p in service.project.template.parameters}
    clean = [r for r in records if r["status"] in ("completed", "partial")]
    clean_model, *_ = fit_models(service.project.template, clean, "bayesian_linear_v1")
    torch.testing.assert_close(model.posterior(encoder.encode([conditions])).mean,
                               clean_model.posterior(encoder.encode([conditions])).mean)


@pytest.mark.parametrize("preset", ["gp_rbf_v1", "gp_matern25_v1", "bayesian_linear_v1"])
def test_noise_variance_and_prediction_guards(service, conditions, measurements, preset):
    p = service.project
    cells = {name: {"value": value, "uncertainty": {"kind": "std", "amount": 0.2}}
             for name, value in measurements.items()}
    with pytest.raises(CapabilityError, match="不足两条"):
        analyze(p.snapshot(), {"conditions": [conditions], "model": preset})
    service.add_record(conditions, cells)
    second = {**conditions, "cl2_sccm": 20.0}
    service.add_record(second, cells)
    for record in p.experiments():
        assert record["derived"]["sio2_loss_nm"]["uncertainty"]["standard"] ** 2 == pytest.approx(0.08)
    snapshot = p.snapshot()
    with pytest.raises(ValidationError):
        analyze(snapshot, {"conditions": [{**conditions, "cl2_sccm": 101}], "model": preset})
    mixed = copy.deepcopy(snapshot)
    mixed["experiments"][0]["derived"]["sio2_loss_nm"]["uncertainty"] = None
    with pytest.raises(CapabilityError, match="混合已知/未知"):
        analyze(mixed, {"conditions": [conditions], "model": preset})


def test_fit_linear_uses_squared_propagated_uncertainty(service, conditions):
    p = service.project
    # Only one active input: expected posterior can be solved in native units.
    parameters = copy.deepcopy(p.template.parameters)
    for field in parameters:
        field["use_as_model_input"] = field["name"] == "cl2_sccm"
    service.update_template(p.template.revised(parameters=parameters))
    ys = [2.0, 3.2, 5.1, 8.0]
    for x, y in zip([0.0, 25.0, 60.0, 100.0], ys):
        observations = {"sio2_initial_nm": 100.0, "sio2_remaining_nm": 100.0-y,
                        "sin_initial_nm": 100.0, "sin_remaining_nm": 99.0}
        service.add_record({**conditions, "cl2_sccm": x},
                           {k: {"value": v, "uncertainty": {"kind": "std", "amount": 0.2}}
                            for k, v in observations.items()})
    model, encoder, *_ = fit_models(p.template, p.experiments(), "bayesian_linear_v1")
    phi = np.column_stack([np.ones(4), [0.0, 0.25, 0.6, 1.0]])
    covariance = np.linalg.inv(np.diag([1e-6, 0.01]) + phi.T @ phi / 0.08)
    coefficients = covariance @ phi.T @ np.array(ys) / 0.08
    query = np.array([1.0, 0.4])
    posterior = model.models[0].posterior(encoder.encode([{**conditions, "cl2_sccm": 40.0}]))
    assert posterior.mean.item() == pytest.approx(query @ coefficients, abs=1e-8)
    assert posterior.variance.item() == pytest.approx(query @ covariance @ query, abs=2e-9)
