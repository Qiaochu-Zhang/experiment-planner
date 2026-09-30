import pytest

from experiment_planner.application.analysis import analyze
from experiment_planner.engine.models import fit_models

pytestmark = pytest.mark.model


@pytest.mark.parametrize("preset", ["gp_rbf_v1", "gp_matern25_v1", "bayesian_linear_v1"])
def test_fixed_conditions_time_changes_cumulative_etch_prediction(service, conditions, preset, tmp_path):
    p = service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"], "mode": "remove"}))
    for seconds in (20., 40., 60., 80., 100., 120., 140., 160.):
        values = {"sio2_initial_nm": 200., "sio2_remaining_nm": 200.-.5*seconds,
                  "sin_initial_nm": 100., "sin_remaining_nm": 100.-.02*seconds}
        service.add_record({**conditions, "etch_time_s": seconds}, {
            name: {"value": value, "uncertainty": {"kind": "std", "amount": .2}}
            for name, value in values.items()})
    low = {**conditions, "etch_time_s": 40.}
    high = {**conditions, "etch_time_s": 140.}
    model, encoder, names, datasets, _ = fit_models(p.template, p.experiments(), preset)
    assert "etch_time_s" in datasets["sio2_loss_nm"]["features"]
    assert datasets["sio2_loss_nm"]["feature_ranges"]["etch_time_s"] == {"unique_count": 8, "min": 20., "max": 160.}
    means = model.posterior(encoder.encode([low, high])).mean.detach()
    index = names.index("sio2_loss_nm")
    assert float(means[1, index] - means[0, index]) > 30.
    assert float(means[0, index]) == pytest.approx(20., abs=4.)
    assert float(means[1, index]) == pytest.approx(70., abs=4.)
    report = analyze(p.snapshot(), {"conditions": [low, high], "model": preset,
        "plot_path": str(tmp_path / "time.png"), "variables": ["etch_time_s"], "metric": "sio2_loss_nm", "points": 8})
    assert report["predictions"][1]["sio2_loss_nm"]["quantiles"][1] > report["predictions"][0]["sio2_loss_nm"]["quantiles"][1] + 30.
    assert len(report["plot"]["conditions"]) == 8
    assert any("没有除以" in notice for notice in report["notices"])


def test_constant_time_reports_insufficient_evidence(service, conditions, measurements):
    for flow in (20., 80.): service.add_record({**conditions, "cl2_sccm": flow}, measurements)
    _, _, _, datasets, notices = fit_models(service.project.template, service.project.experiments(), "bayesian_linear_v1")
    assert datasets["sio2_loss_nm"]["feature_ranges"]["etch_time_s"]["unique_count"] == 1
    assert any("刻蚀时间" in notice and "只有一个取值" in notice for notice in notices)


def test_linear_noise_uses_effective_rank_for_fixed_inputs(service, conditions):
    for index, seconds in enumerate((20., 40., 60., 80., 100., 120., 140., 160.)):
        loss = .5*seconds + (2. if index % 2 else -2.)
        service.add_record({**conditions, "etch_time_s": seconds}, {
            "sio2_initial_nm": 200., "sio2_remaining_nm": 200.-loss,
            "sin_initial_nm": 100., "sin_remaining_nm": 99.})
    _, _, _, _, notices = fit_models(service.project.template, service.project.experiments(), "bayesian_linear_v1")
    notice = next(n for n in notices if n.startswith("sio2_loss_nm: 未提供误差"))
    variance = float(notice.split("方差=")[1].split("，")[0])
    # Fixed nuisance inputs add no residual degrees. Treating all 9 columns as
    # independent overstates the noise (> 25) and suppresses the learned slope.
    assert 1. < variance < 10.
