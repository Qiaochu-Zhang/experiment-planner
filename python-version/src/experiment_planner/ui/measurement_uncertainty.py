"""Bulk standard uncertainty editor with a non-mutating preview."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout)

from experiment_planner.application.measurement_uncertainty import plan_standard_uncertainty
from experiment_planner.domain.errors import ValidationError
from experiment_planner.ui.tree_editor import chinese_buttons


class MeasurementUncertaintyDialog(QDialog):
    def __init__(self, template, records, selected_ids=(), parent=None):
        super().__init__(parent)
        self.template, self.records = template, records
        self.selected_ids = set(selected_ids)
        self.setWindowTitle("统一设置误差")
        self.resize(680, 600)
        layout = QVBoxLayout(self)
        intro = QLabel("为已有测量统一填写标准不确定度 1σ。数值越小，模型通常越信任该测量；这里不是准确率百分比。没有测量值的单元格会跳过。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        layout.addLayout(form)
        self.scope = QComboBox()
        if self.selected_ids:
            self.scope.addItem(f"选中的实验（{len(self.selected_ids)} 条）", "selected")
        self.scope.addItem(f"全部实验（{len(records)} 条）", "all")
        form.addRow("应用范围", self.scope)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("输入大于 0 的值，例如 0.5；请根据量测依据或明确的假设填写")
        form.addRow("统一 1σ 值", self.amount)
        layout.addWidget(QLabel("选择原始测量字段（括号内为单位；派生指标自动重新计算）："))
        self.fields = QListWidget()
        for f in template.measurements:
            if f.get("value_type", "float") not in ("float", "int"):
                continue
            item = QListWidgetItem(f"{f.get('label', f['name'])} · {f['name']}（{f.get('unit', '1')}）")
            item.setData(Qt.ItemDataRole.UserRole, f["name"])
            item.setCheckState(Qt.CheckState.Checked)
            self.fields.addItem(item)
        layout.addWidget(self.fields)
        row = QHBoxLayout()
        for label, checked in (("全选字段", True), ("清空选择", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, value=checked: self.select_fields(value))
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.only_unknown = QCheckBox("仅补齐未知误差，保留已有可换算的 1σ")
        self.only_unknown.setToolTip("空误差、含义未指定及无法换算为 1σ 的界限/区间属于未知。未勾选时会替换所选测量原有的误差设置；已有共享来源保留。")
        layout.addWidget(self.only_unknown)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.preview)
        help_text = QLabel("若只有部分实验更可信：先为其他记录设置有依据的基准误差，再选中高可信实验设置较小误差。主观设定应在实验备注中写明，并比较不同取值的预测结果。\n此操作可整体撤销；应用后按 Ctrl+S 保存项目。以后新增/导入的记录需要另行设置。")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.buttons = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.apply_button = self.buttons.addButton("应用设置", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.validate_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.scope.currentIndexChanged.connect(self.update_preview)
        self.amount.textChanged.connect(self.update_preview)
        self.fields.itemChanged.connect(self.update_preview)
        self.only_unknown.toggled.connect(self.update_preview)
        self.update_preview()

    def select_fields(self, checked):
        self.fields.blockSignals(True)
        for i in range(self.fields.count()):
            self.fields.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.fields.blockSignals(False)
        self.update_preview()

    def target_records(self):
        return [r for r in self.records if self.scope.currentData() == "all" or r["id"] in self.selected_ids]

    def values(self):
        try:
            amount = float(self.amount.text())
        except ValueError:
            raise ValidationError("请填写大于 0 的标准不确定度 1σ") from None
        names = [self.fields.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.fields.count())
                 if self.fields.item(i).checkState() == Qt.CheckState.Checked]
        return {"experiment_ids": [r["id"] for r in self.target_records()],
                "measurement_names": names, "amount": amount, "only_unknown": self.only_unknown.isChecked()}

    def update_preview(self, *_):
        self.apply_button.setEnabled(False)
        try:
            values = self.values()
            plan = plan_standard_uncertainty(self.template, self.target_records(), values["measurement_names"],
                                             values["amount"], only_unknown=values["only_unknown"])
            units = sorted({f.get("unit", "1") for f in self.template.measurements if f["name"] in values["measurement_names"]})
            unit_text = "、".join(units)
            text = (f"将修改 {len(plan.changes)} 条实验、{plan.changed_cells} 项测量误差，其中覆盖已知误差 {plan.replaced_known} 项。\n"
                    f"跳过未测 {plan.skipped_missing} 项、保留已知误差 {plan.skipped_known} 项；与新设置相同的项目不重复修改。\n"
                    f"统一数值：{values['amount']:g}；所选字段单位：{unit_text}。")
            if len(units) > 1:
                text += "\n所选单位不同！同一数值分别按各字段单位解释，请确认是否应分开设置。"
            if not plan.changes:
                text += "\n当前没有需要修改的测量。"
            self.preview.setText(text)
            self.apply_button.setEnabled(bool(plan.changes))
        except ValidationError as exc:
            self.preview.setText(str(exc))

    def validate_accept(self):
        self.update_preview()
        if self.apply_button.isEnabled():
            self.accept()
