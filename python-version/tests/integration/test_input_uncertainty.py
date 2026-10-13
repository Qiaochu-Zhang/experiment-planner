"""Input noise: analytic oracles, persistence, and actual BO adapters."""
import copy
import csv
import json

import numpy as np
import pytest
import torch
from botorch.models.model import Model
from botorch.posteriors.gpytorch import GPyTorchPosterior
from botorch.sampling.get_sampler import get_sampler
from gpytorch.distributions import MultivariateNormal

from experiment_planner.application.analysis import analyze
from experiment_planner.application.template_editing import rename_field
from experiment_planner.domain.errors import ValidationError, CapabilityError
from experiment_planner.domain.template import Template
from experiment_planner.engine.input_uncertainty import InputDistribution, ExpectedInputModel
from experiment_planner.engine.models import Encoder, fit_models
from experiment_planner.engine.objectives import Objectives, prediction_summary
from experiment_planner.engine.planner import generate
from experiment_planner.engine.space import BatchRequest
from experiment_planner.io.exchange import export_analysis
from experiment_planner.ui.messages import analysis_text


def input_template(kind="bounds", amount=.2, enabled=True, mode="single", samples=32):
    data = {"schema_version": 2, "template_version": 1, "name": "合成输入波动",
        "parameters": [{"name": "x", "label": "流量", "unit": "1", "bounds": [0., 1.],
                        "input_uncertainty": {"enabled": True, "kind": kind, "amount": amount, "note": "合成假设"}},
                       {"name": "z", "unit": "1", "bounds": [0., 1.]}],
        "measurements": [{"name": "y", "is_response": True, "unit": "1"}],
        "derived_metrics": [], "objectives": [{"metric": "y", "direction": "maximize"}],
        "optimization": {"mode": "single"}, "ratio_policy": {"mode": "remove"},
        "input_uncertainty": {"enabled": enabled, "samples": samples}}
    if mode != "single":
        data["measurements"].append({"name": "b", "is_response": True, "unit": "1"})
        data["objectives"].append({"metric": "b", "direction": "minimize", "transform": "absolute_distance", "target": 0.})
        data["optimization"].update(mode=mode, weights=[1., 1.], scales=[1., 1.])
    return Template(data)


def snapshot(template):
    records = [{"id": i, "status": "completed", "actual": {"x": x, "z": .3}, "derived": {},
                "observations": {name: {"value": 1+2*x if name == "y" else 1-x,
                    "uncertainty": {"kind": "std", "amount": .05}} for name in [f["name"] for f in template.responses]}}
               for i, x in enumerate([.1, .4, .8], 1)]
    return {"template": template.data, "experiments": records, "revision": 1, "name": "合成输入波动"}


class KnownLinear(Model):
    @property
    def num_outputs(self): return 1
    @property
    def batch_shape(self): return torch.Size()
    def posterior(self, X, **kwargs):
        mean = 2*X[..., 0]+X[..., 1]
        covariance = torch.eye(X.shape[-2], dtype=X.dtype, device=X.device).expand(*X.shape[:-2], -1, -1)*1e-12
        return GPyTorchPosterior(MultivariateNormal(mean, covariance))


@pytest.mark.parametrize("amount", [None, 0, -1, True, float("nan"), float("inf"), 1e-30, 1e30, ".2"])
def test_invalid_active_uncertainty_is_rejected(amount):
    with pytest.raises(ValidationError): input_template(amount=amount)


@pytest.mark.parametrize("field_changes", [
    {"value_type": "int"}, {"use_as_model_input": False},
    {"fixed_value": .5}, {"values": [.1, .5]},
])
def test_unsupported_input_is_not_silently_perturbed(field_changes):
    data = input_template().data
    data["parameters"][0].update(field_changes)
    with pytest.raises(ValidationError, match="连续数值"):
        Template(data)


def test_enabled_requires_selection_and_valid_configuration():
    data = input_template().data
    data["parameters"][0]["input_uncertainty"]["enabled"] = False
    with pytest.raises(ValidationError, match="至少勾选"):
        Template(data)
    for invalid in ({"enabled": "false"}, {"enabled": True, "samples": 17}, {"enabled": True, "samples": True}):
        with pytest.raises(ValidationError): input_template().revised(input_uncertainty=invalid)
    with pytest.raises(ValidationError): input_template(kind="automatic")


