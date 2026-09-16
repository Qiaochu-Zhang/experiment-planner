import copy
import pytest
import torch
from experiment_planner.application.synthetic import synthetic_records
from experiment_planner.engine.models import fit_models, BayesianLinear, BernoulliLogit
from experiment_planner.engine.objectives import Objectives, prediction_summary
from experiment_planner.engine.space import BatchRequest
from experiment_planner.engine.planner import generate
from experiment_planner.domain.errors import CapabilityError, StaleVersionError
from experiment_planner.knowledge.priors import check_capabilities

pytestmark = pytest.mark.model


def seed_service(service, count=8, policy="stabilized"):
    p = service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":policy,"epsilon_nm":1.}))
    for row in synthetic_records(p.template,count): service.add_record(**row)


@pytest.mark.parametrize("preset",["gp_rbf_v1","gp_matern25_v1","bayesian_linear_v1"])
def test_real_model_fit_and_joint_prediction(service,preset):
    seed_service(service)
    model, encoder, names, datasets, notices = fit_models(service.project.template,service.project.experiments(),preset,seed=12)
    conditions = [service.project.experiments()[0]["actual"], service.project.experiments()[0]["actual"]]
    posterior = model.posterior(encoder.encode(conditions))
    torch.manual_seed(5)
    samples = posterior.rsample(torch.Size([256]))
    assert samples.shape == (256,2,2)
    assert (samples[:,0,:]-samples[:,1,:]).abs().max() < .01
    assert samples.std(0).min() > 0
    summary = prediction_summary(model,encoder,names,service.project.template,conditions)
    assert summary[0]["raw_selectivity_abs"]["mean"] is None
    assert summary[0]["sio2_loss_nm"]["mean"] is not None


def test_nonlinear_shared_samples(template):
    template = template.revised(ratio_policy={**template.data["ratio_policy"],"mode":"stabilized","epsilon_nm":1})
    objective = Objectives(template,["sio2_loss_nm","sin_loss_nm"])
    sample = torch.tensor([[[-2.,.5]], [[4.,-2.]]],dtype=torch.double)
    actual = objective.transformed(sample)
    assert torch.equal(actual,torch.tensor([[[2.,-.5,2.]],[[4.,-2.,2.]]],dtype=torch.double))
    assert actual[...,0].mean() != sample[...,0].mean().abs()


def test_bernoulli_single_class_and_joint():
    X = torch.linspace(0,1,8,dtype=torch.double).unsqueeze(-1)
    model = BernoulliLogit(X,torch.zeros(8,1,dtype=torch.double))
    draws = model.posterior(X[:2]).rsample(torch.Size([100]))
    assert (draws > 0).all() and (draws < 1).all()
    assert draws.std() > 0


@pytest.mark.parametrize("policy",["stabilized","valid_region","remove"])
def test_qlog_batch_restore_and_stale_guard(service,policy):
    seed_service(service,6,policy)
    request = BatchRequest(n=2,mode="single",baseline_id=1,variables=["cl2_sccm"],pool_size=8,seed=3)
    batch = generate(service.project.snapshot(),request)
    assert batch["stage"] == "model_driven"
    assert len(batch["candidates"]) == 2
    assert all(len(c["changes"]) == 1 for c in batch["candidates"])
    assert all(c["prediction"] is not None for c in batch["candidates"])
    bid, ids = service.commit_batch(batch)
    assert len(ids) == 2
    assert service.project.experiment(ids[0])["status"] == "pending"
    with pytest.raises(StaleVersionError): service.commit_batch(batch)
    assert service.project.batches()[0]["reference_point"] == batch["reference_point"]
    again=generate(service.project.snapshot(),BatchRequest(n=1,mode="single",baseline_id=1,variables=["cl2_sccm"],pool_size=6,seed=9))
    previous=[c["conditions"] for c in batch["candidates"]]
    assert again["candidates"][0]["conditions"] not in previous


