import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from experiment_planner.ui.window import MainWindow, RecordDialog
from experiment_planner.storage.project import Project

pytestmark=pytest.mark.gui


def test_minimal_window_records_restore(tmp_path, conditions, measurements):
    app=QApplication.instance() or QApplication([])
    window=MainWindow()
    from PySide6.QtGui import QFontMetrics
    assert QFontMetrics(app.font()).inFont('实')
    path=tmp_path/"中文 路径"/"project.sqlite"
    window.set_project(Project.create(path,"GUI 合成测试"))
    window.service.add_record(conditions,measurements)
    window.refresh();window.show();app.processEvents()
    assert window.table.rowCount()==1
    assert window.table.item(0,2).text()==str(conditions["cl2_sccm"])
    window.close_project();window.set_project(Project(path))
    assert window.table.rowCount()==1
    dialog=RecordDialog(window.service.project.template,window.service.project.experiments()[0])
    assert dialog.values()["observations"]["sio2_initial_nm"]["value"]=="100.0"
    dialog.close();window.close();app.processEvents()
