"""Exercise the real bulk editor, including previews and modal application."""
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.measurement_uncertainty import MeasurementUncertaintyDialog

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("amount", ["", "abc", "0", "-1", "nan", "inf", "1e200", "1e-200"])
def test_invalid_amount_disables_apply(qt_application, service, conditions, measurements, amount):
    service.add_record(conditions, measurements)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments())
    dialog.amount.setText(amount)
    assert not dialog.apply_button.isEnabled()
    assert "1σ" in dialog.preview.text()
    dialog.close()


def test_preview_scope_fields_only_unknown_and_no_mutation(qt_application, service, conditions, measurements):
    ids = [service.add_record(conditions, measurements) for _ in range(2)]
    service.set_measurement_uncertainty([ids[0]], ["sio2_initial_nm"], .2)
    before = service.project.snapshot()
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments(), [ids[0]])
    dialog.amount.setText("0.5")
    assert "修改 1 条实验、4 项" in dialog.preview.text() and "覆盖已知误差 1 项" in dialog.preview.text()
    assert "nm" in dialog.preview.text()
    dialog.only_unknown.setChecked(True)
    assert "修改 1 条实验、3 项" in dialog.preview.text()
    dialog.scope.setCurrentIndex(dialog.scope.findData("all"))
    assert "修改 2 条实验、7 项" in dialog.preview.text()
    dialog.select_fields(False)
    assert not dialog.apply_button.isEnabled()
    dialog.fields.item(0).setCheckState(Qt.CheckState.Checked)
    assert "修改 1 条实验、1 项" in dialog.preview.text()
    assert dialog.values()["measurement_names"] == ["sio2_initial_nm"]
    assert service.project.snapshot() == before
    dialog.close()


def test_numeric_fields_units_and_empty_project(qt_application, template):
    data = template.data
    data["measurements"].extend([{"name": "comment", "value_type": "text", "unit": "1"}, {"name": "mass", "unit": "kg"}])
    dialog = MeasurementUncertaintyDialog(Template(data), [])
    assert dialog.fields.count() == 5
    dialog.amount.setText("1")
    assert "单位不同" in dialog.preview.text()
    assert not dialog.apply_button.isEnabled()
    dialog.close()


@pytest.mark.parametrize("scope,accept", [("selected", True), ("all", True), ("all", False)])
def test_real_button_dialog_apply_cancel_and_undo(qt_application, tmp_path, conditions, measurements, scope, accept):
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / "bulk.sqlite", "统一误差测试"))
    for _ in range(2): window.service.add_record(conditions, measurements)
    window.refresh(); window.go_to(0); window.show(); qt_application.processEvents()
    window.table.selectRow(0)
    p = window.require_project()
    before = p.experiments(); revision = p.revision
    inspected = []
    def answer():
        dialog = QApplication.activeModalWidget()
        inspected.append(isinstance(dialog, MeasurementUncertaintyDialog))
        if not inspected[-1]:
            dialog.reject(); return
        inspected.append(dialog.apply_button.text())
        dialog.scope.setCurrentIndex(dialog.scope.findData(scope))
        dialog.amount.setText(".5")
        target = dialog.apply_button if accept else dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, answer)
    QTest.mouseClick(window.uncertainty_button, Qt.MouseButton.LeftButton)
    assert inspected == [True, "应用设置"]
    assert p.revision == revision + int(accept)
    if accept:
        assert p.experiment(1)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == .5
        assert p.experiment(2)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == (.5 if scope == "all" else None)
        assert "已更新" in window.statusBar().currentMessage()
        window.history_step(False)
        assert p.experiments() == before
    else:
        assert p.experiments() == before
    window.close()
