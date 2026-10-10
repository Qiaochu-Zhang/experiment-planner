"""Shared wheel and unsaved-change behavior for the desktop forms."""
import copy

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QAbstractSpinBox, QComboBox, QDialog, QMessageBox


def ask_save_changes(parent):
    box = QMessageBox(parent)
    box.setWindowTitle("保存变化")
    box.setText("有尚未保存的变化，是否保存？")
    box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
    for code, title in ((QMessageBox.StandardButton.Save, "保存"),
                        (QMessageBox.StandardButton.Discard, "不保存"),
                        (QMessageBox.StandardButton.Cancel, "继续编辑")):
        box.button(code).setText(title)
    box.setDefaultButton(QMessageBox.StandardButton.Save)
    return box.exec()


class DraftDialog(QDialog):
    """Capture the rendered initial state, so default values do not count as edits."""
    def track_changes(self, state, save, restore=None):
        self._draft_state = state
        self._draft_initial = copy.deepcopy(state())
        self._draft_save = save
        self._draft_restore = restore

    def reject(self):
        if self.result() != QDialog.DialogCode.Accepted and hasattr(self, "_draft_state"):
            try:
                changed = self._draft_state() != self._draft_initial
            except (ValueError, TypeError):
                changed = True
            if changed:
                choice = ask_save_changes(self)
                if choice == QMessageBox.StandardButton.Cancel:
                    return
                if choice == QMessageBox.StandardButton.Save:
                    self._draft_save()
                    return
                if self._draft_restore:
                    self._draft_restore()
        super().reject()


class WheelFilter(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            control = watched
            while control is not None and not isinstance(control, (QComboBox, QAbstractSpinBox)):
                control = control.parent()
            if control is not None:
                ancestor = control.parent()
                while ancestor is not None:
                    if isinstance(ancestor, QAbstractScrollArea) and ancestor.verticalScrollBar().maximum() > 0:
                        target = ancestor.viewport()
                        forwarded = QWheelEvent(QPointF(target.mapFromGlobal(event.globalPosition().toPoint())),
                            event.globalPosition(), event.pixelDelta(), event.angleDelta(), event.buttons(),
                            event.modifiers(), event.phase(), event.inverted(), event.source())
                        QApplication.sendEvent(target, forwarded)
                        break
                    ancestor = ancestor.parent()
                event.ignore()
                return True
        return False


def install_wheel_filter():
    app = QApplication.instance()
    if app is not None and not hasattr(app, "_planner_wheel_filter"):
        # Keep Python ownership only; parenting to QApplication as well can
        # destroy this wrapper twice during interpreter teardown.
        app._planner_wheel_filter = WheelFilter()
        app.installEventFilter(app._planner_wheel_filter)


def remove_wheel_filter():
    app = QApplication.instance()
    if app is not None and hasattr(app, "_planner_wheel_filter"):
        app.removeEventFilter(app._planner_wheel_filter)
        del app._planner_wheel_filter
