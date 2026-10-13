import copy
import json
import math

import pytest
import torch

from experiment_planner.application.measurement_uncertainty import plan_standard_uncertainty, raw_measurement_names
from experiment_planner.application.service import PlannerService
from experiment_planner.domain.errors import CapabilityError, StaleVersionError, ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.engine.models import fit_models
from experiment_planner.storage.project import Project, encode
from experiment_planner.storage.session import ProjectSession


SIO2 = ["sio2_initial_nm", "sio2_remaining_nm"]


def test_bulk_recomputes_derived_preserves_values_metadata_and_undoes_once(service, conditions, measurements):
    p = service.project
    ids = [service.add_record(conditions, measurements, note=f"原备注 {i}") for i in range(3)]
    old = p.experiment(ids[0]); old.pop("id")
    old.update(batch_id=9, prediction={"kept": True}, repeat_of=ids[1], repeat_of_uid="repeat-uid", custom={"kept": [1]})
    old["observations"][SIO2[0]]["note"] = "校准后的测量"
    with p.transaction():
        p.db.execute("UPDATE experiments SET payload=?,import_key=? WHERE id=?", (encode(old), "source-row-1", ids[0]))
        p.bump()
    before, revision = p.experiments(), p.revision
    summary = service.set_measurement_uncertainty([ids[0], ids[1], ids[0]], SIO2, .5, expected_revision=revision)
    assert summary == {"changed_records": 2, "changed_cells": 4, "replaced_known": 0, "skipped_missing": 0, "skipped_known": 0}
    after = p.experiments()
    assert p.revision == revision + 1
    assert after[2] == before[2]
    for prior, updated in zip(before[:2], after[:2]):
        for key in prior.keys() - {"derived", "observations", "updated"}:
            assert updated[key] == prior[key]
        for name, cell in updated["observations"].items():
            assert {k: v for k, v in cell.items() if k != "uncertainty"} == {k: v for k, v in prior["observations"][name].items() if k != "uncertainty"}
        assert updated["derived"]["sio2_loss_nm"]["value"] == 10.
        assert updated["derived"]["sio2_loss_nm"]["uncertainty"]["standard"] == pytest.approx(math.sqrt(.5))
        assert updated["derived"]["sin_loss_nm"]["uncertainty"]["standard"] is None
    audit = p.history()[-2:]
    assert all(row["entity"] == "measurement_uncertainty" and row["revision"] == p.revision for row in audit)
    assert json.loads(audit[0]["old_payload"])["observations"] == before[0]["observations"]
    service.undo(); assert p.experiments() == before
    service.redo(); assert p.experiments() == after
    assert p.db.execute("SELECT import_key FROM experiments WHERE id=?", (ids[0],)).fetchone()[0] == "source-row-1"


def test_only_unknown_preserves_convertible_errors_skips_unmeasured_and_keeps_sources(service, conditions):
    supplied = {
        SIO2[0]: {"value": 100, "uncertainty": {"kind": "bounds", "amount": 3, "distribution": "uniform"}},
        SIO2[1]: {"value": 90, "uncertainty": {"kind": "bounds", "amount": 1, "source": "within-this-record"}},
        "sin_initial_nm": {"value": 100, "uncertainty": {"kind": "sem", "amount": .1}},
        "sin_remaining_nm": {"value": None},
    }
    first = service.add_record(conditions, supplied, status="partial")
    pending = service.add_record(conditions, {}, status="pending")
    before = service.project.experiments()
    names = [f["name"] for f in service.project.template.measurements]
    result = service.set_measurement_uncertainty([first, pending], names, .5, only_unknown=True)
    assert result == {"changed_records": 1, "changed_cells": 1, "replaced_known": 0, "skipped_missing": 5, "skipped_known": 2}
    updated = service.project.experiment(first)
    assert updated["observations"][SIO2[0]] == before[0]["observations"][SIO2[0]]
    uncertainty = updated["observations"][SIO2[1]]["uncertainty"]
    assert uncertainty["kind"] == "std" and uncertainty["amount"] == .5
    assert uncertainty["source"] == "within-this-record" and uncertainty["distribution"] is None
    assert updated["observations"]["sin_remaining_nm"]["value"] is None
    assert service.project.experiment(pending) == before[1]


