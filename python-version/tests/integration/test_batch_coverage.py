import pytest

from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.engine.planner import generate
from experiment_planner.engine.space import BatchRequest, candidate_pool, key
from experiment_planner.io.batch_export import export_batch
from experiment_planner.storage.project import Project
from experiment_planner.ui.messages import batch_text


MODES = [("full_space", False), ("single", False), ("double", False), ("double", True)]


def make_template(count=6, **overrides):
    return Template({"schema_version": 2, "template_version": 1,
                     "parameters": [{"name": f"x{i}", "bounds": [0, 10], "execution_rounding": {"mode": "digits", "digits": 0}}
                                    for i in range(count)] + [{"name": "frozen", "bounds": [0, 10]}],
                     "measurements": [{"name": "y", "is_response": True}], "derived_metrics": [],
                     "objectives": [{"metric": "y", "direction": "maximize"}],
                     "optimization": {"mode": "single"}, "ratio_policy": {"mode": "remove"}, **overrides})


def setup_project(tmp_path, template, initialized=False):
    project = Project.create(tmp_path / "coverage.sqlite", "变量覆盖合成测试", template)
    service = PlannerService(project)
    baseline = {p["name"]: 0 for p in template.parameters}
    service.add_record(baseline, {"y": 0} if initialized else {}, status="completed" if initialized else "pending")
    if initialized:
        for i in (1, 2, 3):
            service.add_record({p["name"]: i for p in template.parameters}, {"y": 10*i})
    return project, service, baseline


def assert_batch(batch, baseline, variables, mode, exact, n=10):
    rows = [c["conditions"] for c in batch["candidates"]]
    assert len(rows) == n
    assert len({key(row) for row in rows}) == n
    # Independent oracle: across actual returned rows, every selected column varies.
    assert all(len({row[name] for row in rows}) >= 2 for name in variables)
    for candidate in batch["candidates"]:
        if candidate["arrangement"] == "repeat":
            continue
        row = candidate["conditions"]
        changed = {name for name in baseline if row[name] != baseline[name]}
        assert changed <= set(variables)
        assert row["frozen"] == baseline["frozen"]
        if mode == "single":
            assert len(changed) == 1
        elif mode == "double":
            assert len(changed) in ({2} if exact else {1, 2})
    assert batch["variable_coverage"]["complete"]


@pytest.mark.parametrize("mode,exact", MODES)
@pytest.mark.parametrize("seed", [0, 7, 23])
def test_initialization_ten_rows_cover_six_variables(tmp_path, mode, exact, seed):
    template = make_template()
    p, service, baseline = setup_project(tmp_path, template)
    with p:
        variables = [f"x{i}" for i in range(6)]
        request = BatchRequest(n=10, mode=mode, exact_two=exact, baseline_id=1, variables=variables,
                               pool_size=32, seed=seed, exploration_count=2)
        batch = generate(p.snapshot(), request)
        assert_batch(batch, baseline, variables, mode, exact)
        assert all(c["prediction"] is None for c in batch["candidates"])
        assert sum(c["arrangement"] == "exploration" for c in batch["candidates"]) == 2
        assert [c["conditions"] for c in generate(p.snapshot(), request)["candidates"]] == [c["conditions"] for c in batch["candidates"]]


@pytest.mark.model
@pytest.mark.parametrize("preset", ["bayesian_linear_v1", "gp_rbf_v1", "gp_matern25_v1"])
@pytest.mark.parametrize("mode,exact", MODES)
def test_model_ten_rows_cover_variables_keep_repeat_and_exploration(tmp_path, preset, mode, exact):
    template = make_template()
    p, service, baseline = setup_project(tmp_path, template, initialized=True)
    with p:
        variables = [f"x{i}" for i in range(6)]
        request = BatchRequest(n=10, mode=mode, exact_two=exact, baseline_id=1, variables=variables,
                               model=preset, pool_size=24, seed=11, repeat_ids=[1], exploration_count=2)
        batch = generate(p.snapshot(), request)
        assert_batch(batch, baseline, variables, mode, exact)
        assert batch["stage"] == "model_driven"
        assert all(c["prediction"] is not None for c in batch["candidates"])
        assert sum(c["arrangement"] == "repeat" for c in batch["candidates"]) == 1
        assert sum(c["arrangement"] == "exploration" for c in batch["candidates"]) == 2
        assert not {key(c["conditions"]) for c in batch["candidates"] if c["arrangement"] != "repeat"} & {key(r["actual"]) for r in p.experiments()}
        service.commit_batch(batch)
        with Project(p.path) as restored:
            saved = restored.batches()[-1]
            assert saved["variable_coverage"] == batch["variable_coverage"]
            assert "均出现不同取值" in batch_text(saved, template)


