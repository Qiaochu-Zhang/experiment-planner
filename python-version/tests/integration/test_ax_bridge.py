"""Repeated conditions share an Ax arm, while each run keeps its own trial/data."""
import copy
import json

import pytest

from experiment_planner.application.synthetic import synthetic_records
from experiment_planner.engine.ax_bridge import rebuild, snapshot
from experiment_planner.engine.planner import generate
from experiment_planner.engine.space import BatchRequest
from experiment_planner.storage.project import Project


@pytest.mark.parametrize(
    "status, ax_status",
    [("completed", "COMPLETED"), ("partial", "RUNNING"),
     ("pending", "CANDIDATE"), ("running", "RUNNING"),
     ("failed", "FAILED"), ("cancelled", "ABANDONED")],
)
def test_duplicate_conditions_keep_separate_trials_and_measurements(
    service, conditions, measurements, status, ax_status
):
    project = service.project
    first_id = service.add_record({**conditions, "cl2_sccm": 20.}, measurements)
    original_id = service.add_record(conditions, measurements)
    repeated_measurements = {**measurements, "sio2_remaining_nm": 89.}
    if status == "partial":
        repeated_measurements = {k: v for k, v in repeated_measurements.items()
                                 if k.startswith("sio2_")}
    repeat_id = service.add_record(conditions, repeated_measurements, status=status)
    before = project.snapshot()

    experiment, mapping = rebuild(project.template, project.experiments())

    assert len(experiment.trials) == 3
    assert len(experiment.arms_by_signature) == 2
    assert mapping == {str(first_id): 0, str(original_id): 1, str(repeat_id): 2}
    first, original, repeat = [experiment.trials[i] for i in range(3)]
    assert first.arm.name != original.arm.name
    assert original.arm.name == repeat.arm.name == f"experiment_{original_id}"
    assert original.status.name == "COMPLETED"
    assert repeat.status.name == ax_status
    assert original.arm.parameters == repeat.arm.parameters == conditions

    data = experiment.lookup_data().df
    original_data = data[data.trial_index == original.index].set_index("metric_name")
    assert original_data.loc["sio2_loss_nm", "mean"] == 10.
    repeat_data = data[data.trial_index == repeat.index].set_index("metric_name")
    if status in ("completed", "partial"):
        assert repeat_data.loc["sio2_loss_nm", "mean"] == 11.
        assert len(repeat_data) == (1 if status == "partial" else 2)
    else:
        assert repeat_data.empty
    payload = snapshot(experiment, mapping)
    json.dumps(payload, allow_nan=False)
    assert payload["business_id_to_trial"] == mapping
    assert project.snapshot() == before


@pytest.mark.model
@pytest.mark.parametrize("arrangement", ["repeat", "cross"])
def test_recommend_after_saving_and_completing_repeated_conditions(
    service, tmp_path, arrangement
):
    project = service.project
    service.update_template(project.template.revised(
        ratio_policy={**project.template.data["ratio_policy"], "mode": "remove"}
    ))
    for row in synthetic_records(project.template, count=5):
        service.add_record(**row)
    original = project.experiment(1)
    if arrangement == "repeat":
        request = BatchRequest(n=1, repeat_ids=[1], model="bayesian_linear_v1", pool_size=6)
    else:
        request = BatchRequest(
            n=4, mode="cross", baseline_id=1, model="bayesian_linear_v1",
            cross_values={name: (original["actual"][name] + 1.) % 100
                          for name in ("cl2_sccm", "rf_w")},
        )
    batch = generate(project.snapshot(), request)
    _, ids = service.commit_batch(batch)
    repeat = project.experiment(ids[0])
    assert repeat["actual"] == original["actual"]
    assert repeat["status"] == "pending"
    saved = project.snapshot()
    next_batch = generate(project.snapshot(), BatchRequest(
        n=1, model="bayesian_linear_v1", pool_size=6, seed=7,
    ))
    assert len(next_batch["candidates"]) == 1
    assert all(d["count"] == 5 for d in next_batch["model_datasets"].values())
    assert project.snapshot() == saved
    service.commit_batch(next_batch)

    observations = copy.deepcopy(original["observations"])
    observations["sio2_remaining_nm"]["value"] -= 1.
    service.revise_record(ids[0], original["actual"], observations, status="completed")
    assert project.experiment(1) == original
    assert project.experiment(ids[0])["prediction"] == repeat["prediction"]
    backup = tmp_path / f"{arrangement}-restored.sqlite"
    project.backup(backup)
    with Project(backup) as restored:
        assert restored.experiments() == project.experiments()
        result = generate(restored.snapshot(), BatchRequest(
            n=1, model="bayesian_linear_v1", pool_size=6, seed=11,
        ))
        assert result["stage"] == "model_driven"
        assert len(result["candidates"]) == 1
        assert all(d["count"] == 6 for d in result["model_datasets"].values())
        mapping = result["ax_snapshot"]["business_id_to_trial"]
        assert mapping["1"] != mapping[str(ids[0])]
