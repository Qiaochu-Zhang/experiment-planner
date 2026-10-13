"""Exercise the real bulk editor, including previews and modal application."""
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.measurement_uncertainty import MeasurementUncertaintyDialog

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("amount", ["", "abc", "0", "-1", "nan", "inf", "1e200", "1e-200"])
@pytest.mark.parametrize("kind", ["std", "bounds"])
def test_invalid_amount_disables_apply(qt_application, service, conditions, measurements, amount, kind):
    service.add_record(conditions, measurements)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments())
    dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
    dialog.amount.setText(amount)
    assert not dialog.apply_button.isEnabled()
    assert ("界限" if kind == "bounds" else "1σ") in dialog.preview.text()
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
@pytest.mark.parametrize("kind", ["std", "bounds"])
def test_real_button_dialog_apply_cancel_and_undo(qt_application, tmp_path, conditions, measurements, scope, accept, kind):
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
        dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
        dialog.amount.setText(".5")
        target = dialog.apply_button if accept else dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, answer)
    QTest.mouseClick(window.uncertainty_button, Qt.MouseButton.LeftButton)
    assert inspected == [True, "应用设置"]
    assert p.revision == revision + int(accept)
    if accept:
        assert p.experiment(1)["observations"]["sio2_initial_nm"]["uncertainty"]["kind"] == kind
        assert p.experiment(1)["observations"]["sio2_initial_nm"]["uncertainty"]["distribution"] == ("uniform" if kind == "bounds" else None)
        assert p.experiment(1)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == .5
        assert p.experiment(2)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == (.5 if scope == "all" else None)
        assert "已更新" in window.statusBar().currentMessage()
        window.history_step(False)
        assert p.experiments() == before
    else:
        assert p.experiments() == before
    window.close()


def test_relative_mode_selects_all_targets_and_previews_values_and_reason(qt_application, service, conditions, measurements):
    ids = [service.add_record(conditions, measurements) for _ in range(3)]
    service.set_measurement_uncertainty([ids[1]], ["sio2_initial_nm", "sio2_remaining_nm"], .1)
    before = service.project.snapshot()
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments(), ids[:2])
    dialog.mode.setCurrentIndex(dialog.mode.findData("relative"))
    dialog.choose_related_fields(next(i for i in range(dialog.quick_fields.count()) if dialog.quick_fields.itemData(i) == ["sio2_initial_nm", "sio2_remaining_nm"]))
    dialog.amount.setText("1")
    dialog.factor.setValue(.5)
    dialog.reason.setText("试用更可信的复测记录")
    assert dialog.only_unknown.isChecked() and not dialog.scope.isEnabled()
    assert dialog.target_records() == service.project.experiments()
    assert "= 0.5" in dialog.trusted_hint.text()
    assert "修改 2 条实验、4 项" in dialog.preview.text()
    assert dialog.details.rowCount() == 4
    assert dialog.details.item(0, 4).text() == "0.5"
    assert dialog.details.item(2, 4).text() == "1"
    assert "试用更可信" in dialog.details.item(0, 0).toolTip()
    assert service.project.snapshot() == before
    for i in range(dialog.trusted_records.count()):
        dialog.trusted_records.item(i).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.apply_button.isEnabled() and "高可信实验" in dialog.preview.text()
    dialog.mode.setCurrentIndex(0)
    assert dialog.scope.isEnabled() and dialog.values()["trusted_factor"] is None
    dialog.close()


def test_bounds_preview_type_switch_and_relative_labels(qt_application, service, conditions, measurements):
    eid = service.add_record(conditions, measurements)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments(), [eid])
    assert dialog.kind.currentData() == "std"
    dialog.kind.setCurrentIndex(dialog.kind.findData("bounds")); dialog.amount.setText("2")
    assert dialog.values()["kind"] == "bounds" and dialog.values()["amount"] == 2.
    assert "半宽 a" in dialog.amount_label.text() and "均匀分布" in dialog.kind_hint.text()
    assert "±2" in dialog.preview.text() and "1.1547" in dialog.preview.text()
    assert "±2" in dialog.details.item(0, 4).text()
    dialog.mode.setCurrentIndex(dialog.mode.findData("relative"))
    dialog.factor.setValue(.5)
    assert "基准界限" in dialog.factor_label.text() and "= 1" in dialog.trusted_hint.text()
    assert "±1" in dialog.details.item(0, 4).text()
    dialog.kind.setCurrentIndex(dialog.kind.findData("std"))
    assert dialog.amount.text() == "2" and "1σ" in dialog.amount_label.text()
    assert dialog.details.item(0, 4).text() == "1"
    dialog.close()