def test_overwrite_converts_interval_and_preserves_correlation(service, conditions):
    u = {"kind": "interval", "amount": 2., "distribution": "normal", "coverage_factor": 2., "confidence": .95, "source": "shared-in-one-response"}
    eid = service.add_record(conditions, {name: {"value": value, "uncertainty": u} for name, value in zip(SIO2, [100, 90])})
    summary = service.set_measurement_uncertainty([eid], SIO2, .5)
    assert summary["replaced_known"] == 2
    record = service.project.experiment(eid)
    assert record["derived"]["sio2_loss_nm"]["uncertainty"]["standard"] == 0
    for cell in record["observations"].values():
        assert cell["uncertainty"]["source"] == u["source"]
        assert all(cell["uncertainty"][key] is None for key in ("distribution", "coverage_factor", "confidence", "lower", "upper"))


@pytest.mark.parametrize("amount", [0, -1, float("nan"), float("inf"), 1e200, 1e-200, True, ".5", None])
def test_invalid_amount_never_mutates_records_or_audit(service, conditions, measurements, amount):
    eid = service.add_record(conditions, measurements)
    before = service.project.snapshot(), service.project.history()
    with pytest.raises(ValidationError):
        service.set_measurement_uncertainty([eid], SIO2, amount)
    assert (service.project.snapshot(), service.project.history()) == before


def test_invalid_selection_stale_preview_deleted_record_and_write_failure_are_atomic(service, conditions, measurements, monkeypatch):
    p = service.project
    ids = [service.add_record(conditions, measurements) for _ in range(3)]
    service.delete_records([ids[2]])
    before, audit, history_size = p.snapshot(), p.history(), len(service._undo)
    for selected, names in (([], SIO2), ([True], SIO2), (["1"], SIO2), ([ids[0], 999], SIO2),
                            ([ids[0], ids[2]], SIO2), (ids[:2], []), (ids[:2], ["sio2_loss_nm"]), (ids[:2], ["invalid"])):
        with pytest.raises(ValidationError): service.set_measurement_uncertainty(selected, names, .5)
        assert (p.snapshot(), p.history(), len(service._undo)) == (before, audit, history_size)
    with pytest.raises(StaleVersionError):
        service.set_measurement_uncertainty(ids[:2], SIO2, .5, expected_revision=p.revision - 1)
    log = p.log
    def fail_second(entity, eid, old, new):
        if eid == ids[1]: raise RuntimeError("模拟第二条写入失败")
        log(entity, eid, old, new)
    monkeypatch.setattr(p, "log", fail_second)
    with pytest.raises(RuntimeError, match="模拟第二条"):
        service.set_measurement_uncertainty(ids[:2], SIO2, .5)
    assert (p.snapshot(), p.history(), len(service._undo)) == (before, audit, history_size)


def test_noop_does_not_add_revision_or_history_and_preview_is_read_only(service, conditions, measurements):
    eid = service.add_record(conditions, measurements)
    service.set_measurement_uncertainty([eid], SIO2, .5)
    p = service.project
    before, audit, history_size = p.snapshot(), p.history(), len(service._undo)
    for only_unknown in (False, True):
        assert service.set_measurement_uncertainty([eid], SIO2, .5, only_unknown=only_unknown)["changed_records"] == 0
    records = p.experiments(); original = copy.deepcopy(records)
    plan = plan_standard_uncertainty(p.template, records, SIO2, .2)
    assert len(plan.changes) == 1 and records == original
    assert (p.snapshot(), p.history(), len(service._undo)) == (before, audit, history_size)


