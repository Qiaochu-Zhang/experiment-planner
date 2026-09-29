"""Independent signed-target oracles and end-to-end exploration allocation."""
import copy

import numpy as np
import pytest
import torch

from experiment_planner.application.records import derive, normalize_observations
from experiment_planner.application.synthetic import synthetic_records
from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.engine.exploration import adjusted_scores, dedicated_scores
from experiment_planner.engine.models import Encoder
from experiment_planner.engine.objectives import Objectives, prediction_summary
from experiment_planner.engine.planner import generate
from experiment_planner.engine.space import BatchRequest, key
from experiment_planner.storage.project import Project


class FixedPosterior:
    def __init__(self, values):self.values=torch.tensor(values,dtype=torch.double).unsqueeze(1)
    def posterior(self, _):return self
    def rsample(self, shape):
        assert shape[0]==len(self.values)
        return self.values


@pytest.mark.parametrize("mode",["stabilized","valid_region","remove","require_configuration"])
def test_signed_ratio_and_targets_match_independent_oracle(template, conditions, mode):
    t=template.revised(ratio_policy={**template.data["ratio_policy"],"mode":mode,"epsilon_nm":1.0})
    draws=[[-4.,.1],[2.,-.2],[6.,2.],[-8.,-4.]]
    result=prediction_summary(FixedPosterior(draws),Encoder(t),["sio2_loss_nm","sin_loss_nm"],t,[conditions],samples=4)[0]
    expected=np.quantile([-40.,-10.,3.,2.],[.025,.5,.975])
    assert result["objective_predictions"][0]["mean"]==-1.
    assert result["objective_predictions"][1]["mean"]==pytest.approx(1.575)
    for name in ("selectivity","raw_selectivity"):
        assert result[name]["mean"] is None
        np.testing.assert_allclose(result[name]["quantiles"],expected)
    if mode=="stabilized":
        assert result["selectivity_stable"]["mean"]==pytest.approx(-.25)
        assert result["objective_predictions"][2]["mean"]==pytest.approx(-.25)
    if mode=="valid_region":
        assert result["feasibility_probability"]==.5
        np.testing.assert_allclose(result["objective_predictions"][2]["quantiles"],expected)


@pytest.mark.parametrize("a,b,expected",[(-4,.1,-4),(2,-.2,-2),(6,2,3),(-8,-4,2),(2,0,2)])
def test_observation_and_posterior_stabilization_agree(template,conditions,a,b,expected):
    t=template.revised(ratio_policy={**template.data["ratio_policy"],"mode":"stabilized","epsilon_nm":1.})
    measurements={"sio2_initial_nm":100.,"sio2_remaining_nm":100.-a,"sin_initial_nm":100.,"sin_remaining_nm":100.-b}
    record=derive(t,conditions,normalize_observations(t,measurements))
    sample=torch.tensor([[[a,b]]],dtype=torch.double)
    objective=Objectives(t,["sio2_loss_nm","sin_loss_nm"]).transformed(sample)
    assert record["selectivity_stable"]["value"]==pytest.approx(expected)
    assert objective[0,0,2].item()==pytest.approx(expected)


def test_intensity_changes_uncertain_candidates_preference_without_reversing_feasibility():
    log_bo=torch.tensor([-1.,-1.2,-1.2])
    uncertainty=torch.tensor([.1,4.,10.])
    feasibility=torch.tensor([1.,1.,0.])
    assert adjusted_scores(log_bo,uncertainty,feasibility,0).argmax()==0
    boosted=adjusted_scores(log_bo,uncertainty,feasibility,2)
    assert boosted.argmax()==1
    assert boosted[2]==log_bo[2]
    dedicated=dedicated_scores(torch.tensor([[0.],[.5],[1.]]),uncertainty,feasibility,torch.tensor([[0.]]))
    assert dedicated.argmax()==1
    assert dedicated[0]==0 and dedicated[2]==0


