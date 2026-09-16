import csv
import json
import pytest
from experiment_planner.storage.project import Project
from experiment_planner.domain.errors import ValidationError, StaleVersionError
from experiment_planner.io.exchange import preview_import, export_records


def test_revision_backup_and_isolation(service, conditions, measurements, tmp_path):
    p = service.project
    eid = service.add_record(conditions,measurements,note="模拟备注",field_notes={"cl2_sccm":"测试"})
    old_version = p.revision
    service.revise_record(eid,{**conditions,"cl2_sccm":40},{**measurements,"sio2_remaining_nm":105},note="更正")
    assert p.experiment(eid)["derived"]["sio2_loss_nm"]["value"] == -5
    assert len(p.history()) == 2
    assert json.loads(p.history()[1]["old_payload"])["derived"]["sio2_loss_nm"]["value"] == 10
    with pytest.raises(StaleVersionError):
        with p.transaction(old_version): p.bump()
    backup = tmp_path/"备份 空格.sqlite"
    p.backup(backup)
    with Project(backup) as restored:
        assert restored.experiments() == p.experiments()
        assert restored.revision == p.revision
    with Project.create(tmp_path/"second.sqlite","另一个项目") as other:
        assert other.experiments() == []


def test_partial_and_ratio(service, conditions):
    eid = service.add_record(conditions,{"sio2_initial_nm":100,"sio2_remaining_nm":90},status="partial")
    e = service.project.experiment(eid)
    assert e["derived"]["sio2_loss_nm"]["value"] == 10
    assert e["derived"]["sin_loss_nm"]["value"] is None


def test_versioned_formula_recompute(service, conditions, measurements):
    p = service.project
    service.add_record(conditions,measurements)
    metrics = p.template.data["derived_metrics"].copy()
    metrics[0] = {**metrics[0],"expression":"sio2_remaining_nm - sio2_initial_nm"}
    service.update_template(p.template.revised(derived_metrics=metrics))
    assert p.experiments()[0]["derived"]["sio2_loss_nm"]["value"] == -10
    assert p.template.data["template_version"] == 2


@pytest.mark.parametrize("extension",["csv","xlsx"])
def test_import_preview_export_dedup(service, conditions, measurements, tmp_path, extension):
    service.add_record(conditions, measurements,note="中文备注")
    path = tmp_path/f"实验.{extension}"
    export_records(service.project,path)
    with Project.create(tmp_path/f"import_{extension}.sqlite","导入") as other:
        from experiment_planner.application.service import PlannerService
        target = PlannerService(other)
        preview = preview_import(target,path)
        assert preview.errors == []
        assert other.experiments() == []
        assert len(preview.commit(target)) == 1
        assert preview_import(target,path).commit(target) == []
        assert other.experiments()[0]["note"] == "中文备注"


def test_import_error_atomic(service, tmp_path):
    path = tmp_path/"invalid.csv"
    path.write_text("cl2_sccm\nwrong\n",encoding="utf-8")
    preview = preview_import(service,path)
    assert preview.errors[0]["row"] == 2
    with pytest.raises(ValidationError): preview.commit(service)
    assert service.project.experiments() == []


def test_missing_file_not_empty_project(tmp_path):
    with pytest.raises(ValidationError): Project(tmp_path/"missing.sqlite")


def test_multiple_connections_see_new_template(service,conditions,measurements):
    p=service.project
    with Project(p.path) as second:
        from experiment_planner.application.service import PlannerService
        reader=PlannerService(second)
        new=p.template.revised(ratio_policy={**p.template.data["ratio_policy"],"mode":"remove"})
        service.update_template(new)
        assert second.template.data["template_version"]==2
        eid=reader.add_record(conditions,measurements)
        assert p.experiment(eid)["template_version"]==2


def test_stale_import_and_conflicting_external_id(service,conditions,measurements):
    p=service.project
    rows=[{"conditions":conditions,"observations":measurements,"external_id":"external-1"}]
    first=service.import_records(rows,p.revision)
    assert len(first)==1
    rows[0]["observations"]={**measurements,"sin_remaining_nm":95.}
    with pytest.raises(ValidationError):service.import_records(rows,p.revision)
    assert len(p.experiments())==1
    with pytest.raises(StaleVersionError):service.import_records(rows,0)
