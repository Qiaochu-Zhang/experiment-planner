import copy
import json

import pytest
from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidget

from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.help import HelpDialog, attach_help, help_path
from experiment_planner.ui.template_editor import TemplateEditor
from experiment_planner.ui.tree_editor import JsonTreeEditor
from experiment_planner.ui.window import RecordDialog

pytestmark=pytest.mark.gui


@pytest.fixture
def app():
    instance=QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


def test_form_updates_precision_priors_goals_and_roundtrips_database(app,service):
    editor=TemplateEditor(service.project.template)
    editor.bulk_digits.setValue(0);editor.apply_digits()
    editor.model.setCurrentIndex(editor.model.findData("bayesian_linear_v1"))
    editor.add_prior({"input":"etch_time_s","response":"sio2_loss_nm","relation":"linear","coefficient":.2,"strength":2,"source":"界面测试依据"})
    editor.objective_rows[0][5].setValue(2)
    editor.ratio.setCurrentIndex(editor.ratio.findData("remove"))
    editor.optimization.setCurrentIndex(editor.optimization.findData("weighted"))
    editor.save()
    assert editor.result()==QDialog.DialogCode.Accepted
    service.update_template(editor.result_template)
    with Project(service.project.path) as reopened:
        assert all(p["execution_rounding"]["digits"]==0 for p in reopened.template.parameters)
        assert reopened.template.data["knowledge_priors"][0]["coefficient"]==.2
        assert reopened.template.data["optimization"]["weights"]==[2,1]
        assert reopened.template.data["objectives"][0]["transform"]=="identity"
    editor.close()


def test_apply_new_goals_keeps_legacy_metric_and_requires_explicit_save(app,legacy_template):
    before=copy.deepcopy(legacy_template.data)
    editor=TemplateEditor(legacy_template,section="objectives")
    editor.new_goals()
    assert legacy_template.data==before
    editor.save()
    data=editor.result_template.data
    assert {m["name"] for m in data["derived_metrics"]}>={"selectivity_abs","selectivity"}
    assert data["objectives"][0]["transform"]=="identity"
    assert data["objectives"][2]["metric"]=="selectivity"
    assert data["ratio_policy"]["original_metric"]=="selectivity"
    editor.close()


def test_tree_preserves_unknown_properties_and_nested_null_bool_types(app,template):
    original=copy.deepcopy(template.data)
    original["custom"]={"nested":[None,False,1,1.25,"中文",{"a":True}]}
    editor=JsonTreeEditor(original)
    assert editor.data()==original
    root=editor.tree.topLevelItem(0)
    parameter_group=next(root.child(i) for i in range(root.childCount()) if root.child(i).data(0,Qt.ItemDataRole.UserRole)=="parameters")
    parameter=parameter_group.child(0)
    label=next(parameter.child(i) for i in range(parameter.childCount()) if parameter.child(i).data(0,Qt.ItemDataRole.UserRole)=="label")
    label.setData(1,Qt.ItemDataRole.UserRole,"新的中文名称")
    changed=Template(editor.data())
    assert changed.parameters[0]["label"]=="新的中文名称"
    assert changed.data["custom"]==original["custom"]
    editor.close()


def test_help_hover_has_clickable_blue_link_and_offline_target(app,monkeypatch):
    import experiment_planner.ui.help as help_module
    assert help_path().is_file()
    owner=QDialog();label=QLabel("探索强度",owner);attach_help(label,"exploration_strength")
    owner.show();app.processEvents()
    called=[];monkeypatch.setattr(help_module,"show_help",lambda key,parent:called.append(key))
    event=QHelpEvent(QEvent.Type.ToolTip,QPoint(2,2),label.mapToGlobal(QPoint(2,2)))
    QApplication.sendEvent(label,event)
    popup=label._help_handler.popup
    assert popup.isVisible()
    content=popup.findChild(QLabel)
    assert "color:#1565c0" in content.text() and "href='details'" in content.text()
    content.linkActivated.emit("details")
    assert called==["exploration_strength"]
    detailed=HelpDialog("exploration_count")
    assert detailed.topics.currentItem().text()=="专门探索名额"
    assert detailed.browser.textCursor().block().text()=="专门探索名额"
    assert "扣除复测" in detailed.browser.toPlainText()
    detailed.close();popup.close();owner.close()


def test_desktop_favorites_persist_defaults_and_duplicate_record_input(app,tmp_path,conditions,measurements):
    window=PythonWindow();window.set_project(Project.create(tmp_path/"界面.sqlite","界面测试"))
    assert window.navigation.count()==2
    def choose_favorites():
        dialog=QApplication.activeModalWidget()
        choices=dialog.findChild(QListWidget)
        for i in range(choices.count()):
            if choices.item(i).data(Qt.ItemDataRole.UserRole)=="backup":choices.item(i).setCheckState(Qt.CheckState.Checked)
        dialog.accept()
    QTimer.singleShot(0,choose_favorites);window.customize_favorites()
    assert "backup" in window.preferences.value("favorites")
    for remaining in (90.,89.):
        dialog=RecordDialog(window.require_project().template)
        for name,(field,_) in dialog.inputs.items():field.setText(str(conditions[name]))
        for name,widgets in dialog.cells.items():widgets[0].setText(str(remaining if name=="sio2_remaining_nm" else measurements[name]))
        dialog.validate_accept();assert dialog.result()==QDialog.DialogCode.Accepted
        window.service.add_record(**dialog.values());dialog.close()
    window.refresh()
    assert window.table.rowCount()==2
    rows=window.require_project().experiments()
    assert rows[0]["actual"]==rows[1]["actual"]
    assert rows[0]["derived"]["sio2_loss_nm"]["value"]!=rows[1]["derived"]["sio2_loss_nm"]["value"]
    window.exploration_strength.setValue(1.25);window.exploration_count.setValue(2)
    window.save_batch_defaults()
    assert window.batch_request().exploration_count==2
    path=window.require_project().path;window.close()
    restored=PythonWindow();restored.set_project(Project(path))
    assert restored.exploration_strength.value()==1.25 and restored.exploration_count.value()==2
    assert "backup" in restored.favorite_ids
    restored.table.selectRow(0);restored.copy_conditions()
    assert json.loads(restored.conditions.toPlainText())==conditions
    restored.close()