def test_initialization_cross_quota(service, conditions):
    p=service.project
    service.update_template(p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":"remove"}))
    request=BatchRequest(n=4,mode="cross",baseline=conditions,cross_values={"rf_w":10.,"cl2_sccm":20.})
    batch=generate(p.snapshot(),request)
    assert batch["stage"] == "initialization"
    assert len(batch["candidates"]) == 4
    assert [len(c["changes"]) for c in batch["candidates"]] == [0,1,1,2]
    assert all(c["prediction"] is None for c in batch["candidates"])


def test_prior_excludes_per_response_and_changes_prediction(service):
    seed_service(service,5)
    p=service.project
    priors=[{"input":"cl2_sccm","response":"sio2_loss_nm","relation":"independent","source":"合成案例","enabled":True}]
    template=p.template.revised(knowledge_priors=priors)
    model,encoder,names,datasets,_=fit_models(template,p.experiments(),"bayesian_linear_v1")
    assert "cl2_sccm" not in datasets["sio2_loss_nm"]["features"]
    assert "cl2_sccm" in datasets["sin_loss_nm"]["features"]
    first=p.experiments()[0]["actual"]
    second={**first,"cl2_sccm":100-first["cl2_sccm"]}
    draws=model.posterior(encoder.encode([first,second])).rsample(torch.Size([30]))
    assert (draws[:,0,0]-draws[:,1,0]).abs().max()<.01
    priors=[{"input":"cl2_sccm","response":"sio2_loss_nm","relation":"monotonic","coefficient":2.,"strength":1000.,"source":"模拟强先验"}]
    positive=p.template.revised(knowledge_priors=priors)
    with pytest.raises(CapabilityError): check_capabilities(positive,"gp_rbf_v1")
    model,encoder,*_=fit_models(positive,p.experiments(),"bayesian_linear_v1")
    low={**first,"cl2_sccm":0.}; high={**first,"cl2_sccm":100.}
    draws=model.posterior(encoder.encode([low,high])).rsample(torch.Size([50]))
    assert (draws[:,1,0]-draws[:,0,0]).mean() > 100


@pytest.mark.parametrize("mode",["single","weighted"])
def test_qlog_single_and_weighted(service,mode):
    seed_service(service,6,"remove")
    p=service.project
    objectives=p.template.data["objectives"][:1] if mode=="single" else p.template.data["objectives"][:2]
    config={**p.template.data["optimization"],"mode":mode,"weights":[.6,.4],"scales":[50.,5.]}
    service.update_template(p.template.revised(objectives=objectives,optimization=config))
    batch=generate(p.snapshot(),BatchRequest(n=1,mode="single",baseline_id=1,variables=["rf_w"],pool_size=6,model="bayesian_linear_v1"))
    assert batch["stage"]=="model_driven"
    assert len(batch["candidates"])==1


def test_mixed_boolean_response_and_categorical_inputs(tmp_path):
    from experiment_planner.domain.template import Template
    from experiment_planner.storage.project import Project
    from experiment_planner.application.service import PlannerService
    data={"schema_version":2,"template_version":1,"name":"合成布尔例","parameters":[{"name":"x","label":"数值","unit":"1","value_type":"float","bounds":[0.,1.]},{"name":"enabled","label":"开关","unit":"1","value_type":"bool"},{"name":"category","label":"类别","unit":"1","value_type":"category","values":["a","b"]}],"measurements":[{"name":"y","label":"响应","unit":"1","value_type":"float","is_response":True},{"name":"event","label":"事件","unit":"1","value_type":"bool","is_response":True}],"derived_metrics":[],"objectives":[{"metric":"y","direction":"maximize","transform":"identity"}],"optimization":{"mode":"single"},"ratio_policy":{"mode":"remove"}}
    with Project.create(tmp_path/"mixed.sqlite","合成混合",Template(data)) as p:
        service=PlannerService(p)
        for i in range(8):
            service.add_record({"x":i/8,"enabled":bool(i%2),"category":"a" if i<4 else "b"},{"y":float(i),"event":bool(i>=4)})
        model,encoder,names,_,_=fit_models(p.template,p.experiments(),"bayesian_linear_v1")
        predictions=prediction_summary(model,encoder,names,p.template,[p.experiments()[0]["actual"]])
        assert 0 < predictions[0]["event"]["mean"] < 1
        batch=generate(p.snapshot(),BatchRequest(n=1,model="bayesian_linear_v1",pool_size=6))
        assert len(batch["candidates"])==1


def test_explicit_shared_error_not_ignored_by_models(service,conditions,measurements):
    for i in range(2):
        cells={n:{"value":v,"uncertainty":{"kind":"std","amount":1.,"source":"shared_instrument"}} for n,v in measurements.items()}
        service.add_record(conditions,cells)
    with pytest.raises(CapabilityError,match="共享误差"):
        fit_models(service.project.template,service.project.experiments(),"gp_rbf_v1")
