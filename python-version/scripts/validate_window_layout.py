"""Capture prediction layouts after copy, resize, maximize and font changes."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from experiment_planner import __version__
from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.interaction import remove_wheel_filter
from experiment_planner.ui.template_editor import TemplateEditor


def check_labels(form):
    for label in form.findChildren(QLabel):
        assert label.height() >= label.heightForWidth(label.width()), label.text()
        assert form.rect().contains(label.geometry()), label.text()
    for editor in form.editors.values():
        assert editor.height() >= editor.minimumSizeHint().height()
        assert form.rect().contains(editor.geometry())


def main():
    evidence = ROOT / f'docs/evidence/v{__version__}'
    evidence.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    results = []
    with tempfile.TemporaryDirectory() as folder:
        data = Template.builtin().data
        for p in data['parameters']: p['label'] += '：实验条件完整名称'
        template = Template(data)
        window = PythonWindow()
        window.set_project(Project.create(Path(folder) / '窗口检查.sqlite', '合成窗口检查', template))
        values = {p['name']: sum(p['bounds']) / 2 for p in template.parameters}
        window.service.add_record(values, {'sio2_initial_nm': 100, 'sio2_remaining_nm': 90, 'sin_initial_nm': 100, 'sin_remaining_nm': 99})
        window.refresh(); window.table.setCurrentCell(0, 0); window.copy_conditions()
        window.go_to(3); window.show()
        for state in ('normal', 'small', 'maximized', 'fullscreen', 'restored'):
            if state == 'normal': window.resize(1280, 820)
            elif state == 'small': window.resize(1024, 650)
            elif state == 'maximized': window.showMaximized()
            elif state == 'fullscreen': window.showFullScreen()
            else: window.showNormal(); window.resize(1100, 720)
            app.processEvents(); check_labels(window.conditions)
            assert window.conditions.values() == values
            image = f'prediction-{state}.png'
            window.grab().save(str(evidence / image))
            results.append({'state': state, 'size': window.size().toTuple(), 'labels': 'passed', 'copied_values': 'preserved', 'image': image})
        original = QFont(app.font())
        font = QFont(original); font.setPointSizeF(original.pointSizeF() * 1.5); app.setFont(font)
        for widget in window.findChildren(QWidget): widget.setFont(font)
        app.processEvents(); check_labels(window.conditions)
        assert all(label.font().pointSizeF() == font.pointSizeF() for label in window.conditions.findChildren(QLabel))
        window.grab().save(str(evidence / 'prediction-font150.png'))
        editor = TemplateEditor(template); editor.show(); app.processEvents()
        for widget in editor.findChildren(QWidget): widget.setFont(font)
        app.processEvents()
        for table in (editor.precision, editor.response_display):
            for row in range(table.rowCount()):
                for column in range(table.columnCount()):
                    widget = table.cellWidget(row, column)
                    if widget: assert widget.height() >= widget.sizeHint().height()
        editor.grab().save(str(evidence / 'template-font150.png'))
        editor.close(); window.close(); app.setFont(original)
    app.clipboard().clear()
    for widget in app.topLevelWidgets(): widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    remove_wheel_filter()
    result = {'version': __version__, 'python': sys.version, 'window_states': results, 'font150_prediction_and_template': 'passed'}
    (evidence / 'layout-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