def test_read_common_bound_never_infers_it_from_sigma(qt_application, service, conditions, measurements):
    eid = service.add_record(conditions, measurements)
    names = [f["name"] for f in service.project.template.measurements]
    service.set_measurement_uncertainty([eid], names, .3)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments())
    dialog.kind.setCurrentIndex(dialog.kind.findData("bounds"))
    dialog.load_current_amount()
    assert dialog.amount.text() == "" and "不会由 1σ 反推" in dialog.read_feedback.text()
    service.set_measurement_uncertainty([eid], names, 2., kind="bounds")
    dialog.records = service.project.experiments()
    dialog.load_current_amount()
    assert dialog.amount.text() == "2.0" and not dialog.apply_button.isEnabled()
    dialog.kind.setCurrentIndex(dialog.kind.findData("std"))
    dialog.load_current_amount()
    assert float(dialog.amount.text()) == pytest.approx(2/3**.5)
    dialog.close()


def test_read_common_value_and_related_measurement_shortcuts(qt_application, service, conditions, measurements):
    eid = service.add_record(conditions, measurements)
    service.set_measurement_uncertainty([eid], ["sio2_initial_nm", "sio2_remaining_nm"], .3)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments())
    index = next(i for i in range(dialog.quick_fields.count()) if dialog.quick_fields.itemData(i) == ["sio2_initial_nm", "sio2_remaining_nm"])
    dialog.choose_related_fields(index)
    dialog.load_current_amount()
    assert dialog.amount.text() == "0.3"
    assert not dialog.apply_button.isEnabled()  # Already identical: no accidental rewrite.
    dialog.choose_related_fields(next(i for i in range(dialog.quick_fields.count()) if dialog.quick_fields.itemText(i).startswith("SiN")))
    dialog.load_current_amount()
    assert "没有唯一" in dialog.read_feedback.text()
    assert dialog.amount.text() == "0.3"
    dialog.close()


def test_relative_dialog_applies_both_groups_in_one_revision(qt_application, tmp_path, conditions, measurements):
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / "relative.sqlite", "相对误差"))
    for _ in range(2): window.service.add_record(conditions, measurements)
    window.refresh(); window.go_to(0); window.show(); qt_application.processEvents()
    window.table.selectRow(0)
    p = window.require_project()
    before, revision = p.experiments(), p.revision
    seen = []
    def apply():
        dialog = QApplication.activeModalWidget()
        seen.append(isinstance(dialog, MeasurementUncertaintyDialog))
        if not seen[-1]: dialog.reject(); return
        dialog.mode.setCurrentIndex(dialog.mode.findData("relative"))
        dialog.amount.setText("1")
        dialog.factor.setValue(.5)
        dialog.reason.setText("按复测比较")
        QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, apply)
    QTest.mouseClick(window.uncertainty_button, Qt.MouseButton.LeftButton)
    assert seen == [True] and p.revision == revision + 1
    assert p.experiment(1)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == .5
    assert p.experiment(2)["observations"]["sio2_initial_nm"]["uncertainty"]["amount"] == 1.
    assert "复测比较" in p.experiment(1)["observations"]["sio2_initial_nm"]["note"]
    window.history_step(False)
    assert p.experiments() == before
    window.close()


@pytest.mark.parametrize("width,height,scale", [(680, 560, 1.), (840, 760, 1.5)])
def test_relative_editor_scrolls_but_summary_and_apply_stay_visible(qt_application, service, conditions, measurements, width, height, scale):
    eid = service.add_record(conditions, measurements)
    dialog = MeasurementUncertaintyDialog(service.project.template, service.project.experiments(), [eid])
    font = QFont(dialog.font())
    font.setPointSizeF(max(9., font.pointSizeF()) * scale)
    dialog.setFont(font)
    dialog.mode.setCurrentIndex(1)
    dialog.amount.setText("1")
    dialog.show_details.setChecked(True)
    dialog.resize(width, height); dialog.show(); qt_application.processEvents()
    assert dialog.height() == height
    assert dialog.rect().contains(dialog.apply_button.mapTo(dialog, dialog.apply_button.rect().center()))
    assert dialog.rect().contains(dialog.preview.mapTo(dialog, dialog.preview.rect().center()))
    scroll = dialog.findChild(QScrollArea)
    scroll.ensureWidgetVisible(dialog.factor); qt_application.processEvents()
    assert scroll.viewport().rect().contains(dialog.factor.mapTo(scroll.viewport(), dialog.factor.rect().center()))
    scroll.ensureWidgetVisible(dialog.details); qt_application.processEvents()
    assert scroll.viewport().rect().contains(dialog.details.mapTo(scroll.viewport(), dialog.details.rect().center()))
    dialog.close()
