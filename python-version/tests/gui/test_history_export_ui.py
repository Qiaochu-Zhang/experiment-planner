import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.template_editor import TemplateEditor
from experiment_planner.ui.window import RecordDialog
from experiment_planner.ui.messages import analysis_text

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("shift", [False, True])
def test_keyboard_undo_redo_deleted_record(qt_application, tmp_path, conditions, measurements, shift):
    window = PythonWindow(); window.set_project(Project.create(tmp_path / "undo.sqlite", "撤销测试"))
    window.service.add_record(conditions, measurements)
    window.service.delete_records([1]); window.refresh(); window.go_to(0)
    window.show(); window.activateWindow(); window.table.setFocus(); qt_application.processEvents()
    modifiers = Qt.KeyboardModifier.ControlModifier
    if shift: modifiers |= Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(window.table, Qt.Key.Key_Z, modifiers)
    assert window.table.rowCount() == 1
    QTest.keyClick(window.table, Qt.Key.Key_Y, modifiers)
    assert window.table.rowCount() == 0
    window.close()


def test_text_undo_does_not_change_database(qt_application, tmp_path, conditions, measurements):
    window = PythonWindow(); window.set_project(Project.create(tmp_path / "text.sqlite", "文字撤销"))
    window.service.add_record(conditions, measurements)
    window.go_to(1); window.show(); window.activateWindow(); window.repeats.setFocus(); qt_application.processEvents()
    QTest.keyClicks(window.repeats, "123")
    QTest.keyClick(window.repeats, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert window.repeats.text() == ""
    assert len(window.require_project().experiments()) == 1
    QTest.keyClick(window.repeats, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert window.repeats.text() == "123"
    window.close()


def test_response_precision_saves_and_formats_prediction(qt_application, service, conditions, measurements):
    service.add_record(conditions, measurements)
    editor = TemplateEditor(service.project.template)
    for name, widget in editor.response_display_rows:
        if name in ("sio2_loss_nm", "sin_loss_nm", "selectivity"):
            widget.setCurrentIndex(widget.findData(2))
    editor.save(); service.update_template(editor.result_template)
    report = {"predictions": [{"sio2_loss_nm": {"quantiles": [1.234, 2.345, 3.456]},
        "raw_selectivity": {"quantiles": [1.234, 2.345, 3.456]}}]}
    text = analysis_text(report, service.project.template)
    assert "2.35" in text and "1.23" in text and "3.46" in text
    with Project(service.project.path) as reopened:
        assert all(f["display_digits"] == 2 for f in reopened.template.metrics)
    editor.close()


def test_template_fields_do_not_get_generic_popups(qt_application, tmp_path, conditions):
    window = PythonWindow(); window.set_project(Project.create(tmp_path / "help.sqlite", "变量帮助"))
    record = RecordDialog(window.require_project().template)
    for field, _ in record.inputs.values(): assert field.property("helpKey") is None and not field.toolTip()
    for field in window.conditions.editors.values(): assert field.property("helpKey") is None and not field.toolTip()
    window.refresh(); window.go_to(0); window.show(); qt_application.processEvents()
    header = window.table.horizontalHeader().viewport()
    QApplication.sendEvent(header, QHelpEvent(QEvent.Type.ToolTip, QPoint(200, 5), header.mapToGlobal(QPoint(200, 5))))
    assert window.header_help.popup is None
    record.close(); window.close()