def test_save_and_reopen_preserves_bulk_errors(service, conditions, measurements):
    eid = service.add_record(conditions, measurements)
    path = service.project.path
    with ProjectSession(path) as session:
        editor = PlannerService(session)
        editor.set_measurement_uncertainty([eid], SIO2, .3)
        assert session.dirty
        with Project(path) as disk:
            assert disk.experiment(eid)["observations"][SIO2[0]]["uncertainty"]["amount"] is None
        session.save()
        assert not session.dirty
    with Project(path) as reopened:
        assert reopened.experiment(eid)["observations"][SIO2[0]]["uncertainty"]["amount"] == .3
        assert reopened.experiment(eid)["derived"]["sio2_loss_nm"]["uncertainty"]["standard"] == pytest.approx(math.sqrt(2) * .3)


def test_bulk_rejects_non_numeric_measurements(service, conditions):
    data = service.project.template.data
    data["measurements"].append({"name": "comment", "value_type": "text", "unit": "1"})
    template = Template(data)
    with pytest.raises(ValidationError, match="数值型"):
        plan_standard_uncertainty(template, [], ["comment"], 1.)


@pytest.mark.model
@pytest.mark.parametrize("preset", ["gp_rbf_v1", "gp_matern25_v1"])
def test_fill_unknown_allows_real_gp_and_smaller_error_increases_trust(tmp_path, preset):
    template = Template({"schema_version": 2, "template_version": 1, "name": "合成可信度验证",
        "parameters": [{"name": "x", "unit": "1", "bounds": [0, 1]}],
        "measurements": [{"name": "y", "unit": "nm", "is_response": True}],
        "derived_metrics": [], "objectives": [{"metric": "y", "direction": "maximize"}],
        "optimization": {"mode": "single"}, "ratio_policy": {"mode": "remove"}})
    with Project.create(tmp_path / "gp.sqlite", "合成数据", template) as p:
        service = PlannerService(p)
        a = service.add_record({"x": .5}, {"y": 10.})
        b = service.add_record({"x": .5}, {"y": 14.})
        service.set_measurement_uncertainty([a], ["y"], .2)
        with pytest.raises(CapabilityError, match="混合已知/未知") as caught:
            fit_models(template, p.experiments(), preset)
        assert "误差已知的实验：1；误差未知的实验：2" in str(caught.value)
        assert "统一设置误差" in str(caught.value)
        service.set_measurement_uncertainty([a, b], ["y"], 1., only_unknown=True,
                                            trusted_experiment_ids=[a], trusted_factor=.2)
        model, encoder, _, _, _ = fit_models(template, p.experiments(), preset)
        first_prediction = model.posterior(encoder.encode([{"x": .5}])).mean.item()
        assert math.isfinite(first_prediction) and abs(first_prediction - 10.) < .5
        service.set_measurement_uncertainty([a, b], ["y"], 1.)
        service.set_measurement_uncertainty([b], ["y"], .2)
        model, encoder, _, _, _ = fit_models(template, p.experiments(), preset)
        second_prediction = model.posterior(encoder.encode([{"x": .5}])).mean.item()
        assert abs(second_prediction - 14.) < .5
        assert second_prediction > first_prediction
        assert torch.isfinite(model.posterior(encoder.encode([{"x": .5}])).variance).all()
        assert [r["observations"]["y"]["value"] for r in p.experiments()] == [10., 14.]


