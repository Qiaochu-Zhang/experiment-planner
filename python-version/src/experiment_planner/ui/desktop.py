"""Desktop access to template revisions, restricted batches and local analysis."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLineEdit, QPlainTextEdit, QDialog, QDialogButtonBox, QFileDialog, QLabel,
)

from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.io.exchange import preview_import
from experiment_planner.ui.window import MainWindow, button


class PythonWindow(MainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("实验规划助手 · Python 源码版")
        self.summary.setText("新建或打开本地项目，录入实验后规划下一批条件。")
        self.analysis_task = None
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setInterval(200)
        self.analysis_timer.timeout.connect(self.poll_analysis)

        form = self.tabs.widget(1).layout()
        self.mode.addItem("基准 / 单 A / 单 B / AB 交叉布局", "cross")
        self.exact_two = QCheckBox("双变量模式恰好改变两项")
        self.cross_values = QLineEdit()
        self.cross_values.setPlaceholderText('例如 {"cl2_sccm": 20, "rf_w": 30}')
        self.repeat_baseline = QCheckBox("交叉布局包含基准复测（4 组；不选为 3 组）")
        self.repeat_baseline.setChecked(True)
        form.insertRow(8, "双变量限制", self.exact_two)
        form.insertRow(9, "交叉布局的两个新值 (JSON)", self.cross_values)
        form.insertRow(10, self.repeat_baseline)

        template_page = QWidget()
        layout = QVBoxLayout(template_page)
        label = QLabel("编辑模板的字段、公式、目标、精度、误差与先验；保存时校验并重算派生值。\n"
                       "更改已有项目的字段结构或范围时，请导出模板并从该模板新建项目。")
        label.setWordWrap(True)
        layout.addWidget(label)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        button("编辑项目模板", lambda: self.guard(self.edit_template), actions)
        button("查看修订历史", lambda: self.guard(self.show_history), actions)
        self.template_view = QPlainTextEdit()
        self.template_view.setReadOnly(True)
        layout.addWidget(self.template_view)
        self.tabs.addTab(template_page, "模板 / 公式 / 先验")

        analysis_page = QWidget()
        analysis_layout = QVBoxLayout(analysis_page)
        self.conditions = QPlainTextEdit()
        self.conditions.setPlaceholderText("完整输入条件 JSON；可从选中实验复制，再修改数值。")
        self.conditions.setMaximumHeight(170)
        button("从选中实验复制条件", lambda: self.guard(self.copy_conditions), analysis_layout)
        analysis_layout.addWidget(self.conditions)
        settings = QFormLayout()
        analysis_layout.addLayout(settings)
        self.plot_variables = QLineEdit()
        self.plot_variables.setPlaceholderText("cl2_sccm 或 cl2_sccm,rf_w；空白表示只预测")
        self.plot_metric = QLineEdit("sio2_loss_nm")
        settings.addRow("趋势图变量（1 或 2 项）", self.plot_variables)
        settings.addRow("趋势图响应/指标", self.plot_metric)
        self.analyze_button = QPushButton("按「下一批实验」所选模型预测 / 绘图")
        self.analyze_button.clicked.connect(lambda: self.guard(self.start_analysis))
        analysis_layout.addWidget(self.analyze_button)
        button("取消分析", self.cancel_analysis, analysis_layout)
        self.analysis_output = QPlainTextEdit()
        self.analysis_output.setReadOnly(True)
        analysis_layout.addWidget(self.analysis_output)
        self.plot_image = QLabel()
        self.plot_image.setAlignment(Qt.AlignCenter)
        analysis_layout.addWidget(self.plot_image)
        self.tabs.addTab(analysis_page, "预测 / 趋势图")

    def batch_request(self):
        request = super().batch_request()
        request.exact_two = self.exact_two.isChecked()
        request.repeat_baseline = self.repeat_baseline.isChecked()
        if request.mode == "cross":
            request.cross_values = json.loads(self.cross_values.text())
            if not isinstance(request.cross_values, dict):
                raise ValidationError("交叉布局需要两个字段及其新值组成的 JSON 对象")
        return request

    def refresh(self):
        super().refresh()
        if hasattr(self, "template_view"):
            self.template_view.setPlainText(json.dumps(self.require_project().template.data, ensure_ascii=False, indent=2))

    def close_project(self):
        super().close_project()
        for name in ("template_view", "conditions", "analysis_output", "plot_image"):
            if hasattr(self, name):
                getattr(self, name).clear()

    def edit_template(self):
        project = self.require_project()
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑项目模板（JSON）")
        dialog.resize(950, 720)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlainText(json.dumps(project.template.data, ensure_ascii=False, indent=2))
        layout.addWidget(editor)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(actions)

        def save():
            data = json.loads(editor.toPlainText())
            data["template_version"] = project.template.data["template_version"] + 1
            self.service.update_template(Template(data))
            self.refresh()
            dialog.accept()

        actions.accepted.connect(lambda: self.guard(save))
        actions.rejected.connect(dialog.reject)
        dialog.exec()

    def show_history(self):
        self.template_view.setPlainText(json.dumps(self.require_project().history(), ensure_ascii=False, indent=2))

    def copy_conditions(self):
        project = self.require_project()
        row = self.table.currentRow()
        if row < 0:
            raise ValidationError("请先在实验记录页选择一行")
        eid = int(self.table.item(row, 0).text())
        self.conditions.setPlainText(json.dumps(project.experiment(eid)["actual"], ensure_ascii=False, indent=2))

    def start_analysis(self):
        from experiment_planner.worker.process import CalculationTask
        project = self.require_project()
        condition = project.template.validate_conditions(json.loads(self.conditions.toPlainText()))
        request = {"conditions": [condition], "model": self.model.currentData()}
        variables = [v.strip() for v in self.plot_variables.text().split(",") if v.strip()]
        if variables:
            from experiment_planner.plots.trends import slice_conditions
            slice_conditions(project.template, condition, variables, points=15)
            path, _ = QFileDialog.getSaveFileName(self, "保存趋势图", "trend.png", "PNG (*.png)")
            if not path:
                return
            request.update(plot_path=path, variables=variables, metric=self.plot_metric.text().strip())
        self.analysis_task = CalculationTask(project, request, operation="analyze")
        self.analyze_button.setEnabled(False)
        self.analysis_output.setPlainText("正在本地拟合与预测；区间表示潜在响应，不包含未知的未来量测误差。")
        self.plot_image.clear()
        self.analysis_timer.start()

    def poll_analysis(self):
        if self.analysis_task is None:
            return
        result = self.analysis_task.poll()
        if result is None:
            return
        self.analysis_task = None
        self.analysis_timer.stop()
        self.analyze_button.setEnabled(True)
        if "error" in result:
            self.analysis_output.setPlainText(result["error"])
            return
        report = result["result"]
        message = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if report["revision"] != self.require_project().revision:
            message = "项目已更改：以下分析属于旧数据版本，请重新计算。\n" + message
        self.analysis_output.setPlainText(message)
        if report.get("plot_path"):
            pixmap = QPixmap(report["plot_path"])
            self.plot_image.setPixmap(pixmap.scaled(720, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def cancel_analysis(self):
        if getattr(self, "analysis_task", None):
            self.analysis_task.cancel()
            self.analysis_task = None
        if hasattr(self, "analysis_timer"):
            self.analysis_timer.stop()
            self.analyze_button.setEnabled(True)

    def cancel(self):
        self.cancel_analysis()
        super().cancel()

    def import_data(self):
        self.require_project()
        path, _ = QFileDialog.getOpenFileName(self, "选择历史记录", "", "表格 (*.csv *.xlsx)")
        if not path:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("字段映射与导入预览")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('可选表头映射，例如 {"氯气流量": "cl2_sccm"}；空对象使用模板名称自动匹配。'))
        mapping = QPlainTextEdit("{}")
        mapping.setMaximumHeight(100)
        layout.addWidget(mapping)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        layout.addWidget(output)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setEnabled(False)
        preview = None

        def refresh_preview():
            nonlocal preview
            preview = None
            actions.button(QDialogButtonBox.Save).setEnabled(False)
            aliases = json.loads(mapping.toPlainText())
            if not isinstance(aliases, dict):
                raise ValidationError("映射需要 JSON 对象")
            preview = preview_import(self.service, path, aliases)
            output.setPlainText(json.dumps({"errors": preview.errors, "records": preview.records}, ensure_ascii=False, indent=2))
            actions.button(QDialogButtonBox.Save).setEnabled(not preview.errors)

        def commit():
            if preview is None:
                raise ValidationError("请先预览")
            preview.commit(self.service)
            self.refresh()
            dialog.accept()

        mapping.textChanged.connect(lambda: actions.button(QDialogButtonBox.Save).setEnabled(False))
        button("校验并预览", lambda: self.guard(refresh_preview), layout)
        actions.accepted.connect(lambda: self.guard(commit))
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        self.guard(refresh_preview)
        dialog.exec()
