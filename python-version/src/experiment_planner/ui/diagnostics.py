"""Readable, copyable failure details independent of Qt's built-in translations."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)


class FailureDialog(QDialog):
    def __init__(self, message, diagnostic, parent=None, title="操作未完成", expanded=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 240)
        layout = QVBoxLayout(self)
        summary = QLabel(message)
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlainText(diagnostic or "未收到原始诊断。已收到的错误信息：\n" + message)
        self.details.setMinimumHeight(220)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.details_button = QPushButton("查看原始诊断")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.set_expanded)
        actions.addWidget(self.details_button)
        self.copy_button = QPushButton("复制原始诊断")
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.details.toPlainText()))
        actions.addWidget(self.copy_button)
        actions.addStretch()
        close_button = QPushButton("知道了")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        self.set_expanded(False)
        self.details_button.setChecked(expanded)

    def set_expanded(self, expanded):
        self.details.setVisible(expanded)
        self.details_button.setText("收起原始诊断" if expanded else "查看原始诊断")
        if expanded:
            self.resize(self.width(), max(self.height(), 480))


def show_failure_dialog(parent, message, diagnostic, title="操作未完成", expanded=False):
    dialog = FailureDialog(message, diagnostic, parent, title, expanded)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
