import copy

import pytest

from experiment_planner.domain.errors import ValidationError
from experiment_planner.plots.trends import slice_conditions


def test_ranges_limit_both_axes_and_preserve_template_and_fixed_inputs(template, conditions):
    before = copy.deepcopy(template.data)
    ranges = {"cl2_sccm": [12, 28], "rf_w": [20, 40]}
    rows = slice_conditions(template, conditions, list(ranges), points=5, ranges=ranges)
    assert len(rows) == 25
    for name, bounds in ranges.items():
        assert min(c[name] for c in rows) == bounds[0]
        assert max(c[name] for c in rows) == bounds[1]
    assert all(all(c[k] == v for k, v in conditions.items() if k not in ranges) for c in rows)
    assert template.data == before
    # Omitted bounds preserve the existing full-template-range behavior.
    full = slice_conditions(template, conditions, ["cl2_sccm"], points=5)
    assert [c["cl2_sccm"] for c in full] == [0, 25, 50, 75, 100]


@pytest.mark.parametrize("ranges", [[], {"rf_w": [0, 10]}, {"cl2_sccm": [20, 10]},
    {"cl2_sccm": [10, 10]}, {"cl2_sccm": [-1, 10]}, {"cl2_sccm": [0, 101]},
    {"cl2_sccm": [0, float("nan")]}, {"cl2_sccm": [0, float("inf")]},
    {"cl2_sccm": [False, 10]}, {"cl2_sccm": ["0", 10]}, {"cl2_sccm": [0]}])
def test_invalid_ranges_are_rejected(template, conditions, ranges):
    with pytest.raises(ValidationError):
        slice_conditions(template, conditions, ["cl2_sccm"], ranges=ranges)


@pytest.mark.parametrize("points", [0, 1, 31, True, 2.5])
def test_invalid_sampling_counts(template, conditions, points):
    with pytest.raises(ValidationError, match="2–30"):
        slice_conditions(template, conditions, ["cl2_sccm"], points=points)


def test_rounded_points_stay_in_selected_range(template, conditions):
    parameters = copy.deepcopy(template.parameters)
    parameters[0]["execution_rounding"] = {"mode": "step", "step": 5}
    template = template.revised(parameters=parameters)
    rows = slice_conditions(template, conditions, ["cl2_sccm"], ranges={"cl2_sccm": [12, 28]})
    assert [c["cl2_sccm"] for c in rows] == [15, 20, 25]
    for bounds in ([11, 14], [14, 16]):
        with pytest.raises(ValidationError, match="合法"):
            slice_conditions(template, conditions, ["cl2_sccm"], ranges={"cl2_sccm": bounds})


def test_integer_axis_and_constraints(template, conditions):
    parameters = copy.deepcopy(template.parameters)
    parameters[0].update(value_type="int", execution_rounding={"mode": "none"})
    template = template.revised(parameters=parameters, input_constraints=[
        {"coefficients": {"cl2_sccm": 1, "rf_w": 1}, "op": "<=", "rhs": 100}])
    baseline = {**conditions, "cl2_sccm": 0, "rf_w": 98}
    rows = slice_conditions(template, baseline, ["cl2_sccm"], points=15, ranges={"cl2_sccm": [0.5, 4.5]})
    assert [c["cl2_sccm"] for c in rows] == [1, 2]
    with pytest.raises(ValidationError, match="合法条件"):
        slice_conditions(template, baseline, ["cl2_sccm"], ranges={"cl2_sccm": [3, 10]})
