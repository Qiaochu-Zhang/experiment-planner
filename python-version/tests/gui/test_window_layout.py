import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QLabel, QScrollArea, QWidget

from experiment_planner.domain.template import Template
from experiment_planner.storage.project import Project
from experiment_planner.ui.conditions import ConditionsForm
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.template_editor import TemplateEditor


pytestmark = pytest.mark.gui


def long_template():
    data = Template.builtin().data
    for index, field in enumerate(data['parameters']):
        field['label'] = f'实验条件 {index + 1}：需要完整显示的较长名称与说明'
    for index in range(20):
        data['parameters'].append({'name': f'extra_{index}', 'label': f'额外实验条件 {index + 1} 的完整名称', 'bounds': [0, 1], 'unit': '1'})
    data['knowledge_priors'] = [{'enabled': False, 'input': 'cl2_sccm', 'response': 'sio2_loss_nm', 'relation': 'independent', 'source': '界面布局测试'}]
    return Template(data)


def check_condition_geometry(form):
    labels = form.findChildren(QLabel)
    for label in labels:
        needed = label.heightForWidth(label.width())
        assert label.height() >= needed, (label.text(), label.size(), needed)
        assert form.rect().contains(label.geometry()), (label.text(), label.geometry(), form.size())
    for editor in form.editors.values():
        assert editor.height() >= editor.minimumSizeHint().height()
        assert form.rect().contains(editor.geometry())
    for index, label in enumerate(labels):
        for other in labels[index + 1:]: assert not label.geometry().intersects(other.geometry())
        for editor in form.editors.values(): assert not label.geometry().intersects(editor.geometry())


@pytest.mark.parametrize('width,height', [(420, 300), (640, 480), (900, 650)])
def test_conditions_wrap_and_scroll_without_clipping(qt_application, width, height):
    form = ConditionsForm(); form.set_template(long_template())
    scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(form)
    scroll.resize(width, height); scroll.show(); qt_application.processEvents()
    check_condition_geometry(form)
    assert scroll.verticalScrollBar().maximum() > 0
    last = list(form.editors.values())[-1]
    scroll.ensureWidgetVisible(last); qt_application.processEvents()
    position = last.mapTo(scroll.viewport(), last.rect().center())
    assert scroll.viewport().rect().contains(position)
    scroll.close()


@pytest.mark.parametrize('state', ['normal', 'small', 'maximized', 'fullscreen', 'restored'])
def test_prediction_layout_survives_window_states_and_large_plot(qt_application, tmp_path, state, measurements):
    window = PythonWindow()
    template = long_template()
    window.set_project(Project.create(tmp_path / 'layout.sqlite', '窗口检查', template))
    values = {p['name']: sum(p['bounds']) / 2 for p in template.parameters}
    window.service.add_record(values, measurements); window.refresh()
    window.table.setCurrentCell(0, 0); window.copy_conditions()
    assert window.conditions.values() == values
    window.go_to(3); window.show(); qt_application.processEvents()
    if state == 'normal': window.resize(1280, 820)
    elif state == 'small': window.resize(1024, 650)
    elif state == 'maximized': window.showMaximized()
    elif state == 'fullscreen': window.showFullScreen()
    else:
        window.showMaximized(); qt_application.processEvents(); window.showNormal(); window.resize(1100, 720)
    image = QPixmap(900, 600); image.fill(Qt.GlobalColor.white); window.plot_image.setPixmap(image)
    qt_application.processEvents()
    if state == 'small': assert window.height() == 650
    check_condition_geometry(window.conditions)
    outer = window.tabs.widget(3)
    assert isinstance(outer, QScrollArea)
    inner = window.condition_scroll
    assert inner.verticalScrollBar().maximum() > 0
    outer.ensureWidgetVisible(inner); qt_application.processEvents()
    last = list(window.conditions.editors.values())[-1]
    inner.ensureWidgetVisible(last); qt_application.processEvents()
    assert inner.viewport().rect().contains(last.mapTo(inner.viewport(), last.rect().center()))
    outer.ensureWidgetVisible(window.plot_metric); qt_application.processEvents()
    assert outer.viewport().rect().contains(window.plot_metric.mapTo(outer.viewport(), window.plot_metric.rect().center()))
    outer.ensureWidgetVisible(window.analysis_output); qt_application.processEvents()
    assert outer.viewport().rect().contains(window.analysis_output.mapTo(outer.viewport(), window.analysis_output.rect().center()))
    window.close()


@pytest.mark.parametrize('scale', [1.0, 1.5, 2.0])
def test_larger_fonts_keep_prediction_and_template_controls_readable(qt_application, tmp_path, scale):
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / 'font.sqlite', '字体检查', long_template()))
    original = QFont(qt_application.font())
    font = QFont(original); font.setPointSizeF(original.pointSizeF() * scale)
    editor = None
    try:
        qt_application.setFont(font)
        # Existing styled Qt children can retain their resolved font when the
        # application font changes; explicitly scale them and verify it took.
        for widget in window.findChildren(QWidget): widget.setFont(font)
        window.go_to(3); window.show(); window.resize(1100, 720)
        editor = TemplateEditor(long_template()); editor.show()
        for widget in editor.findChildren(QWidget): widget.setFont(font)
        qt_application.processEvents()
        assert all(label.font().pointSizeF() == font.pointSizeF() for label in window.conditions.findChildren(QLabel))
        check_condition_geometry(window.conditions)
        for tab in range(editor.tabs.count()):
            editor.tabs.setCurrentIndex(tab); qt_application.processEvents()
            for table in (editor.precision, editor.response_display, editor.prior_table, editor.objective_table):
                if not table.isVisible(): continue
                for row in range(table.rowCount()):
                    for column in range(table.columnCount()):
                        cell = table.cellWidget(row, column)
                        if cell:
                            assert cell.height() >= cell.sizeHint().height(), (scale, row, column, cell.height(), cell.sizeHint())
        window.showMaximized(); qt_application.processEvents(); check_condition_geometry(window.conditions)
        window.showNormal(); qt_application.processEvents(); check_condition_geometry(window.conditions)
    finally:
        if editor: editor.close()
        window.close()
        qt_application.setFont(original); qt_application.processEvents()
