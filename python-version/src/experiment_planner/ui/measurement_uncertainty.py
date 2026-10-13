"""Bulk measurement uncertainty editor with a non-mutating preview."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QDoubleSpinBox, QWidget, QScrollArea, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView)

from experiment_planner.application.measurement_uncertainty import plan_measurement_uncertainty, raw_measurement_names
from experiment_planner.domain.errors import ValidationError
from experiment_planner.metrics.uncertainty import Uncertainty
from experiment_planner.ui.tree_editor import chinese_buttons


class MeasurementUncertaintyDialog(QDialog):
    def __init__(self, template, records, selected_ids=(), parent=None):
        super().__init__(parent)
        self.template, self.records = template, records
        self.selected_ids = set(selected_ids)
        self.setWindowTitle("统一设置误差")
        self.resize(840, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        intro = QLabel("为已有测量统一填写标准不确定度 1σ 或对称误差界限 ±a。数值不是准确率百分比；没有测量值的单元格会跳过。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        layout.addLayout(form)
        self.mode = QComboBox()
        self.mode.addItem("统一数值", "uniform")
        self.mode.addItem("基准误差 + 高可信实验（一次应用）", "relative")
        form.addRow("设置方式", self.mode)
        self.scope = QComboBox()
        if self.selected_ids:
            self.scope.addItem(f"选中的实验（{len(self.selected_ids)} 条）", "selected")
        self.scope.addItem(f"全部实验（{len(records)} 条）", "all")
        form.addRow("应用范围", self.scope)
        self.kind = QComboBox()
        self.kind.addItem("标准不确定度 1σ（标准差）", "std")
        self.kind.addItem("误差界限 ±a（区间内均匀分布假设）", "bounds")
        form.addRow("误差含义", self.kind)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("输入大于 0 的值，例如 0.5；请根据量测依据或明确的假设填写")
        self.amount_label = QLabel("统一 1σ 值")
        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount)
        self.read_current = QPushButton("读取已有共同 1σ")
        self.read_current.setToolTip("从当前范围和所选字段读取已有的共同 1σ；没有共同值时不自动猜测。")
        self.read_current.clicked.connect(self.load_current_amount)
        amount_row.addWidget(self.read_current)
        form.addRow(self.amount_label, amount_row)
        self.kind_hint = QLabel()
        self.kind_hint.setWordWrap(True)
        layout.addWidget(self.kind_hint)
        self.read_feedback = QLabel()
        self.read_feedback.setWordWrap(True)
        self.read_feedback.setVisible(False)
        layout.addWidget(self.read_feedback)
        self.quick_fields = QComboBox()
        self.quick_fields.addItem("按响应或单位快速选择字段…", None)
        for response in [*template.responses, *template.metrics]:
            names = raw_measurement_names(template, response["name"])
            if names and self.quick_fields.findData(sorted(names)) < 0:
                self.quick_fields.addItem(f"{response.get('label', response['name'])} 所需测量（{len(names)} 项）", sorted(names))
        units = sorted({f.get("unit", "1") for f in template.measurements if f.get("value_type", "float") in ("float", "int")})
        for unit in units:
            names = [f["name"] for f in template.measurements if f.get("unit", "1") == unit and f.get("value_type", "float") in ("float", "int")]
            self.quick_fields.addItem(f"单位 {unit} 的全部数值测量", names)
        form.addRow("快速选字段", self.quick_fields)
        selections = QHBoxLayout()
        layout.addLayout(selections)
        field_panel = QWidget()
        field_layout = QVBoxLayout(field_panel)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_label = QLabel("原始测量字段（括号内为单位）：")
        field_label.setWordWrap(True)
        field_layout.addWidget(field_label)
        self.fields = QListWidget()
        self.fields.setMinimumHeight(100)
        self.fields.setMaximumHeight(150)
        for f in template.measurements:
            if f.get("value_type", "float") not in ("float", "int"):
                continue
            item = QListWidgetItem(f"{f.get('label', f['name'])}（{f.get('unit', '1')}）")
            item.setToolTip(f["name"])
            item.setData(Qt.ItemDataRole.UserRole, f["name"])
            item.setCheckState(Qt.CheckState.Checked)
            self.fields.addItem(item)
        field_layout.addWidget(self.fields)
        row = QHBoxLayout()
        for label, checked in (("全选字段", True), ("清空选择", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, value=checked: self.select_fields(value))
            row.addWidget(button)
        row.addStretch()
        field_layout.addLayout(row)
        selections.addWidget(field_panel, 1)
        self.trusted_panel = QWidget()
        trusted_layout = QVBoxLayout(self.trusted_panel)
        trusted_layout.setContentsMargins(0, 0, 0, 0)
        trusted_label = QLabel("高可信实验（主表所选行已勾选，可调整）：")
        trusted_label.setWordWrap(True)
        trusted_layout.addWidget(trusted_label)
        self.trusted_records = QListWidget()
        self.trusted_records.setMinimumHeight(90)
        self.trusted_records.setMaximumHeight(130)
        statuses = {"completed": "完成", "partial": "部分结果", "pending": "待做", "running": "进行中", "failed": "失败", "cancelled": "取消"}
        for record in records:
            label = f"实验 {record['id']} · {statuses.get(record['status'], record['status'])}"
            if record.get("note"):
                label += " · " + record["note"].replace("\n", " ")[:60]
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            item.setCheckState(Qt.CheckState.Checked if record["id"] in self.selected_ids else Qt.CheckState.Unchecked)
            self.trusted_records.addItem(item)
        trusted_layout.addWidget(self.trusted_records)
        factor_row = QHBoxLayout()
        self.factor_label = QLabel("高可信 1σ = 基准 1σ ×")
        factor_row.addWidget(self.factor_label)
        self.factor = QDoubleSpinBox()
        self.factor.setDecimals(3)
        self.factor.setRange(.001, .999)
        self.factor.setSingleStep(.1)
        self.factor.setValue(.5)
        self.factor.setToolTip("高可信 1σ 与基准 1σ 的比值；0.5 表示误差减半，不表示准确率 50%。")
        factor_row.addWidget(self.factor)
        factor_row.addStretch()
        trusted_layout.addLayout(factor_row)
        self.trusted_hint = QLabel()
        self.trusted_hint.setWordWrap(True)
        trusted_layout.addWidget(self.trusted_hint)
        self.trusted_panel.setVisible(False)
        selections.addWidget(self.trusted_panel, 1)
        self.only_unknown = QCheckBox("仅补齐未知误差，保留已有可换算的 1σ")
        self.only_unknown.setToolTip("空误差、含义未指定及无法换算为 1σ 的界限/区间属于未知。未勾选时会替换所选测量原有的误差设置；已有共享来源保留。")
        layout.addWidget(self.only_unknown)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("可选：如设备已校准、复测更稳定；会附加到实际改动的测量备注")
        reason_form = QFormLayout()
        reason_form.addRow("设置依据", self.reason)
        layout.addLayout(reason_form)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.preview)
        self.show_details = QCheckBox("展开逐项修改预览")
        layout.addWidget(self.show_details)
        self.details = QTableWidget(0, 6)
        self.details.setHorizontalHeaderLabels(["实验", "测量", "单位", "原 1σ", "新 1σ", "设置"])
        self.details.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.details.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.details.setMinimumHeight(100)
        self.details.setMaximumHeight(170)
        self.details.setVisible(False)
        self.show_details.toggled.connect(self.details.setVisible)
        layout.addWidget(self.details)
        help_text = QLabel("比例只是建模假设，不是实际准确率。基准请按量测依据填写；可比较不同取值的预测。基准模式自动将本次假设写入测量备注。\n应用后按 Ctrl+S 保存项目；Ctrl+Z 可整批撤销。以后新增/导入的记录需另行设置。")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.buttons = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel))
        self.apply_button = self.buttons.addButton("应用设置", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.validate_accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.kind.currentIndexChanged.connect(self.change_kind)
        self.quick_fields.activated.connect(self.choose_related_fields)
        self.scope.currentIndexChanged.connect(self.update_preview)
        self.amount.textChanged.connect(self.update_preview)
        self.fields.itemChanged.connect(self.update_preview)
        self.only_unknown.toggled.connect(self.update_preview)
        self.factor.valueChanged.connect(self.update_preview)
        self.trusted_records.itemChanged.connect(self.update_preview)
        self.reason.textChanged.connect(self.update_preview)
        self.change_kind()

    def change_mode(self):
        relative = self.mode.currentData() == "relative"
        self.trusted_panel.setVisible(relative)
        self.scope.setEnabled(not relative)
        self.only_unknown.setText("其他实验仅补齐未知误差，保留已有 1σ" if relative else "仅补齐未知误差，保留已有可换算的 1σ")
        self.only_unknown.setToolTip("高可信实验会改为基准 × 比例；已有 1σ 更小或相等时保留。此选项只控制其他实验。" if relative else "只补齐无法换算为标准不确定度的误差；已有共享来源保留。")
        if relative:
            self.scope.setCurrentIndex(self.scope.findData("all"))
            self.only_unknown.setChecked(True)
        self.change_kind()

    def change_kind(self):
        bounds = self.kind.currentData() == "bounds"
        prefix = "基准" if self.mode.currentData() == "relative" else "统一"
        self.amount_label.setText(prefix + ("界限半宽 a" if bounds else " 1σ 值"))
        self.read_current.setText("读取已有共同界限" if bounds else "读取已有共同 1σ")
        self.read_current.setToolTip("只读取已保存的对称界限；不会从标准差反推最大误差。" if bounds else
                                    "从当前范围和所选字段读取已有的共同 1σ；没有共同值时不自动猜测。")
        self.read_feedback.setVisible(False)
        self.factor_label.setText("高可信界限 a = 基准界限 a ×" if bounds else "高可信 1σ = 基准 1σ ×")
        self.factor.setToolTip("高可信与基准采用同一种误差含义；0.5 表示数值减半，不表示准确率 50%。")
        self.kind_hint.setText(
            "填写正数 a：例如误差界限 ±2 nm 填 2，完整区间宽度为 4 nm。采用区间内均匀分布假设，换算 1σ=a/√3。"
            "GP 使用换算方差，不保证预测落在测量值 ±a 内。切换类型会按新含义解释当前数值。" if bounds else
            "1σ 表示标准不确定度，不是最大绝对误差或 95% 区间。切换类型会按新含义解释当前数值，不自动换算。")
        self.details.setHorizontalHeaderLabels(["实验", "测量", "单位", "原误差设置" if bounds else "原 1σ",
                                                "新误差设置" if bounds else "新 1σ", "设置"])
        self.update_preview()

    def choose_related_fields(self, index):
        names = self.quick_fields.itemData(index)
        if names is None:
            return
        self.fields.blockSignals(True)
        for i in range(self.fields.count()):
            item = self.fields.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in names else Qt.CheckState.Unchecked)
        self.fields.blockSignals(False)
        self.update_preview()

    def field_names(self):
        return [self.fields.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.fields.count())
                if self.fields.item(i).checkState() == Qt.CheckState.Checked]

    def load_current_amount(self):
        names = self.field_names()
        known = set()
        for record in self.target_records():
            for name in names:
                cell = record["observations"].get(name, {})
                if cell.get("value") is not None:
                    uncertainty = Uncertainty(**(cell.get("uncertainty") or {}))
                    value = (uncertainty.amount if uncertainty.kind == "bounds" else None) if self.kind.currentData() == "bounds" else uncertainty.standard()
                    if value is not None:
                        known.add(value)
        units = {f.get("unit", "1") for f in self.template.measurements if f["name"] in names}
        if len(known) == 1 and len(units) == 1:
            self.read_feedback.setVisible(False)
            self.amount.setText(str(next(iter(known))))
        else:
            label = "对称误差界限 a（不会由 1σ 反推）" if self.kind.currentData() == "bounds" else "1σ"
            self.read_feedback.setText(f"所选范围没有唯一的已有 {label}，或单位不同；请缩小字段/实验范围，或手动填写基准。")
            self.read_feedback.setVisible(True)

    def select_fields(self, checked):
        self.fields.blockSignals(True)
        for i in range(self.fields.count()):
            self.fields.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.fields.blockSignals(False)
        self.update_preview()

    def target_records(self):
        return [r for r in self.records if self.mode.currentData() == "relative" or self.scope.currentData() == "all" or r["id"] in self.selected_ids]

    def values(self):
        try:
            amount = float(self.amount.text())
        except ValueError:
            label = "误差界限半宽 a" if self.kind.currentData() == "bounds" else "标准不确定度 1σ"
            raise ValidationError(f"请填写大于 0 的{label}") from None
        names = self.field_names()
        relative = self.mode.currentData() == "relative"
        trusted = [self.trusted_records.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.trusted_records.count())
                   if self.trusted_records.item(i).checkState() == Qt.CheckState.Checked] if relative else []
        return {"experiment_ids": [r["id"] for r in self.target_records()],
                "measurement_names": names, "amount": amount, "only_unknown": self.only_unknown.isChecked(),
                "trusted_experiment_ids": trusted, "trusted_factor": self.factor.value() if relative else None,
                "reason": self.reason.text(), "kind": self.kind.currentData()}

    def update_preview(self, *_):
        self.apply_button.setEnabled(False)
        self.details.setRowCount(0)
        self.trusted_hint.setText("高可信实验已有误差更小或相等时保留；请先输入基准。")
        try:
            values = self.values()
            plan = plan_measurement_uncertainty(self.template, self.target_records(), values["measurement_names"],
                                             values["amount"], kind=values["kind"], only_unknown=values["only_unknown"],
                                             trusted_experiment_ids=values["trusted_experiment_ids"],
                                             trusted_factor=values["trusted_factor"], reason=values["reason"])
            units = sorted({f.get("unit", "1") for f in self.template.measurements if f["name"] in values["measurement_names"]})
            unit_text = "、".join(units)
            text = (f"将修改 {len(plan.changes)} 条实验、{plan.changed_cells} 项测量误差，其中覆盖已知误差 {plan.replaced_known} 项。\n"
                    f"跳过未测 {plan.skipped_missing} 项、保留已知误差 {plan.skipped_known} 项；与新设置相同的项目不重复修改。\n"
                    f"{'基准值' if values['trusted_factor'] is not None else '统一数值'}：{values['amount']:g}；所选字段单位：{unit_text}。")
            if values["kind"] == "bounds":
                standard = Uncertainty("bounds", values["amount"], distribution="uniform").standard()
                text += f"\n误差界限 ±{values['amount']:g}；均匀分布假设下换算 1σ≈{standard:.6g}。"
            if len(units) > 1:
                text += "\n所选单位不同！同一数值分别按各字段单位解释，请确认是否应分开设置。"
            if values["trusted_factor"] is not None:
                label = "界限 a" if values["kind"] == "bounds" else "1σ"
                self.trusted_hint.setText(f"高可信 {label} = {values['amount']:g} × {values['trusted_factor']:g} = {values['amount'] * values['trusted_factor']:g}（{unit_text}）。按换算 1σ 比较，已有误差更小或相等时保留；保留项不改成新类型。")
                text += f"\n已选高可信实验 {len(values['trusted_experiment_ids'])} 条；可展开逐项预览，假设与依据附加到测量备注。"
            fields = {f["name"]: f for f in self.template.measurements}
            self.details.setRowCount(min(200, len(plan.details)))
            for row, detail in enumerate(plan.details[:200]):
                field = fields[detail["measurement"]]
                before = "未知" if detail["before"] is None else f"{detail['before']:g}"
                after = f"{detail['after']:g}"
                if values["kind"] == "bounds":
                    previous = detail["before_setting"]
                    if previous["kind"] == "bounds" and previous["amount"] is not None:
                        before = f"±{previous['amount']:g}（界限；1σ {before}）"
                    elif detail["before"] is not None:
                        before = f"1σ={before}"
                    after = f"±{detail['after_setting']['amount']:g}（界限；1σ≈{detail['after']:.6g}）"
                items = [str(detail["experiment_id"]), field.get("label", field["name"]), field.get("unit", "1"),
                         before, after, detail["role"]]
                for col, value in enumerate(items):
                    item = QTableWidgetItem(value)
                    item.setToolTip(detail["note"] or field["name"])
                    self.details.setItem(row, col, item)
            if len(plan.details) > 200:
                text += f"\n表格显示前 200 项；应用将修改全部 {len(plan.details)} 项。"
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
