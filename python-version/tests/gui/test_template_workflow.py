import copy

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QCursor, QHelpEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QFileDialog, QLabel, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from experiment_planner.application.template_editing import blank_template
from experiment_planner.domain.template import Template
from experiment_planner.io.template_excel import read_template_excel
from experiment_planner.storage.project import Project
from experiment_planner.storage.session import ProjectSession
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.field_editor import FieldDialog, FieldsEditor
from experiment_planner.ui.help import attach_help
from experiment_planner.ui.interaction import install_wheel_filter
from experiment_planner.ui.template_editor import TemplateEditor

pytestmark = pytest.mark.gui


def choose_unsaved(choice):
    def click():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox) and '是否保存' in dialog.text()
        dialog.button(choice).click()
    QTimer.singleShot(0, click)


def test_shift_ctrl_select_copy_cross_section_paste_and_batch_delete(qt_application, template):
    editor = FieldsEditor(template.data); editor.show(); qt_application.processEvents()
    table = editor.tables[0]
    for row, modifiers in ((0, Qt.KeyboardModifier.NoModifier), (2, Qt.KeyboardModifier.ShiftModifier), (4, Qt.KeyboardModifier.ControlModifier)):
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifiers, table.visualItemRect(table.item(row, 0)).center())
    assert editor.selected_rows() == [0, 1, 2, 4]
    QTest.keyClick(table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    editor.tabs.setCurrentIndex(1); editor.tables[1].setFocus()
    before = len(editor.data['measurements'])
    QTest.keyClick(editor.tables[1], Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    pasted = editor.data['measurements'][before:]
    assert len(pasted) == 4 and all('bounds' not in f and 'execution_rounding' not in f for f in pasted)
    assert all('measured_at' not in f and 'is_response' not in f for f in pasted)
    editor.tabs.setCurrentIndex(0)
    def confirm(): QApplication.activeModalWidget().button(QMessageBox.StandardButton.Yes).click()
    QTimer.singleShot(0, confirm); editor.remove_field()
    assert len(editor.data['parameters']) == len(template.parameters) - 4
    editor.accept(); editor.close()


def test_field_help_reads_note_and_new_popup_hides_previous(qt_application):
    dialog = FieldDialog('parameters'); dialog.show(); qt_application.processEvents()
    def hover(widget):
        point = QPoint(5, 5); QCursor.setPos(widget.mapToGlobal(point))
        QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, point, widget.mapToGlobal(point)))
    hover(dialog.unit); previous = dialog.unit._help_handler.popup
    assert previous.isVisible() and '单位可直接输入' in previous.findChild(QLabel).text()
    hover(dialog.model_input)
    assert not previous.isVisible() and dialog.model_input._help_handler.popup.isVisible()
    dialog.close()
    data = blank_template(); data['parameters'] = [{'name': 'speed', 'unit': '1', 'note': '由用户自由编辑的说明'}]
    editor = FieldsEditor(data); editor.show(); qt_application.processEvents()
    point = editor.tables[0].visualItemRect(editor.tables[0].item(0, 0)).center()
    viewport = editor.tables[0].viewport(); QCursor.setPos(viewport.mapToGlobal(point))
    QApplication.sendEvent(viewport, QHelpEvent(QEvent.Type.ToolTip, point, viewport.mapToGlobal(point)))
    assert '由用户自由编辑的说明' in viewport._help_handler.popup.findChild(QLabel).text()
    editor.close()


def test_wheel_scrolls_container_without_changing_dropdown_or_digits(qt_application):
    install_wheel_filter()
    scroll = QScrollArea(); scroll.resize(400, 220); scroll.setWidgetResizable(True)
    content = QWidget(); layout = QVBoxLayout(content)
    combo = QComboBox(); combo.addItems(['第一项', '第二项', '第三项']); layout.addWidget(combo)
    from PySide6.QtWidgets import QSpinBox
    spin = QSpinBox(); spin.setValue(4); layout.addWidget(spin)
    content.setMinimumHeight(1000); layout.addStretch(); scroll.setWidget(content); scroll.show(); qt_application.processEvents()
    for widget in (combo, spin):
        widget.setFocus()
        local = widget.rect().center()
        event = QWheelEvent(QPointF(local), QPointF(widget.mapToGlobal(local)), QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, event)
    assert combo.currentIndex() == 0 and spin.value() == 4
    assert scroll.verticalScrollBar().value() > 0
    scroll.close()


