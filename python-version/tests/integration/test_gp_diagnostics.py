"""Optimizer failures, real recovery, and inclusive tight-domain GP fits."""
import copy
import json
import warnings

import pytest
import torch
from botorch.exceptions.warnings import OptimizationWarning
from botorch.optim.core import OptimizationResult, OptimizationStatus
from linear_operator.utils.errors import NotPSDError

from experiment_planner.domain.errors import ModelTrainingError
from experiment_planner.domain.template import Template
from experiment_planner.engine import gp_fitting
from experiment_planner.engine.models import fit_models
from experiment_planner.ui.messages import exception_diagnostic, user_error


def case(bounds=(10., 20.), known=True):
    template = Template({
        "schema_version": 2, "template_version": 1, "name": "合成拟合诊断",
        "parameters": [{"name": "x", "label": "功率", "unit": "W", "bounds": list(bounds)}],
        "measurements": [{"name": "y", "label": "厚度", "unit": "nm", "is_response": True}],
        "derived_metrics": [], "objectives": [{"metric": "y", "direction": "maximize"}],
        "optimization": {"mode": "single"}, "ratio_policy": {"mode": "remove"},
    })
    xs = [bounds[0] + (bounds[1] - bounds[0]) * i / 4 for i in range(5)]
    records = [{"id": i + 1, "status": "completed", "actual": {"x": x}, "derived": {},
                "observations": {"y": {"value": y, "uncertainty":
                    {"kind": "std", "amount": .05} if known else {}}}}
               for i, (x, y) in enumerate(zip(xs, (1., 1.4, 2., 2.7, 3.2)))]
    return template, records


def test_all_failed_attempts_keep_warnings_debug_causes_response_and_data(monkeypatch):
    template, records = case()
    records[1]["actual"] = records[0]["actual"].copy()
    before = copy.deepcopy(records)
    logger = gp_fitting.logger
    logging_before = logger.level, logger.handlers[:], logger.propagate, logger.disabled

    def fail(*args, **kwargs):
        warnings.warn("controlled original jitter warning", OptimizationWarning)
        raise NotPSDError("controlled matrix decomposition failure")

    monkeypatch.setattr(gp_fitting, "fit_gpytorch_mll_scipy", fail)
    with pytest.raises(ModelTrainingError) as caught:
        fit_models(template, records, "gp_rbf_v1", seed=17)
    text = exception_diagnostic(caught.value)
    assert text.startswith("GP 训练诊断")
    assert text.count("训练上下文（原单位；编码范围另列）") == 1
    assert caught.value.__notes__  # Formatting must not mutate the CLI traceback.
    assert "厚度（y）" in user_error(caught.value)
    for expected in ("controlled original jitter warning", "controlled matrix decomposition failure",
                     "NotPSDError", '"attempt": 3', '"sample_count": 5', '"seed": 17',
                     '"duplicate_group_count": 1', '"allowed_bounds"', '"boundary_count"'):
        assert expected in text
    assert "DEBUG: Fit attempt" in text  # BoTorch catches NotPSDError internally.
    assert (logger.level, logger.handlers, logger.propagate, logger.disabled) == logging_before
    assert records == before


@pytest.mark.parametrize("constant_input", [False, True])
def test_real_recovery_changes_initialization_but_preserves_known_noise(monkeypatch, constant_input):
    template, records = case()
    if constant_input:
        for record in records:
            record["actual"]["x"] = 15.
    before = copy.deepcopy(records)
    original = gp_fitting.fit_gpytorch_mll_scipy
    starting_lengths, noises, options = [], [], []

    def fail_twice_then_fit(mll, **kwargs):
        starting_lengths.append(mll.model.covar_module.base_kernel.lengthscale.detach().clone())
        noises.append(mll.likelihood.noise.detach().clone())
        options.append(kwargs["options"])
        if len(noises) < 3:
            return OptimizationResult(step=1, fval=3., status=OptimizationStatus.FAILURE,
                                      message="ABNORMAL: controlled line search failure")
        return original(mll, **kwargs)

    monkeypatch.setattr(gp_fitting, "fit_gpytorch_mll_scipy", fail_twice_then_fit)
    model, encoder, _, datasets, notices = fit_models(template, records, "gp_rbf_v1")
    assert len(noises) == 3
    assert not torch.equal(starting_lengths[0], starting_lengths[1])
    assert not torch.equal(starting_lengths[1], starting_lengths[2])
    for noise in noises[1:]:
        torch.testing.assert_close(noise, noises[0], rtol=0, atol=0)
    assert [o["maxls"] for o in options] == [20, 50, 100]
    report = datasets["y"]["gp_training"]
    assert report["recovered"]
    assert [a["outcome"] for a in report["attempts"]] == ["failed", "failed", "accepted"]
    assert "ABNORMAL" in report["attempts"][0]["optimizer_result"]["message"]
    assert any("第 3 次 GP 拟合恢复" in n for n in notices)
    assert torch.isfinite(model.posterior(encoder.encode([{"x": 15.}])).mean).all()
    json.dumps(datasets, ensure_ascii=False, allow_nan=False)
    assert records == before


