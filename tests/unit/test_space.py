import pytest
from experiment_planner.domain.template import Template
from experiment_planner.domain.errors import ValidationError
from experiment_planner.engine.space import BatchRequest, candidate_pool, changes


@pytest.mark.parametrize("mode,exact,counts",[("single",False,{1}),("double",False,{1,2}),("double",True,{2})])
def test_subspaces(template,conditions,mode,exact,counts):
    request = BatchRequest(mode=mode,baseline=conditions,exact_two=exact,variables=["cl2_sccm","rf_w"],pool_size=40)
    pool = candidate_pool(template,request)
    assert pool
    for c in pool:
        diff = changes(template,conditions,c)
        assert len(diff) in counts
        assert set(diff) <= {"cl2_sccm","rf_w"}


def test_finite_pool_does_not_fill_duplicates(template, conditions):
    data = template.data.copy()
    data["parameters"] = [{**p,"fixed_value":conditions[p["name"]]} for p in template.parameters]
    fixed = Template(data)
    pool = candidate_pool(fixed,BatchRequest(n=6),[conditions])
    assert pool == []


def test_invalid_baseline_and_quota(template,conditions):
    with pytest.raises(ValidationError): BatchRequest(mode="single",baseline={**conditions,"rf_w":101}).validate(template)
    with pytest.raises(ValidationError): BatchRequest(n=3,mode="cross",baseline=conditions,cross_values={"rf_w":10,"cl2_sccm":20}).validate(template)