def test_display_bulk_is_separate_from_execution_and_skips_text(qt_application, template):
    data = template.data
    data['parameters'].append({'name': 'sample', 'value_type': 'text', 'use_as_model_input': False})
    data['measurements'].append({'name': 'comment', 'value_type': 'text', 'is_response': False, 'model_base': False})
    editor = TemplateEditor(Template(data))
    before = editor.collect()
    editor.bulk_display.setCurrentIndex(editor.bulk_display.findData(3)); editor.apply_display_digits('parameters')
    inputs = editor.collect()
    assert all(f.get('display_digits') == 3 for f in inputs['parameters'][:-1])
    assert inputs['parameters'][-1]['display_digits'] is None
    assert [f.get('display_digits') for f in inputs['measurements']] == [f.get('display_digits') for f in before['measurements']]
    assert [f['execution_rounding'] for f in inputs['parameters']] == [f['execution_rounding'] for f in before['parameters']]
    editor.bulk_display.setCurrentIndex(editor.bulk_display.findData(2)); editor.apply_display_digits('responses')
    editor.save(); result = editor.result_template
    assert all(f.get('display_digits') == 2 for f in result.measurements[:-1] + result.metrics)
    assert result.measurements[-1].get('display_digits') is None
    editor.close()


@pytest.mark.parametrize('choice', [QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel])
def test_template_x_save_discard_or_continue(qt_application, template, choice):
    original = copy.deepcopy(template.data); editor = TemplateEditor(template); editor.show()
    editor.name.setText('修改后的模板')
    choose_unsaved(choice); closed = editor.close()
    if choice == QMessageBox.StandardButton.Cancel:
        assert not closed and editor.isVisible()
        choose_unsaved(QMessageBox.StandardButton.Discard); editor.close()
    elif choice == QMessageBox.StandardButton.Save:
        assert editor.result() == QDialog.DialogCode.Accepted and editor.result_template.data['name'] == '修改后的模板'
    else:
        assert editor.result() == QDialog.DialogCode.Rejected and editor.data == original
    assert template.data == original


def test_fields_x_discard_restores_original_and_field_save_validates(qt_application):
    editor = FieldsEditor(blank_template()); original = copy.deepcopy(editor.data); editor.show()
    editor.data['parameters'].append({'name': 'x'})
    choose_unsaved(QMessageBox.StandardButton.Discard); editor.close()
    assert editor.data == original
    field = FieldDialog('parameters'); field.show(); field.name.setText('sample')
    field.kind.setCurrentIndex(field.kind.findData('text')); field.unit.setCurrentText('自定义单位')
    choose_unsaved(QMessageBox.StandardButton.Save); field.close()
    assert field.result() == QDialog.DialogCode.Accepted
    assert field.value()['value_type'] == 'text' and not field.value()['use_as_model_input']


@pytest.mark.parametrize('choice', [QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel])
def test_project_x_and_explicit_save_preserve_last_saved_state(qt_application, tmp_path, conditions, measurements, choice):
    file = tmp_path / '保存.sqlite'
    with Project.create(file, '保存测试'): pass
    window = PythonWindow(); window.set_project(ProjectSession(file)); window.show()
    window.service.add_record(conditions, measurements)
    window.save_project_button.click()
    window.service.add_record(conditions, {**measurements, 'sin_remaining_nm': 97})
    choose_unsaved(choice); closed = window.close()
    if choice == QMessageBox.StandardButton.Cancel:
        assert not closed and window.isVisible()
        choose_unsaved(QMessageBox.StandardButton.Discard); window.close()
    with Project(file) as disk: assert len(disk.experiments()) == (2 if choice == QMessageBox.StandardButton.Save else 1)


def test_excel_editor_export_then_import_and_save(qt_application, tmp_path, template, monkeypatch):
    file = tmp_path / '模板.xlsx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(file), ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(file), ''))
    editor = TemplateEditor(template); editor.export_excel()
    assert read_template_excel(file)['parameters'][0]['name'] == template.parameters[0]['name']
    editor.name.setText('会被导入替换的草稿'); editor.import_excel(); editor.save()
    assert editor.result_template.data['name'] == template.data['name']
    editor.close()


def test_replacing_open_same_name_project_captures_just_saved_version(qt_application, tmp_path, conditions, measurements, monkeypatch):
    file = tmp_path / '同名.sqlite'
    with Project.create(file, '旧项目'): pass
    window = PythonWindow(); window.set_project(ProjectSession(file)); window.show()
    window.service.add_record(conditions, measurements)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(file), ''))
    choose_unsaved(QMessageBox.StandardButton.Save); window.create_project()
    assert window.require_project().dirty and not window.require_project().experiments()
    window.save_project()
    window.close()
    with Project(file) as disk: assert not disk.experiments() and disk.name == '同名'


def test_save_as_overwrites_target_and_keeps_source(qt_application, tmp_path, conditions, measurements, monkeypatch):
    source, target = tmp_path / 'source.sqlite', tmp_path / 'target.sqlite'
    with Project.create(source, '来源'): pass
    with Project.create(target, '旧目标'): pass
    window = PythonWindow(); window.set_project(ProjectSession(source)); window.show()
    window.service.add_record(conditions, measurements)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(target), ''))
    window.save_project_as(); window.close()
    with Project(source) as disk: assert not disk.experiments()
    with Project(target) as disk: assert len(disk.experiments()) == 1