@pytest.mark.parametrize("mode,exact", MODES)
def test_small_pool_preserves_each_variable_when_room_exists(mode, exact):
    template = make_template()
    baseline = {p["name"]: 0 for p in template.parameters}
    variables = [f"x{i}" for i in range(6)]
    request = BatchRequest(mode=mode, exact_two=exact, baseline=baseline, variables=variables, pool_size=6)
    pool = candidate_pool(template, request, excluded=[baseline])
    assert len(pool) == 6
    assert all(len({row[name] for row in pool}) >= 2 for name in variables)


@pytest.mark.parametrize("mode,exact", MODES)
def test_strong_score_preference_cannot_freeze_other_selected_variables(tmp_path, monkeypatch, mode, exact):
    import experiment_planner.engine.planner as planner

    template = make_template()
    p, _, baseline = setup_project(tmp_path, template, initialized=True)
    variables = [f"x{i}" for i in range(6)]
    if mode == "single":
        pool = [{**baseline, "x0": i} for i in range(1, 11)]
        pool += [{**baseline, f"x{i}": 1} for i in range(1, 6)]
    elif mode == "double":
        pool = [{**baseline, "x0": i, "x1": 1} for i in range(1, 11)]
        pool += [{**baseline, "x2": 1, "x3": 1}, {**baseline, "x4": 1, "x5": 1}]
    else:
        pool = [{**baseline, "x0": 10, "x1": i} for i in range(1, 11)]
        pool += [{**baseline, **{f"x{i}": 1 for i in range(2, 6)}}]

    class BiasedAcquisition:
        def __init__(self, **kwargs):
            pass

        def __call__(self, X):
            # Without coverage all ten choices favor x0, or the same x0/x1 pair.
            return 100 * X[..., 0].squeeze(-1)

        def set_X_pending(self, X):
            pass

    monkeypatch.setattr(planner, "candidate_pool", lambda *args, **kwargs: pool.copy())
    monkeypatch.setattr(planner, "qLogNoisyExpectedImprovement", BiasedAcquisition)
    with p:
        batch = generate(p.snapshot(), BatchRequest(n=10, mode=mode, exact_two=exact, baseline_id=1,
                         variables=variables, model="bayesian_linear_v1"))
        assert_batch(batch, baseline, variables, mode, exact)
        assert batch["request"]["exploration_strength"] == batch["request"]["exploration_count"] == 0
        assert batch["candidates"][1]["log_acquisition"] < batch["candidates"][0]["log_acquisition"]


def test_implicit_variables_cover_categories_booleans_and_discrete_text(tmp_path):
    parameters = [{"name": "x", "bounds": [0, 2], "value_type": "int"},
                  {"name": "gas", "value_type": "category", "values": ["A", "B"]},
                  {"name": "flag", "value_type": "bool"},
                  {"name": "recipe", "value_type": "text", "values": ["甲", "乙"], "use_as_model_input": False},
                  {"name": "note", "value_type": "text", "use_as_model_input": False},
                  {"name": "fixed", "fixed_value": 2, "bounds": [0, 3]}]
    template = make_template(parameters=parameters)
    baseline = {"x": 0, "gas": "A", "flag": False, "recipe": "甲", "note": "保持文字", "fixed": 2}
    with Project.create(tmp_path / "mixed.sqlite", "混合输入", template) as p:
        batch = generate(p.snapshot(), BatchRequest(n=5, mode="single", baseline=baseline))
        assert batch["variable_coverage"]["requested_variables"] == ["x", "gas", "flag", "recipe"]
        assert batch["variable_coverage"]["complete"]
        rows = [c["conditions"] for c in batch["candidates"]]
        assert all(len({row[name] for row in rows}) > 1 for name in ["x", "gas", "flag", "recipe"])
        assert all(row["note"] == "保持文字" and row["fixed"] == 2 for row in rows)


