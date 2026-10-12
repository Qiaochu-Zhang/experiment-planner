import pytest
from experiment_planner.engine.space import BatchRequest
from experiment_planner.worker.process import CalculationTask
from experiment_planner.domain.errors import ValidationError
from experiment_planner.application.synthetic import synthetic_records
from experiment_planner.engine.models import fit_models
from experiment_planner.plots.trends import plot_slice


def test_cancel_worker_preserves_project(service):
    p=service.project
    before=p.snapshot()
    task=CalculationTask(p,BatchRequest(n=1))
    with pytest.raises(ValidationError):CalculationTask(p,BatchRequest(n=1))
    task.cancel()
    assert p.snapshot()==before
    assert str(p.path) not in CalculationTask.active
    from filelock import FileLock
    with FileLock(str(p.path)+".generate.lock"):
        with pytest.raises(ValidationError,match="另一个程序窗口"):
            CalculationTask(p,BatchRequest(n=1))


@pytest.mark.model
@pytest.mark.parametrize("custom_ranges", [False, True])
def test_local_one_and_two_dimensional_plots(service,tmp_path,monkeypatch,custom_ranges):
    from matplotlib.figure import Figure
    limits = []
    savefig = Figure.savefig
    def save_with_limits(figure, *args, **kwargs):
        limits.append((figure.axes[0].get_xlim(), figure.axes[0].get_ylim()))
        return savefig(figure, *args, **kwargs)
    monkeypatch.setattr(Figure, "savefig", save_with_limits)
    p=service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":"stabilized","epsilon_nm":1.}))
    for row in synthetic_records(p.template,6):service.add_record(**row)
    model,encoder,names,_,_=fit_models(p.template,p.experiments(),"bayesian_linear_v1")
    baseline=p.experiments()[0]["actual"]
    for variables in (["cl2_sccm"],["cl2_sccm","rf_w"]):
        destination=tmp_path/f"slice{len(variables)}.png"
        ranges = {name: [12, 28] for name in variables} if custom_ranges else None
        result=plot_slice(model,encoder,names,p.template,baseline,variables,"sio2_loss_nm",destination,p.revision,points=4,ranges=ranges)
        assert destination.stat().st_size>1000
        assert result["revision"]==p.revision
        assert result["ranges"] == (ranges or {name: [0, 100] for name in variables})
        assert limits[-1][0] == tuple(result["ranges"][variables[0]])
        if len(variables) == 2:
            assert limits[-1][1] == tuple(result["ranges"][variables[1]])
        for c in result["conditions"]:
            assert all(c[k]==v for k,v in baseline.items() if k not in variables)
            assert all(result["ranges"][k][0] <= c[k] <= result["ranges"][k][1] for k in variables)
