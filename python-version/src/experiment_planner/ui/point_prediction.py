"""Read-only copied conditions and tabular predictions for multiple experiments."""
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from experiment_planner.domain.errors import ValidationError
from experiment_planner.io.prediction_export import point_prediction_tables


class PointPredictionPanel(QWidget):
    copy_requested = Signal()
    predict_requested = Signal()
    cancel_requested = Signal()
    export_requested = Signal()
    details_requested = Signal()
    record_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.template = None
        self.points = []
        self.report = None
        self.report_template = None
        self.busy = False
        layout = QVBoxLayout(self)
        hint = QLabel("在“实验记录”中按 Ctrl 多选或 Shift 连选，再复制到这里。使用“下一批实验”所选模型和随机种子，"
                      "一次拟合并预测全部实验点；本页不绘图。计算本身不修改实验记录，可点击“记录到原实验”保存为回填评分的依据。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.model_hint = QLabel()
        self.model_hint.setWordWrap(True)
        layout.addWidget(self.model_hint)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.copy_button = QPushButton("从实验记录复制所选条件")
        self.copy_button.clicked.connect(lambda:self.copy_requested.emit())
        row.addWidget(self.copy_button)
        self.remove_button = QPushButton("移除所选点")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_button)
        self.clear_button = QPushButton("清空实验点")
        self.clear_button.clicked.connect(self.clear_points)
        row.addWidget(self.clear_button)
        self.count = QLabel()
        layout.addWidget(self.count)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(240)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.predict_button = QPushButton("按所选模型批量预测")
        self.predict_button.clicked.connect(lambda:self.predict_requested.emit())
        row.addWidget(self.predict_button)
        self.cancel_button = QPushButton("取消批量预测")
        self.cancel_button.clicked.connect(lambda:self.cancel_requested.emit())
        row.addWidget(self.cancel_button)
        self.export_button = QPushButton("导出批量预测 Excel")
        self.export_button.clicked.connect(lambda:self.export_requested.emit())
        row.addWidget(self.export_button)
        self.record_button = QPushButton("记录到原实验（用于回填评分）")
        self.record_button.clicked.connect(lambda:self.record_requested.emit())
        row.addWidget(self.record_button)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(120)
        layout.addWidget(self.output)
        self.details_button = QPushButton("批量预测技术详情")
        self.details_button.clicked.connect(lambda:self.details_requested.emit())
        layout.addWidget(self.details_button)
        self.clear_points()

    def set_template(self, template):
        self.template = template
        self.clear_points()

    def clear(self):
        self.template = None
        self.clear_points()

    def set_points(self, points):
        self.points = deepcopy(points)
        self.reset_result()
        self.output.setPlainText(f"已复制 {len(points)} 个实验点的完整条件。点击“按所选模型批量预测”计算。"
                                 "再次复制会替换当前列表；关闭或切换项目会清空本页，可在计算后记录到原实验以保留逐条预测。")

    def clear_points(self):
        self.points = []
        self.reset_result()
        self.output.setPlainText("请先从实验记录复制一个或多个实验点。")

    def remove_selected(self):
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        if not selected:
            return
        self.points = [point for index, point in enumerate(self.points) if index not in selected]
        self.reset_result()
        self.output.setPlainText("实验点列表已更新，请重新批量预测。")

    def reset_result(self):
        self.report = self.report_template = None
        rows = []
        for index, point in enumerate(self.points, 1):
            rows.append({"点序号": index, "来源实验编号（复制时）": point["source"]["experiment_id"],
                         **{f"条件：{f.get('label', f['name'])} [{f['name']}] ({f.get('unit', '1')})": point["conditions"][f["name"]]
                            for f in self.template.parameters}})
        self.show_rows(rows)
        self.update_controls()

    def show_rows(self, rows):
        headers = list(dict.fromkeys(key for row in rows for key in row))
        self.table.clear()
        self.table.setColumnCount(len(headers))
        labels = []
        for header in headers:
            if " / " in header:
                metric, statistic = header.rsplit(" / ", 1)
                labels.append(f"{statistic}\n{metric}")
            elif header.startswith("条件："):
                labels.append(header.replace(" [", "\n[", 1))
            else:
                labels.append(header)
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, header in enumerate(headers):
                value = row.get(header)
                text = "" if value is None else "是" if value is True else "否" if value is False else str(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(i, j, item)
        for column, header in enumerate(headers):
            self.table.horizontalHeaderItem(column).setToolTip(header)
            self.table.setColumnWidth(column, 90 if header == "点序号" else 190)
        self.table.resizeRowsToContents()
        self.count.setText(f"共 {len(rows)} 个实验点；每行对应一个来源实验，横向滚动可查看全部条件与预测结果。")

    def request(self, template):
        if not self.points:
            raise ValidationError("请先从实验记录复制一个或多个实验点")
        conditions = []
        for index, point in enumerate(self.points, 1):
            try:
                conditions.append(template.validate_conditions(point["conditions"], execution=False))
            except ValidationError as exc:
                raise ValidationError(f"预测点 {index}（来源实验 {point['source']['experiment_id']}）：{exc}") from exc
        return {"conditions": conditions, "source_experiments": deepcopy([p["source"] for p in self.points])}

    def set_busy(self, busy):
        self.busy = busy
        self.update_controls()

    def update_controls(self):
        self.copy_button.setEnabled(not self.busy)
        self.clear_button.setEnabled(bool(self.points) and not self.busy)
        self.remove_button.setEnabled(bool(self.points) and not self.busy)
        self.predict_button.setEnabled(bool(self.points) and not self.busy)
        self.cancel_button.setEnabled(self.busy)
        self.export_button.setEnabled(self.report is not None and not self.busy)
        self.details_button.setEnabled(self.report is not None)
        self.record_button.setEnabled(self.report is not None and not self.busy)

    def display_report(self, report, template, current_revision):
        rows, _ = point_prediction_tables(report, template)
        rows = [{key: value for key, value in row.items() if key not in ("来源记录唯一标识", "复制时数据版本")}
                for row in rows]
        self.report, self.report_template = report, template
        self.show_rows(rows)
        self.update_controls()
        self.mark_revision(current_revision)

    def mark_revision(self, current_revision):
        if self.report is None:
            return
        report = self.report
        message = (f"已完成 {len(report['conditions'])} 个实验点的批量预测；模型：{report['model']}，"
                   f"数据版本：{report['revision']}，模板版本：{report['template_version']}。\n"
                   "表中列出预测均值、中位数与中央 95% 区间；区间未额外叠加未来测量噪声。\n"
                   "所选历史实验仍参与训练，这些是模型预测，不是独立留出验证。本页结果可导出 Excel，或记录到原实验后随项目保留逐条预测。")
        if report["revision"] != current_revision:
            message = "项目已更改：以下结果属于旧数据版本；导出仍保留原预测快照，需要最新结果请重新计算。\n" + message
        notices = report.get("notices", [])
        if notices:
            message += "\n\n提示：\n" + "\n".join(notices)
        self.output.setPlainText(message)
