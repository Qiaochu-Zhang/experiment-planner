import math
import pytest
from experiment_planner.metrics.uncertainty import Uncertainty, difference, propagate
from experiment_planner.metrics.formulas import FormulaGraph
from experiment_planner.domain.errors import ValidationError


def test_independent_difference():
    u = Uncertainty("std",1)
    r = difference(100,90,u,u)
    assert r["value"] == 10
    assert r["standard"] == pytest.approx(math.sqrt(2))


def test_bounds_and_intervals():
    u = Uncertainty("bounds",1)
    r = difference(100,90,u,u)
    assert r["standard"] is None
    assert r["interval"] == [8,12]
    assert Uncertainty("interval",1,distribution="normal",confidence=.95).standard() == pytest.approx(1/1.95996398454)
    assert Uncertainty("bounds",1,distribution="uniform").standard() == pytest.approx(1/math.sqrt(3))
    assert Uncertainty("sem",1).standard() == 1
    assert Uncertainty("unspecified",1).standard() is None
    assert Uncertainty("interval",1).standard() is None


def test_covariance():
    u = Uncertainty("std",1)
    assert difference(100,90,u,u,1)["standard"] == 0
    assert difference(100,90,u,u,-1)["standard"] == 2
    with pytest.raises(ValidationError): difference(100,90,u,u,2)


def test_shared_sources_and_dag():
    graph = FormulaGraph([{"name":"x","unit":"nm"},{"name":"y","unit":"nm"}], [{"name":"a","unit":"nm","expression":"x-y"},{"name":"b","unit":"nm","expression":"a-a"}])
    u = Uncertainty("std",1,source="same_bias")
    result = propagate(graph,{"x":100.,"y":90.},{"x":u,"y":u})
    assert result["a"]["standard"] < 1e-12
    assert result["b"]["standard"] == 0


def test_unknown_not_zero(template):
    result = propagate(template.graph,{"sio2_initial_nm":100.,"sio2_remaining_nm":90.},{})
    assert result["sio2_loss_nm"]["standard"] is None
