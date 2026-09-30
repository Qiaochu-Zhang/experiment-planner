import csv
import json

import pytest

from experiment_planner.domain.errors import StaleVersionError, ValidationError
from experiment_planner.engine.ax_bridge import rebuild
from experiment_planner.engine.models import fit_models
from experiment_planner.io.exchange import export_records
from experiment_planner.storage.project import Project


def test_delete_is_atomic_and_rejects_stale_confirmation(service, conditions, measurements):
    p = service.project
    eid = service.add_record(conditions, measurements)
    before = p.snapshot(), p.history()
    assert p.db.execute("PRAGMA user_version").fetchone()[0] == 1
    for invalid in ([], [eid, 999], [True], [str(eid)]):
        with pytest.raises(ValidationError): service.delete_records(invalid)
        assert (p.snapshot(), p.history()) == before
        assert p.db.execute("PRAGMA user_version").fetchone()[0] == 1
    with pytest.raises(StaleVersionError): service.delete_records([eid], p.revision - 1)
    assert (p.snapshot(), p.history()) == before
    assert service.delete_records([eid, eid], p.revision) == [eid]
    assert p.db.execute("PRAGMA user_version").fetchone()[0] == 2
    assert p.revision == before[0]["revision"] + 1
    with pytest.raises(ValidationError, match="已删除"): p.experiment(eid)
    with pytest.raises(ValidationError, match="已删除"): service.revise_record(eid, conditions, measurements)


def test_delete_preserves_audit_batches_and_reuses_ids_after_backup(service, conditions, measurements, tmp_path):
    p = service.project
    first = service.add_record(conditions, measurements)
    batch = {"revision": p.revision, "request": {"n": 1}, "candidates": [{"conditions": conditions, "repeat_of": first}]}
    _, pending = service.commit_batch(batch)
    original = p.experiment(first)
    batches = p.batches()
    defaults = {**p.template.data.get("batch_defaults", {}), "baseline_experiment_id": first, "repeat_ids": [first]}
    service.update_template(p.template.revised(batch_defaults=defaults))
    version = p.template.data["template_version"]
    stale_batch = {**batch, "revision": p.revision}
    service.delete_records([first, *pending], p.revision)
    assert p.experiments() == p.snapshot()["experiments"] == []
    assert p.batches() == batches
    assert p.template.data["template_version"] == version + 1
    assert p.template.data["batch_defaults"]["baseline_experiment_id"] is None
    assert p.template.data["batch_defaults"]["repeat_ids"] == []
    with pytest.raises(StaleVersionError): service.commit_batch(stale_batch)
    events = [e for e in p.history() if e["entity"] == "experiment_delete"]
    assert len(events) == 2
    assert json.loads(events[0]["old_payload"])["observations"] == original["observations"]
    assert json.loads(events[0]["new_payload"])["deleted_at"]
    replacement = service.add_record(conditions, measurements)
    assert replacement == first
    p.backup(tmp_path / "deleted.sqlite")
    with Project(tmp_path / "deleted.sqlite") as restored:
        assert restored.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert restored.snapshot() == p.snapshot()
        assert restored.history() == p.history()
        assert restored.batches() == batches
        assert restored.experiment(first)["record_uid"] != original["record_uid"]


def test_failure_during_delete_rolls_back_records_audit_and_format(service, conditions, measurements, monkeypatch):
    p = service.project
    ids = [service.add_record(conditions, measurements) for _ in range(2)]
    before = p.snapshot(), p.history()
    real_log = p.log
    def failing_log(entity, eid, old, new):
        if eid == ids[1]: raise RuntimeError("模拟写入失败")
        real_log(entity, eid, old, new)
    monkeypatch.setattr(p, "log", failing_log)
    with pytest.raises(RuntimeError, match="模拟写入失败"): service.delete_records(ids)
    assert (p.snapshot(), p.history()) == before
    assert p.db.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.parametrize("external_id", [None, "run-1"])
def test_deleted_import_can_be_imported_again_reusing_id(service, conditions, measurements, external_id):
    p = service.project
    row = {"conditions": conditions, "observations": measurements, "external_id": external_id}
    [first] = service.import_records([row], p.revision)
    service.delete_records([first])
    [second] = service.import_records([row], p.revision)
    assert second == first
    assert service.import_records([row], p.revision) == []
    assert [e["id"] for e in p.experiments()] == [second]


@pytest.mark.model
def test_training_ax_and_exports_exclude_deleted_data(service, conditions, measurements, tmp_path):
    p = service.project
    for flow in (20., 30., 40.):
        service.add_record({**conditions, "cl2_sccm": flow}, measurements)
    service.delete_records([2])
    _, _, _, datasets, _ = fit_models(p.template, p.snapshot()["experiments"], "bayesian_linear_v1")
    assert all(d["count"] == 2 for d in datasets.values())
    assert all([c["cl2_sccm"] for c in d["conditions"]] == [20., 40.] for d in datasets.values())
    _, mapping = rebuild(p.template, p.experiments())
    assert set(mapping) == {"1", "3"}
    export_records(p, tmp_path / "active.csv")
    with (tmp_path / "active.csv").open(encoding="utf-8-sig", newline="") as source:
        assert [r["experiment_id"] for r in csv.DictReader(source)] == ["1", "3"]
    export_records(p, tmp_path / "active.json")
    assert [r["id"] for r in json.loads((tmp_path / "active.json").read_text())["experiments"]] == [1, 3]