def test_empty_legal_pool_reports_shortfall_and_uncovered_variables(tmp_path):
    template = make_template(1, input_constraints=[{"coefficients": {"x0": 1}, "op": "<=", "rhs": 0}])
    p, _, _ = setup_project(tmp_path, template)
    with p:
        batch = generate(p.snapshot(), BatchRequest(n=10, baseline_id=1, mode="single", variables=["x0"]))
        assert batch["candidates"] == []
        assert batch["shortfall"]
        assert batch["variable_coverage"]["constant_variables"] == ["x0"]


def test_constraints_and_exhausted_history_are_reported_and_exported(tmp_path):
    template = make_template(3, input_constraints=[{"coefficients": {"x2": 1}, "op": "<=", "rhs": 0}])
    p, service, baseline = setup_project(tmp_path, template)
    with p:
        # Exhaust every legal single-variable change for x1 through pending history.
        for value in range(1, 11):
            service.add_record({**baseline, "x1": value}, {}, status="pending")
        batch = generate(p.snapshot(), BatchRequest(n=10, baseline_id=1, mode="single", variables=["x0", "x1", "x2"]))
        assert len(batch["candidates"]) == 10
        assert batch["variable_coverage"]["constant_variables"] == ["x1", "x2"]
        assert batch["variable_coverage"]["pool_constant_variables"] == ["x1", "x2"]
        assert all(c["conditions"]["x1"] == c["conditions"]["x2"] == 0 for c in batch["candidates"])
        assert "x1、x2" in batch_text(batch, template)
        service.commit_batch(batch)
        path = tmp_path / "coverage.xlsx"
        export_batch(p, path)
        from openpyxl import load_workbook
        book = load_workbook(path)
        assert "变量覆盖" in str(list(book["批次说明"].values))
        book.close()


@pytest.mark.parametrize("n,pool_size", [(1, 32), (2, 32), (10, 1)])
def test_insufficient_slots_or_pool_reports_actual_coverage(tmp_path, n, pool_size):
    template = make_template()
    p, _, _ = setup_project(tmp_path, template)
    with p:
        batch = generate(p.snapshot(), BatchRequest(n=n, mode="single", baseline_id=1,
                         variables=[f"x{i}" for i in range(6)], pool_size=pool_size))
        assert len(batch["candidates"]) == min(n, pool_size)
        assert not batch["variable_coverage"]["complete"]
        assert "仍未出现不同取值" in batch_text(batch, template)
        if n == 2:
            assert len(batch["variable_coverage"]["varied_variables"]) == 2
        if pool_size == 1:
            assert batch["shortfall"]


def test_all_repeat_batch_is_not_replaced_to_force_coverage(tmp_path):
    template = make_template()
    p, _, baseline = setup_project(tmp_path, template, initialized=True)
    with p:
        batch = generate(p.snapshot(), BatchRequest(n=2, baseline_id=1, mode="single", variables=["x0", "x1"],
                         repeat_ids=[1, 1], model="bayesian_linear_v1", pool_size=8))
        assert [c["conditions"] for c in batch["candidates"]] == [baseline, baseline]
        assert all(c["arrangement"] == "repeat" for c in batch["candidates"])
        assert batch["variable_coverage"]["constant_variables"] == ["x0", "x1"]


def test_cross_layout_keeps_explicit_combinations(tmp_path):
    template = make_template()
    p, _, baseline = setup_project(tmp_path, template, initialized=True)
    with p:
        batch = generate(p.snapshot(), BatchRequest(n=10, baseline_id=1, mode="cross", variables=[f"x{i}" for i in range(6)],
                         cross_values={"x0": 1, "x1": 2}, model="bayesian_linear_v1"))
        assert [c["conditions"] for c in batch["candidates"]] == [baseline, {**baseline, "x0": 1},
                         {**baseline, "x1": 2}, {**baseline, "x0": 1, "x1": 2}]
        assert batch["variable_coverage"] is None