def test_relative_setting_one_action_preserves_smaller_and_other_known_errors(service, conditions, measurements):
    p = service.project
    ids = [service.add_record(conditions, measurements, note="原实验备注") for _ in range(4)]
    service.set_measurement_uncertainty([ids[0]], SIO2, 1.)
    service.set_measurement_uncertainty([ids[1]], SIO2, .1)
    service.set_measurement_uncertainty([ids[2]], SIO2, .3)
    before, revision = p.experiments(), p.revision
    result = service.set_measurement_uncertainty(ids, SIO2, 1., only_unknown=True,
        trusted_experiment_ids=ids[:2], trusted_factor=.5, reason="按复测稳定性作的假设", expected_revision=revision)
    after = p.experiments()
    assert result == {"changed_records": 2, "changed_cells": 4, "replaced_known": 2, "skipped_known": 4, "skipped_missing": 0}
    assert p.revision == revision + 1
    assert [r["observations"][SIO2[0]]["uncertainty"]["amount"] for r in after] == [.5, .1, .3, 1.]
    assert after[1] == before[1] and after[2] == before[2]
    for i in (0, 3):
        assert after[i]["note"] == "原实验备注"
        cell = after[i]["observations"][SIO2[0]]
        assert "误差设定假设" in cell["note"] and "复测稳定性" in cell["note"]
        assert cell["uncertainty"]["source"] is None
        assert after[i]["derived"]["sio2_loss_nm"]["uncertainty"]["standard"] == pytest.approx(math.sqrt(2) * cell["uncertainty"]["amount"])
    assert "基准 1 × 0.5" in after[0]["observations"][SIO2[0]]["note"]
    service.undo(); assert p.experiments() == before
    service.redo(); assert p.experiments() == after
    revision = p.revision
    assert service.set_measurement_uncertainty(ids, SIO2, 1., only_unknown=True,
        trusted_experiment_ids=ids[:2], trusted_factor=.5, reason="重复点击不追加备注")["changed_cells"] == 0
    assert p.experiments() == after and p.revision == revision


@pytest.mark.parametrize("factor,ids", [(0, [1]), (1, [1]), (-.1, [1]), (float("nan"), [1]),
    (float("inf"), [1]), (True, [1]), (.5, []), (.5, [999]), (.5, [True]), (None, [1])])
def test_invalid_relative_plan_is_atomic(service, conditions, measurements, factor, ids):
    eid = service.add_record(conditions, measurements)
    before = service.project.snapshot(), service.project.history()
    with pytest.raises(ValidationError):
        service.set_measurement_uncertainty([eid], SIO2, 1., trusted_experiment_ids=ids, trusted_factor=factor)
    assert (service.project.snapshot(), service.project.history()) == before


def test_relative_plan_preview_notes_save_and_scope(service, conditions, measurements):
    ids = [service.add_record(conditions, {name: {"value": value, "note": "原测量备注"} for name, value in measurements.items()}) for _ in range(2)]
    p = service.project
    before = p.snapshot()
    plan = plan_standard_uncertainty(p.template, p.experiments(), SIO2, 2., only_unknown=True,
                                    trusted_experiment_ids=[ids[0]], trusted_factor=.25, reason="假设")
    assert p.snapshot() == before
    assert [(d["experiment_id"], d["before"], d["after"], d["role"]) for d in plan.details] == [(1, None, .5, "高可信"), (1, None, .5, "高可信"), (2, None, 2., "基准"), (2, None, 2., "基准")]
    with ProjectSession(p.path) as session:
        s = PlannerService(session)
        s.set_measurement_uncertainty(ids, SIO2, 2., only_unknown=True,
                                      trusted_experiment_ids=[ids[0]], trusted_factor=.25, reason="假设")
        assert session.dirty
        session.save()
    with Project(p.path) as reopened:
        for i, value in zip(ids, [.5, 2.]):
            cell = reopened.experiment(i)["observations"][SIO2[0]]
            assert cell["uncertainty"]["amount"] == value
            assert cell["note"].startswith("原测量备注\n误差设定假设")
            assert reopened.experiment(i)["observations"]["sin_initial_nm"] == before["experiments"][i-1]["observations"]["sin_initial_nm"]


def test_select_measurements_for_nested_response_and_custom_names(template):
    assert raw_measurement_names(template, "sio2_loss_nm") == set(SIO2)
    assert raw_measurement_names(template, "selectivity") == {f["name"] for f in template.measurements}
    assert raw_measurement_names(template, "cl2_sccm") == set()
    data = template.data
    data["derived_metrics"].append({"name": "twice_loss", "expression": "sio2_loss_nm * 2", "unit": "nm"})
    assert raw_measurement_names(Template(data), "twice_loss") == set(SIO2)