def test_nonfinite_objective_is_never_reported_as_success(monkeypatch):
    template, records = case()
    def invalid_result(*args, **kwargs):
        return OptimizationResult(step=1, fval=float("nan"), status=OptimizationStatus.SUCCESS)
    monkeypatch.setattr(gp_fitting, "fit_gpytorch_mll_scipy", invalid_result)
    with pytest.raises(ModelTrainingError) as caught:
        fit_models(template, records, "gp_rbf_v1")
    assert "优化目标出现 NaN 或 Inf" in exception_diagnostic(caught.value)
    assert '"attempt": 3' in exception_diagnostic(caught.value)


@pytest.mark.parametrize("location", ["input", "response", "variance"])
def test_nonfinite_data_is_identified_before_optimizer(monkeypatch, location):
    template, records = case()
    if location == "input":
        records[2]["actual"]["x"] = float("inf")
    elif location == "response":
        records[2]["observations"]["y"]["value"] = float("inf")
    else:
        # Finite standard uncertainty whose square overflows double precision.
        records[2]["observations"]["y"]["uncertainty"]["amount"] = 1e200
    calls = []
    monkeypatch.setattr(gp_fitting, "fit_gpytorch_mll_scipy", lambda *a, **k: calls.append(True))
    with pytest.raises(ModelTrainingError) as caught:
        fit_models(template, records, "gp_rbf_v1")
    assert "实验编号：[3]" in exception_diagnostic(caught.value)
    assert "训练数据检查" in str(caught.value)
    assert not calls


@pytest.mark.model
@pytest.mark.parametrize("preset", ["gp_rbf_v1", "gp_matern25_v1"])
@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("bounds", [(10., 20.), (10., 10. + 1e-9)])
def test_real_gp_accepts_tight_bounds_including_both_experimental_endpoints(preset, known, bounds):
    template, records = case(bounds, known)
    for record in records:
        template.validate_conditions(record["actual"])
    model, encoder, _, datasets, _ = fit_models(template, records, preset)
    encoded = encoder.encode([r["actual"] for r in records])
    assert encoded[0, 0] == 0. and encoded[-1, 0] == 1.
    posterior = model.posterior(encoded)
    assert torch.isfinite(posterior.mean).all() and torch.isfinite(posterior.variance).all()
    context = datasets["y"]["gp_training"]["context"]
    assert context["inputs"][0]["boundary_count"] == 2
    assert context["inputs"][0]["outside_experiment_ids"] == []


def test_unexpected_programming_error_is_not_retried_or_disguised(monkeypatch):
    template, records = case()
    calls = []
    def fail(*args, **kwargs):
        calls.append(True)
        raise TypeError("controlled incompatible optimizer interface")
    monkeypatch.setattr(gp_fitting, "fit_gpytorch_mll_scipy", fail)
    with pytest.raises(ModelTrainingError) as caught:
        fit_models(template, records, "gp_rbf_v1")
    assert len(calls) == 1
    assert "TypeError: controlled incompatible optimizer interface" in exception_diagnostic(caught.value)


def test_direct_api_without_database_ids_uses_explicit_row_labels():
    template, records = case()
    for record in records:
        del record["id"]
    _, _, _, datasets, _ = fit_models(template, records, "gp_rbf_v1")
    assert datasets["y"]["gp_training"]["context"]["experiment_ids"] == [
        f"输入第 {i} 行（无实验编号）" for i in range(1, 6)
    ]
