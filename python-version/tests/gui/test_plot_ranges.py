import pytest

from experiment_planner.domain.errors import ValidationError
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.plot_ranges import PlotRangesForm


pytestmark = pytest.mark.gui


def test_range_form_defaults_reset_and_variable_changes(qt_application, template):
    form = PlotRangesForm()
    form.set_template(template)
    form.set_variables("cl2_sccm")
    assert form.values() == {"cl2_sccm": [0, 100]}
    form.editors["cl2_sccm"][0].setText("12.123456789")
    form.set_variables("cl2_sccm,rf_w")
    assert form.values()["cl2_sccm"] == [12.123456789, 100]
    assert form.values()["rf_w"] == [0, 100]
    form.editors["rf_w"][0].setText("不是数值")
    with pytest.raises(ValidationError, match="上下限需要数值"):
        form.values()
    form.reset()
    assert form.values() == {"cl2_sccm": [0, 100], "rf_w": [0, 100]}
    form.set_variables("rf_w")
    assert list(form.values()) == ["rf_w"]
    form.clear()
    assert form.values() == {}
    form.close()


def test_desktop_passes_ranges_and_rejects_invalid_before_worker(qt_application, tmp_path, conditions, monkeypatch):
    from experiment_planner.worker import process
    from PySide6.QtWidgets import QFileDialog

    captured = []
    class Task:
        def __init__(self, project, request, operation):
            captured.append((request, operation))
        def cancel(self): pass

    monkeypatch.setattr(process, "CalculationTask", Task)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(tmp_path / "trend.png"), ""))
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / "ranges.sqlite", "绘图范围"))
    try:
        window.conditions.set_values(conditions)
        window.plot_variables.setText("cl2_sccm,rf_w")
        for name, bounds in {"cl2_sccm": [12, 28], "rf_w": [20, 40]}.items():
            for editor, value in zip(window.plot_ranges.editors[name], bounds):
                editor.setText(str(value))
        before = window.require_project().snapshot()
        window.start_analysis()
        window.analysis_timer.stop()
        request, operation = captured[0]
        assert operation == "analyze"
        assert request["plot_ranges"] == {"cl2_sccm": [12, 28], "rf_w": [20, 40]}
        assert request["conditions"] == [conditions]
        assert window.require_project().snapshot() == before
        window.cancel_analysis()
        window.plot_ranges.editors["rf_w"][0].setText("60")
        with pytest.raises(ValidationError, match="下限必须小于上限"):
            window.start_analysis()
        assert len(captured) == 1
        window.close_project()
        assert not window.plot_ranges.editors
        assert not window.plot_variables.text()
    finally:
        window.close()
