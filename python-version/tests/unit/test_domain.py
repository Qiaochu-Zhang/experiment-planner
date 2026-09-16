import copy
import pytest
from experiment_planner.domain.template import Template, parse_value
from experiment_planner.domain.errors import ValidationError
from experiment_planner.metrics.formulas import Formula, FormulaGraph
from experiment_planner.precision.rounding import round_decimal, quantize, display


def test_builtin_matches_spec(template):
    assert len(template.parameters) == 8
    assert len(template.measurements) == 4
    assert template.parameters[3]["bounds"] == [100, 1500]
    assert template.parameters[5]["unit"] == "mT"
    assert all(p["execution_rounding"]["mode"] == "none" for p in template.parameters)
    assert template.data["ratio_policy"]["mode"] == "require_configuration"


@pytest.mark.parametrize("value,digits,expected", [(1.25,1,1.3),(-1.25,1,-1.3),(15,-1,20),(-15,-1,-20),(2.5,0,3),(-2.5,0,-3)])
def test_rounding(value,digits,expected): assert round_decimal(value,digits) == expected


def test_grid_and_conflict():
    assert quantize(2.1,{"mode":"step","step":.5,"origin":.2}) == 2.2
    with pytest.raises(ValidationError): quantize(1,{"mode":"step","step":.5,"digits":1})
    with pytest.raises(ValidationError): round_decimal(True)


@pytest.mark.parametrize("raw,expected", [("False",False),("否",False),("0",False),("True",True),(None,None),("",None)])
def test_boolean(raw,expected): assert parse_value(raw,{"name":"b","value_type":"bool"}) is expected


def test_invalid_boolean():
    with pytest.raises(ValidationError): parse_value("anything",{"name":"b","value_type":"bool"})


@pytest.mark.parametrize("expression", ["__import__('os')", "a.__class__", "[a][0]", "a ** 99", "(lambda: 1)()", "open('file')", "round(a, a)", "a + missing"])
def test_formula_rejects_code(expression):
    with pytest.raises(ValidationError): Formula(expression,{"a":"nm"})


def test_formulas(template, measurements):
    result = template.graph.evaluate(measurements)
    assert result["sio2_loss_nm"].value == 10
    assert result["sin_loss_nm"].value == 1
    assert result["selectivity_abs"].value == 10
    measurements["sio2_remaining_nm"] = 110
    measurements["sin_remaining_nm"] = 100
    result = template.graph.evaluate(measurements)
    assert result["sio2_loss_nm"].value == -10
    assert result["selectivity_abs"].value is None
    assert result["selectivity_abs"].status == "undefined"


def test_missing_keeps_other_response(template):
    result = template.graph.evaluate({"sio2_initial_nm": 100,"sio2_remaining_nm":90})
    assert result["sio2_loss_nm"].value == 10
    assert result["sin_loss_nm"].status == "missing"


def test_units_cycles_and_roles(template):
    with pytest.raises(ValidationError): Formula("a+b",{"a":"nm","b":"W"})
    with pytest.raises(ValidationError): FormulaGraph([], [{"name":"a","unit":"nm","expression":"b"},{"name":"b","unit":"nm","expression":"a"}])
    data = copy.deepcopy(template.data)
    data["measurements"][2]["use_as_model_input"] = True
    with pytest.raises(ValidationError): Template(data)


def test_display_does_not_modify_ratio(template, measurements):
    measurements["sin_remaining_nm"] = 99.999
    result = template.graph.evaluate(measurements)
    assert display(result["sin_loss_nm"].value, 1) == "0.0"
    assert result["selectivity_abs"].value == pytest.approx(10000)


def test_min_max_round():
    assert Formula("round(max(a,b)-min(a,b), 1)",{"a":"nm","b":"nm"}).evaluate({"a":2.25,"b":1.}) == 1.3


def test_ratio_requires_explicit_strategy(template):
    with pytest.raises(ValidationError): template.require_ratio_configuration()
    t = template.revised(ratio_policy={**template.data["ratio_policy"],"mode":"remove"})
    t.require_ratio_configuration()
    with pytest.raises(ValidationError): template.revised(ratio_policy={"mode":"stabilized","epsilon_nm":0})
