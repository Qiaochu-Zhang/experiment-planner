"""Opt-in, per-input settings for future execution fluctuations."""
import math

from PySide6.QtWidgets import (QCheckBox, QComboBox, QHeaderView, QLabel, QLineEdit,
                              QTableWidget, QVBoxLayout, QHBoxLayout, QWidget)

from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.input_uncertainty import eligible_input


class InputUncertaintyEditor(QWidget):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        config = data.get("input_uncertainty", {})
        self.enabled = QCheckBox("启用输入不确定度（预测 / 趋势图 / 推荐）")
        self.enabled.setChecked(config.get("enabled", False))
        layout.addWidget(self.enabled)
        hint = QLabel("勾选需要考虑执行波动的输入，按其原单位填写。未勾选的输入按确定值近似。\n"
                      "正态填写标准差 1σ；均匀填写最大偏差 ±a 的半宽 a。未知时请保留关闭，不代填 0。")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["考虑波动", "输入参数 / 单位", "分布与数值含义", "数值", "依据 / 备注"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.rows = {}
        for field in data["parameters"]:
            setting = field.get("input_uncertainty", {})
            selected = QCheckBox(); selected.setChecked(setting.get("enabled", False))
            label = QLabel(f"{field.get('label', field['name'])} ({field.get('unit', '1')})")
            kind = QComboBox()
            kind.addItem("正态：标准差 1σ", "std")
            kind.addItem("均匀：最大偏差半宽 a", "bounds")
            kind.setCurrentIndex(max(0, kind.findData(setting.get("kind", "std"))))
            amount = QLineEdit("" if setting.get("amount") is None else str(setting["amount"]))
            amount.setPlaceholderText("例如 0.5，须大于 0")
            amount.setMaximumWidth(180)
            note = QLineEdit(setting.get("note", "")); note.setPlaceholderText("例如机台复测、校准资料或明确假设")
            allowed = eligible_input(field)
            if not allowed:
                label.setText(label.text() + "（暂不支持）")
                label.setToolTip("仅支持有上下限、参与建模的连续数值输入；整数、离散和固定值暂不支持。")
            row = self.table.rowCount(); self.table.insertRow(row)
            for col, widget in enumerate((selected, label, kind, amount, note)):
                self.table.setCellWidget(row, col, widget)
            self.rows[field["name"]] = (selected, kind, amount, note)

            def sync(*_, selected=selected, widgets=(kind, amount, note), allowed=allowed):
                selected.setEnabled(self.enabled.isChecked())
                # Unsupported imported selections can still be unchecked.
                if not allowed and not selected.isChecked(): selected.setEnabled(False)
                for widget in widgets:
                    widget.setEnabled(self.enabled.isChecked() and selected.isChecked() and allowed)
            self.enabled.toggled.connect(sync); selected.toggled.connect(sync); sync()
        layout.addWidget(self.table, 1)
        options = QHBoxLayout(); layout.addLayout(options)
        options.addWidget(QLabel("每个条件的输入采样数"))
        self.samples = QComboBox()
        for value in (8, 16, 32): self.samples.addItem(str(value), value)
        self.samples.setCurrentIndex(max(0, self.samples.findData(config.get("samples", 16))))
        self.samples.setEnabled(self.enabled.isChecked())
        self.enabled.toggled.connect(self.samples.setEnabled)
        options.addWidget(self.samples); options.addStretch()
        boundary = QLabel("分布假设：各输入原始波动独立，实际执行限制在模板范围和线性约束内。上述数值指截断前分布；"
                          "靠近边界时实际均值和标准差会改变。采样数越大，计算通常越慢。\n"
                          "推荐比较波动后的平均目标；输出约束要求全部采样点通过，属于采样近似。\n"
                          "本设置用于未来执行波动；历史实验仍按记录的实际输入训练，不自动估计或修改输入误差。")
        boundary.setWordWrap(True); layout.addWidget(boundary)

    def apply_to(self, data):
        active = self.enabled.isChecked()
        if active or "input_uncertainty" in data:
            data["input_uncertainty"] = {**data.get("input_uncertainty", {}),
                                         "enabled": active, "samples": self.samples.currentData()}
        for field in data["parameters"]:
            selected, kind, amount, note = self.rows[field["name"]]
            raw = amount.text().strip()
            if not selected.isChecked() and not raw and not note.text().strip() and "input_uncertainty" not in field:
                continue
            try:
                number = float(raw) if raw else None
            except ValueError as error:
                raise ValidationError(f"{field['name']}：输入不确定度应填写数值") from error
            if number is not None and (not math.isfinite(number) or number <= 0):
                raise ValidationError(f"{field['name']}：输入不确定度必须为大于零的有限数值")
            field["input_uncertainty"] = {**field.get("input_uncertainty", {}),
                "enabled": selected.isChecked(), "kind": kind.currentData(), "amount": number,
                "note": note.text().strip()}