def test_off_is_default_and_exactly_preserves_existing_prediction():
    template = input_template(enabled=False)
    original = copy.deepcopy(template.data)
    original.pop("input_uncertainty")
    original["parameters"][0].pop("input_uncertainty")
    original = Template(original)
    conditions = [{"x": .5, "z": .3}]
    expected = prediction_summary(KnownLinear(), Encoder(original), ["y"], original, conditions, seed=12)
    actual = prediction_summary(KnownLinear(), Encoder(template), ["y"], template, conditions, seed=12)
    assert actual == expected
    assert "nominal_prediction" not in actual[0]


@pytest.mark.parametrize("kind", ["std", "bounds"])
def test_selected_inputs_only_reproducible_conditioned_sampling(kind):
    template = input_template(kind=kind, amount=.1)
    encoder = Encoder(template)
    X = encoder.encode([{"x": 0., "z": .3}, {"x": .5, "z": .7}, {"x": 1., "z": .6}])
    distribution = InputDistribution(template, encoder, seed=41)
    draws = distribution.expand(X)
    torch.testing.assert_close(draws, distribution.expand(X))
    torch.testing.assert_close(draws[..., 1], X[:, 1, None].expand(-1, 32), rtol=0, atol=0)
    assert ((draws >= 0) & (draws <= 1)).all()
    assert not ((draws[..., 0] == 0) | (draws[..., 0] == 1)).any()
    assert not torch.equal(draws, InputDistribution(template, encoder, seed=42).expand(X))
    expected_boundary_mean = .1*np.sqrt(2/np.pi) if kind == "std" else .05
    assert draws[0, :, 0].mean().item() == pytest.approx(expected_boundary_mean, abs=.006)
    torch.testing.assert_close(distribution.expand(X.flip(0)).flip(0), draws)


def test_linear_constraint_conditions_the_joint_distribution():
    template = input_template().revised(input_constraints=[{"coefficients": {"x": 1, "z": 1}, "op": "<=", "rhs": .6}])
    encoder = Encoder(template)
    draws = InputDistribution(template, encoder).expand(encoder.encode([{"x": .3, "z": .3}]))
    assert (draws.sum(-1) <= .6 + 1e-10).all()
    assert draws[..., 0].std() > .02
    impossible = template.revised(input_constraints=[
        {"coefficients": {"x": 1}, "op": "<=", "rhs": .3},
        {"coefficients": {"x": 1}, "op": ">=", "rhs": .3}])
    with pytest.raises(CapabilityError, match="不足"):
        InputDistribution(impossible, Encoder(impossible)).expand(encoder.encode([{"x": .3, "z": .3}]))


def test_input_variability_matches_linear_uniform_oracle_and_keeps_nominal():
    template = input_template()
    conditions = [{"x": .5, "z": .3}]
    summary = prediction_summary(KnownLinear(), Encoder(template), ["y"], template, conditions, samples=512, seed=19)[0]
    # 2 * Uniform[-.2,.2] + 1.3 has quantiles [0.92,1.3,1.68].
    np.testing.assert_allclose(summary["y"]["quantiles"], [.92, 1.3, 1.68], atol=.025)
    assert summary["y"]["mean"] == pytest.approx(1.3, abs=.004)
    assert summary["nominal_prediction"]["y"]["quantiles"][2] - summary["nominal_prediction"]["y"]["quantiles"][0] < 1e-5
    assert summary["y"]["interval_kind"] == "latent_response_with_input_uncertainty"
    assert summary["input_uncertainty"]["parameters"][0]["name"] == "x"
    assert summary["input_uncertainty"]["posterior_function_samples"] == 16
    assert summary["input_uncertainty"]["mixture_samples"] == 512
    text = analysis_text({"predictions": [summary]}, template)
    assert "输入确定时" in text and "考虑输入执行波动后" in text
    json.dumps(summary, allow_nan=False)


def test_objective_transform_precedes_input_averaging_and_sampling_adapter():
    template = input_template(samples=8).revised(objectives=[
        {"metric": "y", "direction": "minimize", "transform": "absolute_distance", "target": 0.}])
    model = ExpectedInputModel(KnownLinear(), InputDistribution(template, Encoder(template)), Objectives(template, ["y"]))
    draws = torch.tensor([[[-1.], [1.]]*8], dtype=torch.double)
    assert model.transform(draws).tolist() == [[[-1.], [-1.]]]
    posterior = model.posterior(torch.tensor([[[.4, .3], [.6, .3]]], dtype=torch.double))
    assert posterior._extended_shape(torch.Size([5])) == torch.Size([5, 1, 2, 1])
    sampled = get_sampler(posterior, torch.Size([5]), seed=1)(posterior)
    assert sampled.shape == (5, 1, 2, 1) and torch.isfinite(sampled).all()