def test_custom_ratio_uses_same_units_in_measurement_prediction_and_feasibility():
    template=Template({"schema_version":2,"template_version":1,"parameters":[{"name":"x","bounds":[0,1]}],
        "measurements":[{"name":"a","unit":"nm","is_response":True},{"name":"b","unit":"um","is_response":True}],
        "derived_metrics":[{"name":"ratio","expression":"a/b","unit":"1","model_base":False}],
        "objectives":[{"metric":"ratio","direction":"maximize"}],"optimization":{"mode":"single"},
        "ratio_policy":{"mode":"stabilized","epsilon_nm":1.,"original_metric":"ratio"}})
    records=derive(template,{"x":.5},normalize_observations(template,{"a":2.,"b":-.0002}))
    assert records["ratio"]["value"]==pytest.approx(-10.)
    assert records["selectivity_stable"]["value"]==pytest.approx(-2.)
    report=prediction_summary(FixedPosterior([[2.,-.0002]]*4),Encoder(template),["a","b"],template,[{"x":.5}],samples=4)[0]
    assert report["selectivity_stable"]["mean"]==pytest.approx(-2.)
    np.testing.assert_allclose(report["ratio"]["quantiles"],[-10.]*3)
    valid=template.revised(ratio_policy={**template.data["ratio_policy"],"mode":"valid_region"})
    samples=torch.tensor([[[2.,.002]],[[2.,.0002]]],dtype=torch.double)
    constraint=Objectives(valid,["a","b"]).constraints()[0]
    assert (constraint(samples)<=0).flatten().tolist()==[True,False]


@pytest.mark.parametrize("kwargs",[{"exploration_count":-1},{"exploration_count":1.5},{"n":2,"repeat_ids":[1,2],"exploration_count":1},{"exploration_strength":float("nan")},{"exploration_strength":float("inf")},{"exploration_strength":-1},{"exploration_strength":True},{"exploration_strength":101}])
def test_invalid_exploration_settings_are_rejected(template,kwargs):
    with pytest.raises(ValidationError):BatchRequest(**kwargs).validate(template)


@pytest.mark.model
@pytest.mark.parametrize("preset",["bayesian_linear_v1","gp_rbf_v1","gp_matern25_v1"])
def test_exact_exploration_quota_duplicates_pending_and_restore(service,tmp_path,preset):
    p=service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":"remove"}))
    for row in synthetic_records(p.template,6):service.add_record(**row)
    duplicate=p.experiment(1)
    changed=copy.deepcopy(duplicate["observations"]);changed["sio2_remaining_nm"]["value"]-=2
    service.add_record(duplicate["actual"],changed)
    request=BatchRequest(n=7,repeat_ids=[1],exploration_count=2,exploration_strength=1.5,model=preset,pool_size=16,seed=19)
    batch=generate(p.snapshot(),request)
    assert [c["arrangement"] for c in batch["candidates"]].count("repeat")==1
    assert [c["arrangement"] for c in batch["candidates"]].count("exploration")==2
    assert [c["arrangement"] for c in batch["candidates"]].count("new")==4
    assert all(d["count"]==7 for d in batch["model_datasets"].values())
    new=[c for c in batch["candidates"] if c["arrangement"]!="repeat"]
    assert len({key(c["conditions"]) for c in new})==6
    assert not {key(c["conditions"]) for c in new}&{key(r["actual"]) for r in p.experiments()}
    again=generate(p.snapshot(),request)
    assert [c["conditions"] for c in again["candidates"]]==[c["conditions"] for c in batch["candidates"]]
    service.commit_batch(batch)
    path=tmp_path/"恢复.sqlite";p.backup(path)
    with Project(path) as restored:
        saved=restored.batches()[-1]
        assert saved["request"]["exploration_count"]==2
        assert saved["candidates"][1]["normalized_uncertainty"]>0
        assert restored.experiments()[-6]["arrangement"]=="exploration"
        subsequent=generate(restored.snapshot(),BatchRequest(n=2,exploration_count=1,model="bayesian_linear_v1",pool_size=6))
        assert not {key(c["conditions"]) for c in subsequent["candidates"]}&{key(r["actual"]) for r in restored.experiments()}


def test_initialization_quota_and_cross_conflict(service,conditions):
    p=service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":"remove"}))
    result=generate(p.snapshot(),BatchRequest(n=6,exploration_count=2))
    assert len(result["candidates"])==6
    assert sum(c["arrangement"]=="exploration" for c in result["candidates"])==2
    assert all(c["prediction"] is None for c in result["candidates"])
    with pytest.raises(ValidationError,match="交叉布局"):
        BatchRequest(n=6,mode="cross",baseline=conditions,cross_values={"cl2_sccm":1,"rf_w":2},exploration_count=1).validate(p.template)
