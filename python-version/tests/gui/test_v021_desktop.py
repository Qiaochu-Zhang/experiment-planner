import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QCursor, QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidget, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem

from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.help import HelpFilter, attach_help

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("selected,confirm", [([0], True), ([0, 2], True), ([0, 2], False)])
def test_mouse_selection_and_delete_confirmation(qt_application, tmp_path, conditions, measurements, selected, confirm):
    window = PythonWindow()
    window.set_project(Project.create(tmp_path / "selection.sqlite", "多选删除"))
    for remaining in (90., 89., 88.):
        window.service.add_record(conditions, {**measurements, "sio2_remaining_nm": remaining})
    window.refresh(); window.go_to(0); window.show(); qt_application.processEvents()
    for index, row in enumerate(selected):
        QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier if index else Qt.KeyboardModifier.NoModifier,
                         window.table.visualItemRect(window.table.item(row, 0)).center())
    assert sorted(index.row() for index in window.table.selectionModel().selectedRows()) == selected
    revision = window.require_project().revision
    def answer():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        assert str(len(selected)) in dialog.text()
        assert dialog.defaultButton() == dialog.button(QMessageBox.StandardButton.Cancel)
        QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.Cancel), Qt.MouseButton.LeftButton)
    QTimer.singleShot(0, answer)
    delete = next(b for b in window.findChildren(QPushButton) if b.text() == "删除选中实验")
    QTest.mouseClick(delete, Qt.MouseButton.LeftButton)
    expected = [i + 1 for i in range(3) if not confirm or i not in selected]
    assert [e["id"] for e in window.require_project().experiments()] == expected
    assert window.table.rowCount() == len(expected)
    assert window.require_project().revision == revision + int(confirm)
    window.close()


def test_import_is_default_and_upgrade_preserves_other_favorites(qt_application):
    settings = QSettings("ExperimentPlanner", "Desktop")
    settings.clear()
    fresh = PythonWindow()
    assert "import" in fresh.favorite_ids
    fresh.close()
    settings.clear(); settings.setValue("favorites", ["precision", "priors", "objectives", "backup"]); settings.sync()
    upgraded = PythonWindow()
    assert set(upgraded.favorite_ids) == {"precision", "priors", "objectives", "backup", "import"}
    def unpin():
        dialog = QApplication.activeModalWidget()
        choices = dialog.findChild(QListWidget)
        for i in range(choices.count()):
            if choices.item(i).data(Qt.ItemDataRole.UserRole) == "import":
                choices.item(i).setCheckState(Qt.CheckState.Unchecked)
        dialog.accept()
    QTimer.singleShot(0, unpin); upgraded.customize_favorites(); upgraded.close()
    reopened = PythonWindow()
    assert "import" not in reopened.favorite_ids and "backup" in reopened.favorite_ids
    reopened.close()


def hover(widget, local):
    QCursor.setPos(widget.mapToGlobal(local))
    QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, local, widget.mapToGlobal(local)))


def test_help_disappears_after_one_second_but_popup_remains_clickable(qt_application, monkeypatch):
    import experiment_planner.ui.help as help_module
    owner = QDialog(); owner.resize(700, 400)
    label = QLabel("探索强度", owner); label.setGeometry(20, 20, 100, 30)
    attach_help(label, "exploration_strength")
    owner.show(); qt_application.processEvents()
    hover(label, QPoint(5, 5))
    popup = label._help_handler.popup
    away = owner.mapToGlobal(QPoint(600, 350))
    QCursor.setPos(away); QApplication.sendEvent(label, QEvent(QEvent.Type.Leave))
    QTest.qWait(700)
    assert popup.isVisible()
    QCursor.setPos(popup.mapToGlobal(popup.rect().center()))
    QTest.qWait(1100)
    assert popup.isVisible() and not popup.timer.isActive()
    called = []; monkeypatch.setattr(help_module, "show_help", lambda key, parent: called.append(key))
    popup.findChild(QLabel).linkActivated.emit("details")
    assert called == ["exploration_strength"] and not popup.isVisible()
    hover(label, QPoint(5, 5)); popup = label._help_handler.popup
    QCursor.setPos(away); QApplication.sendEvent(label, QEvent(QEvent.Type.Leave))
    QTest.qWait(600)
    QCursor.setPos(label.mapToGlobal(QPoint(5, 5)))
    QTest.qWait(1100)
    assert popup.isVisible() and not popup.timer.isActive()
    QCursor.setPos(away); QApplication.sendEvent(label, QEvent(QEvent.Type.Leave))
    QTest.qWait(700); assert popup.isVisible()
    QTest.qWait(450); assert not popup.isVisible()
    assert not popup.timer.isActive() and not popup.tracker.isActive()
    owner.close()


def test_header_help_closes_when_pointer_moves_to_another_column(qt_application):
    table = QTableWidget(1, 2); table.resize(600, 250)
    for index, key in enumerate(("cl2_sccm", "rf_w")):
        item = QTableWidgetItem(key); item.setData(Qt.ItemDataRole.UserRole, key)
        table.setHorizontalHeaderItem(index, item); table.setColumnWidth(index, 250)
    header = table.horizontalHeader(); source = header.viewport()
    handler = HelpFilter(table); source.installEventFilter(handler)
    table.show(); qt_application.processEvents()
    hover(source, QPoint(5, 5)); popup = handler.popup
    QCursor.setPos(source.mapToGlobal(QPoint(480, 5)))
    QTest.qWait(1150)
    assert not popup.isVisible()
    table.close()