@pytest.mark.parametrize("preset", ["gp_rbf_v1", "gp_matern25_v1", "bayesian_linear_v1"])
@pytest.mark.parametrize("mode", ["single", "weighted", "pareto"])
def test_real_prediction_and_recommendation_with_input_noise(preset, mode):
    template = input_template(kind="std", amount=.05, mode=mode, samples=8)
    template = template.revised(outcome_constraints=[{"metric": "y", "op": ">=", "bound": 0.}])
    data = snapshot(template)
    original = copy.deepcopy(data)
    model, encoder, names, datasets, _ = fit_models(template, data["experiments"], preset, seed=3)
    assert datasets["y"]["count"] == 3
    report = prediction_summary(model, encoder, names, template, [{"x": .5, "z": .3}], seed=3)
    assert report[0]["y"]["quantiles"] and report[0]["nominal_prediction"]["y"]["quantiles"]
    request = BatchRequest(n=2, model=preset, pool_size=4, seed=3, exploration_count=1, exploration_strength=.5)
    batch = generate(data, request)
    assert batch["stage"] == "model_driven" and len(batch["candidates"]) == 2
    assert batch["exploration"]["input_uncertainty"]["enabled"]
    assert {c["arrangement"] for c in batch["candidates"]} == {"new", "exploration"}
    assert all(c["prediction"]["input_uncertainty"]["enabled"] for c in batch["candidates"])
    json.dumps(batch, allow_nan=False)
    assert data == original


def test_template_roundtrip_rename_and_existing_records_are_preserved(service, conditions, measurements, tmp_path):
    service.add_record(conditions, measurements)
    old = service.project.experiment(1)
    fields = copy.deepcopy(service.project.template.parameters)
    fields[0]["input_uncertainty"] = {"enabled": True, "kind": "std", "amount": .5, "note": "合成假设"}
    template = service.project.template.revised(parameters=fields, input_uncertainty={"enabled": True, "samples": 16})
    service.update_template(template)
    current = service.project.experiment(1)
    assert current["actual"] == old["actual"] and current["observations"] == old["observations"]
    for extension in ("json", "xlsx"):
        path = tmp_path / ("uncertainty." + extension)
        template.write(path)
        loaded = Template.read(path)
        assert loaded.parameters[0]["input_uncertainty"] == fields[0]["input_uncertainty"]
        assert loaded.data["input_uncertainty"] == template.data["input_uncertainty"]
    renamed = Template(rename_field(template.data, fields[0]["name"], "renamed"))
    assert renamed.parameters[0]["input_uncertainty"]["amount"] == .5
    service.undo()
    assert not service.project.template.data.get("input_uncertainty", {}).get("enabled", False)
    service.redo()
    assert service.project.template.data["input_uncertainty"]["enabled"]


def test_analysis_plot_export_carries_both_interpretations(tmp_path):
    template = input_template(samples=8)
    data = snapshot(template)
    report = analyze(data, {"conditions": [{"x": .5, "z": .3}], "model": "bayesian_linear_v1",
        "plot_path": str(tmp_path/"trend.png"), "variables": ["x"], "metric": "y", "points": 3})
    assert report["input_uncertainty"]["enabled"]
    assert report["plot"]["interval_kind"] == "latent_response_with_input_uncertainty"
    assert (tmp_path/"trend.png").exists()
    path = tmp_path/"export.csv"
    export_analysis(report, template, path)
    with path.open(encoding="utf-8-sig") as source: rows = list(csv.DictReader(source))
    assert len(rows) == 8
    assert {r["计算口径"] for r in rows} == {"输入确定", "含输入执行波动"}
    assert all(json.loads(r["输入不确定度配置"])["enabled"] for r in rows)


def test_input_noise_changes_recommendation_scoring_and_initialization_is_explicit():
    template = input_template(samples=8)
    data = snapshot(template)
    request = BatchRequest(n=1, model="bayesian_linear_v1", pool_size=4, seed=5)
    on = generate(data, request)
    again = generate(data, request)
    off = generate({**data, "template": template.revised(input_uncertainty={"enabled": False}).data}, request)
    assert on["candidates"] == again["candidates"]
    assert on["candidates"][0]["log_acquisition"] != off["candidates"][0]["log_acquisition"]
    empty = generate({**data, "experiments": []}, request)
    assert empty["stage"] == "initialization" and empty["candidates"][0]["prediction"] is None
    assert any("尚未" in notice and "稳健" in notice for notice in empty["notices"])


