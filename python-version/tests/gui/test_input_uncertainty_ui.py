import copy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from experiment_planner.domain.template import Template
from experiment_planner.ui.template_editor import TemplateEditor

pytestmark = pytest.mark.gui


def test_opt_in_selected_input_and_disable_preserves_settings(qt_application, template):
    editor = TemplateEditor(template, section="input_uncertainty")
    page = editor.input_uncertainty
    editor.show(); qt_application.processEvents()
    assert editor.tabs.tabText(editor.tabs.currentIndex()) == "输入不确定度"
    assert not page.enabled.isChecked()
    selected, kind, amount, note = page.rows["etch_time_s"]
    assert not selected.isChecked() and not selected.isEnabled()
    QTest.mouseClick(page.enabled, Qt.MouseButton.LeftButton, pos=QPoint(8, page.enabled.height()//2))
    QTest.mouseClick(selected, Qt.MouseButton.LeftButton, pos=QPoint(8, selected.height()//2))
    assert page.enabled.isChecked() and selected.isChecked()
    amount.setText("0.5"); note.setText("合成测试假设")
    editor.save()
    saved = editor.result_template
    assert saved.data["input_uncertainty"] == {"enabled": True, "samples": 16}
    assert [p["name"] for p in saved.parameters if p.get("input_uncertainty", {}).get("enabled")] == ["etch_time_s"]
    assert saved.parameters[-1]["input_uncertainty"]["amount"] == .5
    second = TemplateEditor(saved, section="input_uncertainty")
    second.input_uncertainty.enabled.setChecked(False)
    second.save()
    assert not second.result_template.data["input_uncertainty"]["enabled"]
    assert second.result_template.parameters[-1]["input_uncertainty"]["amount"] == .5
    third = TemplateEditor(second.result_template, section="input_uncertainty")
    assert not third.input_uncertainty.enabled.isChecked()
    assert third.input_uncertainty.rows["etch_time_s"][2].text() == "0.5"
    third.accept()


@pytest.mark.parametrize("raw", ["", "abc", "0", "-1", "nan", "inf"])
def test_invalid_enabled_setting_has_readable_error(qt_application, template, monkeypatch, raw):
    editor = TemplateEditor(template, section="input_uncertainty")
    editor.input_uncertainty.enabled.setChecked(True)
    selected, _, amount, _ = editor.input_uncertainty.rows["etch_time_s"]
    selected.setChecked(True); amount.setText(raw)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    editor.save()
    assert editor.result_template is None and errors
    assert "etch_time_s" in errors[0]
    editor.accept()


def test_no_selection_is_reported_and_unsupported_fields_are_disabled(qt_application, template, monkeypatch):
    data = copy.deepcopy(template.data)
    data["parameters"].append({"name": "batch_label", "value_type": "text"})
    editor = TemplateEditor(Template(data), section="input_uncertainty")
    editor.input_uncertainty.enabled.setChecked(True)
    assert not editor.input_uncertainty.rows["batch_label"][0].isEnabled()
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    editor.save()
    assert editor.result_template is None and "至少勾选" in errors[0]
    editor.accept()


def test_rebuilding_template_pages_keeps_input_settings_and_small_window_usable(qt_application, template):
    editor = TemplateEditor(template, section="input_uncertainty")
    page = editor.input_uncertainty
    page.enabled.setChecked(True)
    page.rows["cl2_sccm"][0].setChecked(True)
    page.rows["cl2_sccm"][1].setCurrentIndex(1)
    page.rows["cl2_sccm"][2].setText("1.2")
    editor.data = editor.collect()
    editor.build_pages(); editor.tabs.setCurrentIndex(3)
    page = editor.input_uncertainty
    assert page.rows["cl2_sccm"][1].currentData() == "bounds"
    assert page.rows["cl2_sccm"][2].text() == "1.2"
    font = QFont(editor.font()); font.setPointSizeF(font.pointSizeF()*1.5)
    editor.setFont(font); editor.resize(850, 650); editor.show(); qt_application.processEvents()
    assert page.enabled.isVisible() and editor.buttons.isVisible()
    assert editor.buttons.geometry().bottom() <= editor.height()
    editor.accept()
