"""Batch confidence, observation dates and read-only condition importance."""
from copy import deepcopy

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QDialogButtonBox, QCheckBox, QPushButton, QPlainTextEdit, QMessageBox)

from experiment_planner.domain.reliability import batch_name, confidence_value, experiment_time
from experiment_planner.ui.tree_editor import chinese_buttons


def confidence_editor(value=1.):
    editor = QDoubleSpinBox()
    editor.setDecimals(6); editor.setRange(.000001, 1.); editor.setSingleStep(.1); editor.setValue(value)
    return editor


class ExperimentBatchDialog(QDialog):
    def __init__(self, template, records, selected_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置所选实验批次 / 日期"); self.resize(680, 340)
        self.selected_ids = selected_ids
        layout = QVBoxLayout(self)
        hint = QLabel(f"将 {len(selected_ids)} 条所选实验归入同一批次。批次名称留空可移出自定义批次。\n同名批次共用可信度；调整可信度会影响该批次所有实验及以后加入的实验。")
        hint.setWordWrap(True); layout.addWidget(hint)
        form = QFormLayout(); layout.addLayout(form)
        self.batch = QComboBox(); self.batch.setEditable(True); self.batch.addItem("")
        self.confidences = template.data.get("data_weighting", {}).get("batch_confidence", {})
        names = set(self.confidences) | {e.get("experiment_batch", "") for e in records}
        self.batch.addItems(sorted(n for n in names if n))
        selected_names = {e.get("experiment_batch", "") for e in records if e["id"] in selected_ids}
        if len(selected_names) == 1: self.batch.setCurrentText(next(iter(selected_names)))
        self.confidence = confidence_editor(self.confidences.get(self.batch.currentText(), 1.))
        self.set_confidence = QCheckBox("同时设置该批次可信度（0 < 值 ≤ 1）"); self.set_confidence.setChecked(True)
        self.batch.currentTextChanged.connect(lambda text: self.confidence.setValue(self.confidences.get(text.strip(), 1.)))
        self.date = QLineEdit(); self.date.setPlaceholderText("留空保留原日期；例 2026-10-26 或 2026-10-26T09:00:00+08:00")
        form.addRow("批次名称", self.batch); form.addRow(self.set_confidence, self.confidence); form.addRow("统一实际实验日期（可选）", self.date)
        note = QLabel("可信度是相对训练权重：1 为默认，0.5 降低该批数据影响，不是准确率 50%。可 Ctrl+Z 整批撤销，Ctrl+S 保存项目。")
        note.setWordWrap(True); layout.addWidget(note)
        actions = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        actions.accepted.connect(self.validate_accept); actions.rejected.connect(self.reject); layout.addWidget(actions)

    def values(self):
        name = batch_name(self.batch.currentText())
        return {"experiment_ids": self.selected_ids, "name": name,
                "confidence": confidence_value(self.confidence.value()) if name and self.set_confidence.isChecked() else None,
                "performed_at": experiment_time(self.date.text())}

    def validate_accept(self):
        try: self.values()
        except ValueError as exc:
            QMessageBox.warning(self, "批次设置未保存", str(exc)); return
        self.accept()


class DataWeightingDialog(QDialog):
    def __init__(self, template, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批次可信度 / 近期权重"); self.resize(760, 540)
        self.config = deepcopy(template.data.get("data_weighting", {}))
        layout = QVBoxLayout(self)
        hint = QLabel("默认所有实验权重相同。可信度 1 为基准，较小值降低影响；未设置的批次和未分批实验均为 1。\n近期权重按实际实验日期计算，以每个响应最新的有效实验为参照。半衰期越小，越偏重新实验。")
        hint.setWordWrap(True); layout.addWidget(hint)
        form = QFormLayout(); layout.addLayout(form)
        self.half_life = QDoubleSpinBox(); self.half_life.setRange(0, 1000000); self.half_life.setDecimals(4)
        self.half_life.setSpecialValueText("关闭（所有日期等权）"); self.half_life.setValue(self.config.get("recency_half_life_days", 0))
        self.half_life.setSuffix(" 天"); form.addRow("近期权重半衰期", self.half_life)
        example = QLabel("例如半衰期 30 天：比最新实验早 30 天的时间权重为 0.5，早 60 天为 0.25；再乘以批次可信度。\n日期未知时不衰减并提示补填；旧记录暂以原保存时间近似。权重下限 1e-6。")
        example.setWordWrap(True); layout.addWidget(example)
        names = sorted(set(self.config.get("batch_confidence", {})) | {e.get("experiment_batch", "") for e in records if e.get("experiment_batch")})
        self.table = QTableWidget(len(names), 3); self.table.setHorizontalHeaderLabels(["实验批次", "实验数量", "相对可信度"])
        self.editors = {}
        for i, name in enumerate(names):
            for j, text in enumerate((name, str(sum(e.get("experiment_batch", "") == name for e in records)))):
                item = QTableWidgetItem(text); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(i, j, item)
            editor = confidence_editor(self.config.get("batch_confidence", {}).get(name, 1.))
            self.editors[name] = editor; self.table.setCellWidget(i, 2, editor)
        self.table.resizeColumnsToContents(); layout.addWidget(self.table)
        actions = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        actions.accepted.connect(self.accept); actions.rejected.connect(self.reject); layout.addWidget(actions)

    def values(self):
        return {**self.config, "recency_half_life_days": self.half_life.value(),
                "batch_confidence": {name: editor.value() for name, editor in self.editors.items()}}


class ImportancePanel(QWidget):
    run_requested = Signal()
    cancel_requested = Signal()
    export_requested = Signal()

    def __init__(self):
        super().__init__()
        self.report = None
        layout = QVBoxLayout(self)
        hint = QLabel("根据已完成 / 部分结果实验，按所选模型估算各条件的重要度。使用“下一批实验”的模型及随机种子，应用当前批次可信度和近期权重。\n分数是历史范围内的模型置换敏感度，相对合计 100；不代表因果或准确率。无取值变化的条件显示无法估计。")
        hint.setWordWrap(True); layout.addWidget(hint)
        actions = QHBoxLayout(); layout.addLayout(actions)
        self.run_button = QPushButton("分析实验条件重要度"); self.run_button.clicked.connect(self.run_requested); actions.addWidget(self.run_button)
        self.cancel_button = QPushButton("取消分析"); self.cancel_button.clicked.connect(self.cancel_requested); actions.addWidget(self.cancel_button)
        self.export_button = QPushButton("导出重要度 Excel / CSV"); self.export_button.clicked.connect(self.export_requested); actions.addWidget(self.export_button)
        self.table = QTableWidget(); self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); layout.addWidget(self.table)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True); layout.addWidget(self.output)
        self.set_busy(False)

    def set_busy(self, busy):
        self.run_button.setEnabled(not busy); self.cancel_button.setEnabled(busy)
        self.export_button.setEnabled(not busy and self.report is not None)

    def clear(self):
        self.report = None; self.table.setRowCount(0); self.output.clear(); self.set_busy(False)

    def display_report(self, report, template, revision):
        self.report = deepcopy(report)
        labels = {f["name"]: f.get("label", f["name"]) for f in template.fields}
        headers = ["实验条件", "综合重要度 / 100", *[labels.get(r["response"], r["response"]) + " / 100" for r in report["responses"]], "说明"]
        self.table.setColumnCount(len(headers)); self.table.setHorizontalHeaderLabels(headers); self.table.setRowCount(len(report["ranking"]))
        for i, ranked in enumerate(report["ranking"]):
            details = [next(row for row in response["parameters"] if row["parameter"] == ranked["parameter"]) for response in report["responses"]]
            values = [ranked["label"], "无法估计" if ranked["score"] is None else f"{ranked['score']:.2f}",
                      *["无法估计" if row["score"] is None else f"{row['score']:.2f}" for row in details],
                      "；".join(dict.fromkeys(row["reason"] for row in details))]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(value); self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        lines = [f"数据版本 {report['revision']}；模型 {report['model']}；置换 {report['repeats']} 次。"]
        for r in report["responses"]: lines.append(f"{labels.get(r['response'], r['response'])}：训练 {r['count']} 条，分析 {r['analyzed_count']} 条。")
        for r in report["unavailable_responses"]: lines.append(f"{labels.get(r['response'], r['response'])}：{r['reason']}（{r['count']} 条）。")
        lines.extend(report["notices"]); self.output.setPlainText("\n".join(lines)); self.mark_stale(revision); self.set_busy(False)

    def mark_stale(self, revision):
        if self.report and self.report["revision"] != revision and not self.output.toPlainText().startswith("项目已更改"):
            self.output.setPlainText("项目已更改：以下重要度属于旧数据版本，请重新分析。\n" + self.output.toPlainText())