def test_disabled_settings_preserve_default_recommendations():
    template = input_template(enabled=False)
    original = copy.deepcopy(template.data)
    original.pop("input_uncertainty")
    original["parameters"][0].pop("input_uncertainty")
    data = snapshot(template)
    request = BatchRequest(n=2, model="bayesian_linear_v1", pool_size=4, seed=7)
    assert generate(data, request)["candidates"] == generate({**data, "template": original}, request)["candidates"]


def test_unmodeled_constraint_input_is_reported_before_training():
    data = input_template().data
    data["parameters"][1]["use_as_model_input"] = False
    data["input_constraints"] = [{"coefficients": {"x": 1, "z": 1}, "op": "<=", "rhs": 1.}]
    template = Template(data)
    with pytest.raises(CapabilityError, match="全部参与数值模型"):
        fit_models(template, snapshot(template)["experiments"], "gp_rbf_v1")


def test_expected_performance_prefers_broad_peak_over_narrow_nominal_peak():
    class TwoPeaks(KnownLinear):
        def posterior(self, X, **kwargs):
            x = X[..., 0]
            mean = torch.exp(-((x-.25)/.02)**2) + .8*torch.exp(-((x-.75)/.3)**2)
            covariance = torch.eye(X.shape[-2], dtype=X.dtype).expand(*X.shape[:-2], -1, -1)*1e-12
            return GPyTorchPosterior(MultivariateNormal(mean, covariance))
    template = input_template(amount=.15)
    encoder = Encoder(template)
    X = encoder.encode([{"x": .25, "z": .3}, {"x": .75, "z": .3}])
    model = TwoPeaks()
    robust = ExpectedInputModel(model, InputDistribution(template, encoder), Objectives(template, ["y"]))
    assert model.posterior(X).mean.argmax().item() == 0
    # The broad peak has higher average performance under Uniform[-.15,.15].
    assert robust.posterior(X).mean.argmax().item() == 1


def test_mixed_boolean_response_and_derived_metric_under_input_noise():
    data = input_template(samples=8).data
    data["measurements"].append({"name": "passed", "value_type": "bool", "is_response": True})
    data["derived_metrics"] = [{"name": "double_y", "expression": "y * 2", "unit": "1"}]
    data["objectives"] = [{"metric": "double_y", "direction": "maximize"}]
    data["outcome_constraints"] = [{"metric": "passed", "op": ">=", "bound": .4}]
    template = Template(data)
    state = snapshot(template)
    for row in state["experiments"]:
        row["observations"]["passed"] = {"value": row["id"] != 1}
    request = BatchRequest(n=1, model="bayesian_linear_v1", pool_size=4, seed=3)
    result = generate(state, request)
    prediction = result["candidates"][0]["prediction"]
    assert 0 <= prediction["passed"]["mean"] <= 1
    assert prediction["double_y"]["mean"] == pytest.approx(2*prediction["y"]["mean"])
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("operation", ["analyze", "generate"])
def test_spawned_worker_applies_input_uncertainty(tmp_path, operation):
    import time
    from experiment_planner.application.service import PlannerService
    from experiment_planner.storage.project import Project
    from experiment_planner.worker.process import CalculationTask
    template = input_template(samples=8)
    project = Project.create(tmp_path/"input-noise.sqlite", "合成输入波动", template)
    service = PlannerService(project)
    for row in snapshot(template)["experiments"]:
        service.add_record(row["actual"], row["observations"])
    before = project.snapshot()
    request = ({"conditions": [{"x": .5, "z": .3}], "model": "bayesian_linear_v1"} if operation == "analyze"
               else BatchRequest(n=1, pool_size=4, model="bayesian_linear_v1"))
    task = CalculationTask(project, request, operation=operation)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = task.poll()
            if result is not None: break
            time.sleep(.02)
        else: pytest.fail("输入不确定度后台计算未按时返回")
        assert "error" not in result, result
        report = result["result"]
        prediction = report["predictions"][0] if operation == "analyze" else report["candidates"][0]["prediction"]
        assert prediction["input_uncertainty"]["enabled"] and prediction["nominal_prediction"]
        assert project.snapshot() == before
        json.dumps(report, allow_nan=False)
    finally:
        if str(project.path) in CalculationTask.active: task.cancel()
        project.close()
