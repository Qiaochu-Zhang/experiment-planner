"""General input, measurement and formula editing for new or copied templates."""
import copy
import json

from PySide6.QtCore import Qt, QEvent, QMimeData
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QApplication)

from experiment_planner.application.template_editing import SECTIONS, check_name, normalize_draft, paste_fields, remove_fields, rename_field
from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import parse_value
from experiment_planner.metrics.formulas import unit_dimension
from experiment_planner.ui.tree_editor import chinese_buttons
from experiment_planner.ui.help import attach_help, HelpFilter
from experiment_planner.ui.interaction import DraftDialog, install_wheel_filter


class FieldDialog(DraftDialog):
    def __init__(self, section, field=None, parent=None):
        super().__init__(parent)
        install_wheel_filter()
        self.section = section
        self.original = copy.deepcopy(field or {})
        self.setWindowTitle("修改字段" if field else "添加字段")
        self.resize(560, 520)
        form = QFormLayout(self)
        self.name = QLineEdit(self.original.get("name", ""))
        self.label = QLineEdit(self.original.get("label", ""))
        self.kind = QComboBox()
        for title, code in (("数值", "float"), ("整数", "int"), ("类别", "category"), ("是否", "bool"), ("文字", "text")):
            if section == "derived_metrics" and code not in ("float", "int"): continue
            self.kind.addItem(title, code)
        self.kind.setCurrentIndex(max(0, self.kind.findData(self.original.get("value_type", "float"))))
        self.unit = QComboBox(); self.unit.setEditable(True); self.unit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.unit.addItems(["1", "s", "°C", "W", "nm", "um", "sccm", "mT", "mTorr"])
        self.unit.setCurrentText(self.original.get("unit", "1"))
        self.note = QLineEdit(self.original.get("note", ""))
        form.addRow("内部名称（英文标识）", self.name); form.addRow("显示名称（可用中文）", self.label)
        form.addRow("类型", self.kind); form.addRow("单位（无量纲用 1）", self.unit)
        form.addRow("字段说明", self.note)
        hint = QLabel("改内部名称会同步更新公式、目标和先验中的引用；显示名称可以自由填写。更多属性在主模板窗口的“全部属性”中编辑。")
        hint.setWordWrap(True); form.addRow(hint)
        self.domain = QComboBox()
        for title, code in (("待填写", None), ("范围", "bounds"), ("离散取值", "values"), ("固定值", "fixed_value"), ("是否（两种值）", "boolean"), ("自由文字", "text")):
            self.domain.addItem(title, code)
        default_domain = "text" if self.kind.currentData() == "text" else "boolean" if self.kind.currentData() == "bool" else None if field else "bounds"
        self.domain.setCurrentIndex(self.domain.findData(next((key for key in ("fixed_value", "values", "bounds") if key in self.original), default_domain)))
        bounds = self.original.get("bounds", ["", ""] if field else [0, 1])
        self.lower = QLineEdit(str(bounds[0])); self.upper = QLineEdit(str(bounds[1]))
        self.values = QLineEdit(", ".join(map(str, self.original.get("values", []))))
        self.fixed = QLineEdit(str(self.original.get("fixed_value", "")))
        self.model_input = QCheckBox("作为模型输入"); self.model_input.setChecked(self.original.get("use_as_model_input", True))
        self.response = QCheckBox("作为响应，可选择为优化目标"); self.response.setChecked(self.original.get("is_response", True))
        self.model_base = QCheckBox("直接建模（公式也可由基础响应推导）"); self.model_base.setChecked(self.original.get("model_base", section != "derived_metrics"))
        self.measured_at = QComboBox()
        for title, code in (("实验后", "after"), ("实验前", "before"), ("未指定", "unknown")): self.measured_at.addItem(title, code)
        self.measured_at.setCurrentIndex(max(0, self.measured_at.findData(self.original.get("measured_at", "after"))))
        self.expression = QLineEdit(self.original.get("expression", ""))
        if section == "parameters":
            form.addRow("取值方式", self.domain); form.addRow("下限", self.lower); form.addRow("上限", self.upper)
            form.addRow("离散值（逗号分隔）", self.values); form.addRow("固定值", self.fixed); form.addRow(self.model_input)
            def sync():
                kind = self.kind.currentData(); mode = self.domain.currentData()
                if kind == "text":
                    self.model_input.setChecked(False); self.model_input.setEnabled(False)
                    if mode in ("bounds", "boolean"): self.domain.setCurrentIndex(self.domain.findData("text")); mode = "text"
                else: self.model_input.setEnabled(True)
                self.domain.setEnabled(True)
                self.lower.setEnabled(mode == "bounds" and kind in ("float", "int")); self.upper.setEnabled(self.lower.isEnabled())
                self.values.setEnabled(mode == "values" and kind != "bool"); self.fixed.setEnabled(mode == "fixed_value")
            self.kind.currentIndexChanged.connect(sync); self.domain.currentIndexChanged.connect(sync); sync()
        else:
            form.addRow(self.response); form.addRow(self.model_base)
            if section == "measurements":
                form.addRow("测量时点", self.measured_at)
                form.addRow("类别值（类别类型填写）", self.values)
            else: form.addRow("计算公式（使用内部名称）", self.expression)
        actions = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        actions.accepted.connect(self.validate_accept); actions.rejected.connect(self.reject); form.addRow(actions)
        for control in (self.name, self.label, self.kind, self.unit, self.note, self.domain,
                        self.lower, self.upper, self.values, self.fixed, self.model_input,
                        self.response, self.model_base, self.measured_at, self.expression):
            key = "derived_metrics" if control is self.expression else "fields" if section == "parameters" else "measurements"
            description = None
            if control is self.unit: description = "单位可直接输入任意名称，例如 kg、mm 或 nm/s；相同自定义单位视为相同量纲，不自动换算。"
            if control is self.model_input: description = "文字输入保存为实验条件，不进入数值模型。自由文字用于推荐时需要基准；也可指定固定值或离散文字。"
            if control is self.model_base: description = "勾选后为这一响应单独拟合模型；不勾选的派生指标由基础响应的预测按公式计算。至少需要一个基础响应。"
            if control is self.note: description = "填写本字段含义；模板字段表的悬停说明会读取这里的文字。"
            attach_help(control, key, description)
            label = form.labelForField(control)
            if label: attach_help(label, key, description)
        self.track_changes(self.form_state, self.validate_accept)

    def form_state(self):
        return tuple(w.text() for w in (self.name, self.label, self.note, self.lower, self.upper, self.values, self.fixed, self.expression)) + (self.kind.currentData(), self.unit.currentText(), self.domain.currentData(), self.model_input.isChecked(), self.response.isChecked(), self.model_base.isChecked(), self.measured_at.currentData())

    def value(self):
        result = copy.deepcopy(self.original)
        name = self.name.text().strip(); check_name(name)
        kind = self.kind.currentData(); unit = self.unit.currentText().strip(); unit_dimension(unit)
        result.update(name=name, label=self.label.text().strip() or name, value_type=kind, unit=unit, note=self.note.text().strip())
        if self.section == "parameters":
            for key in ("bounds", "values", "fixed_value"): result.pop(key, None)
            result["use_as_model_input"] = self.model_input.isChecked()
            mode = self.domain.currentData()
            if mode is None: raise ValidationError("请填写输入参数的取值方式与范围、离散值或固定值")
            if mode == "text":
                if kind != "text": raise ValidationError("自由文字取值方式仅用于文字类型")
            elif kind == "bool" and mode != "fixed_value": result["execution_rounding"] = {"mode": "none"}
            elif mode == "boolean": raise ValidationError("是否取值方式仅用于是否类型，请选择范围、离散取值或固定值")
            elif mode == "bounds":
                if kind in ("category", "text"): raise ValidationError("类别或文字参数请选择离散取值、固定值或自由文字")
                values = [parse_value(w.text().strip(), result) for w in (self.lower, self.upper)]
                if None in values or values[0] >= values[1]: raise ValidationError("范围需填写下限和上限，且下限小于上限")
                result["bounds"] = values
            elif mode == "values":
                values = [v.strip() for v in self.values.text().replace("，", ",").split(",") if v.strip()]
                result["values"] = values
                result["values"] = [parse_value(v, result) for v in values]
                if not values or len(set(result["values"])) != len(values): raise ValidationError("离散值不能为空或重复")
            else:
                text = self.fixed.text().strip()
                if kind == "category": result["values"] = [text]
                result["fixed_value"] = parse_value(text, result)
                result.pop("values", None)
                if result["fixed_value"] is None: raise ValidationError("固定值不能为空")
            if kind in ("category", "bool", "text"):
                result["execution_rounding"] = {"mode": "none"}; result["display_digits"] = None
            if kind == "text": result["use_as_model_input"] = False
        else:
            result.update(is_response=self.response.isChecked(), model_base=self.model_base.isChecked())
            if kind in ("category", "text") and result["is_response"]:
                raise ValidationError("文字和类别测量请取消“作为响应”；它们不能直接作为数值优化目标")
            if self.section == "measurements":
                result["measured_at"] = self.measured_at.currentData()
                if kind == "category":
                    result["values"] = [v.strip() for v in self.values.text().replace("，", ",").split(",") if v.strip()]
                    if not result["values"]: raise ValidationError("类别测量需要填写类别值")
            else:
                result["expression"] = self.expression.text().strip()
                if not result["expression"]: raise ValidationError("派生指标需要填写计算公式")
        return result

    def validate_accept(self):
        try: self.value()
        except ValidationError as exc: QMessageBox.warning(self, "字段需要调整", str(exc)); return
        self.accept()


CLIPBOARD_TYPE = "application/x-experiment-planner-fields"


class FieldTableHelpFilter(HelpFilter):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ToolTip:
            table = watched.parent()
            item = table.itemAt(event.pos())
            watched.setProperty("helpDescription", item.data(Qt.ItemDataRole.UserRole) if item else None)
        return super().eventFilter(watched, event)


class FieldsEditor(DraftDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = normalize_draft(data)
        self.setWindowTitle("参数、测量与公式 · 增删改名")
        self.resize(1100, 680)
        layout = QVBoxLayout(self)
        hint = QLabel("Shift 连选、Ctrl 多选；可批量复制、粘贴到其他区域或删除。跨区域粘贴保留名称、类型、单位和说明，区域专属属性留空待填写。双击一行修改。")
        hint.setWordWrap(True); layout.addWidget(hint)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        self.tables = []
        for title in ("输入参数", "原始测量", "派生指标与公式"):
            widget = QTableWidget(0, 6)
            widget.setHorizontalHeaderLabels(["内部名称", "显示名称", "类型", "单位", "取值 / 公式", "说明"])
            widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            widget.cellDoubleClicked.connect(lambda *_: self.edit_field())
            self.tables.append(widget); self.tabs.addTab(widget, title)
            for sequence, action in ((QKeySequence.StandardKey.Copy, self.copy_selected), (QKeySequence.StandardKey.Paste, self.paste_selected), (QKeySequence(Qt.Key.Key_Delete), self.remove_field)):
                shortcut = QShortcut(sequence, widget); shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut); shortcut.activated.connect(action)
            viewport = widget.viewport(); viewport.setProperty("helpKey", SECTIONS[len(self.tables)-1] if len(self.tables) > 1 else "fields")
            viewport.setToolTip("字段说明")
            handler = FieldTableHelpFilter(widget); viewport.installEventFilter(handler); viewport._help_handler = handler
        row = QHBoxLayout(); layout.addLayout(row)
        for title, action in (("添加字段", self.add_field), ("修改选中字段", self.edit_field), ("复制选中字段", self.copy_selected), ("粘贴字段", self.paste_selected), ("删除选中字段", self.remove_field)):
            b = QPushButton(title); b.clicked.connect(action); row.addWidget(b)
        actions = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel))
        actions.accepted.connect(self.accept); actions.rejected.connect(self.reject); layout.addWidget(actions)
        self.refresh()
        initial = copy.deepcopy(self.data)
        self.track_changes(lambda: self.data, self.accept, lambda: setattr(self, "data", copy.deepcopy(initial)))

    def selected_rows(self):
        return sorted(index.row() for index in self.tables[self.tabs.currentIndex()].selectionModel().selectedRows())

    def copy_selected(self):
        section = SECTIONS[self.tabs.currentIndex()]
        fields = [self.data[section][row] for row in self.selected_rows()]
        if not fields: return
        mime = QMimeData()
        mime.setData(CLIPBOARD_TYPE, json.dumps({"section": section, "fields": fields}, ensure_ascii=False).encode("utf-8"))
        mime.setText("\n".join("\t".join(str(f.get(k, "")) for k in ("name", "label", "value_type", "unit", "note")) for f in fields))
        QApplication.clipboard().setMimeData(mime)

    def paste_selected(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(CLIPBOARD_TYPE): return
        try:
            payload = json.loads(bytes(mime.data(CLIPBOARD_TYPE)))
            if payload["section"] not in SECTIONS or not isinstance(payload["fields"], list): raise ValueError("字段剪贴板格式无效")
            for field in payload["fields"]: check_name(field["name"])
            self.data, added = paste_fields(self.data, payload["section"], payload["fields"], SECTIONS[self.tabs.currentIndex()])
            self.refresh()
            table = self.tables[self.tabs.currentIndex()]
            table.clearSelection()
            from PySide6.QtCore import QItemSelectionModel
            for row in range(table.rowCount() - len(added), table.rowCount()):
                table.selectionModel().select(table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        except (KeyError, TypeError, ValueError) as exc: QMessageBox.warning(self, "无法粘贴", str(exc))

    def refresh(self):
        for section, table in zip(SECTIONS, self.tables):
            table.setRowCount(len(self.data[section]))
            for row, f in enumerate(self.data[section]):
                values = (f['name'], f.get('label', f['name']), f.get('value_type', 'float'), f.get('unit', '1'),
                          f.get('expression', str(f.get('bounds', f.get('values', f.get('fixed_value', '是否' if f.get('value_type') == 'bool' else '自由文字' if f.get('value_type') == 'text' else '待填写'))))), f.get('note', ''))
                description = f"{f.get('label', f['name'])}（{f['name']}），类型：{f.get('value_type', 'float')}，单位：{f.get('unit', '1')}。{f.get('note') or '可双击修改字段说明。'}"
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value)); item.setData(Qt.ItemDataRole.UserRole, description); table.setItem(row, column, item)
            table.resizeColumnsToContents()

    def set_field(self, section, field, old_name=None):
        existing = [f['name'] for s in SECTIONS for f in self.data[s] if f['name'] != old_name]
        check_name(field['name'], existing)
        if old_name:
            self.data = rename_field(self.data, old_name, field['name'])
            index = next(i for i, f in enumerate(self.data[section]) if f['name'] == field['name'])
            # rename_field may also have rewritten this field's own expression.
            field = copy.deepcopy(field)
            if 'expression' in field and old_name != field['name']:
                import re
                field['expression'] = re.sub(r'\b' + re.escape(old_name) + r'\b', field['name'], field['expression'])
            self.data[section][index] = field
        else: self.data[section].append(field)
        if field.get('is_response') and not any(o['metric'] == field['name'] for o in self.data['objectives']):
            self.data['objectives'].append({'metric': field['name'], 'direction': 'maximize', 'transform': 'identity'})
        self.refresh()

    def open_field(self, existing=None):
        section = SECTIONS[self.tabs.currentIndex()]
        dialog = FieldDialog(section, existing, self)
        while dialog.exec():
            try: self.set_field(section, dialog.value(), existing['name'] if existing else None)
            except ValidationError as exc: QMessageBox.warning(self, '字段需要调整', str(exc)); continue
            break

    def add_field(self): self.open_field()

    def edit_field(self):
        index = self.tabs.currentIndex(); rows = self.selected_rows()
        if len(rows) == 1: self.open_field(self.data[SECTIONS[index]][rows[0]])

    def remove_field(self):
        index = self.tabs.currentIndex(); rows = self.selected_rows()
        if not rows: return
        selected = [self.data[SECTIONS[index]][row]['name'] for row in rows]
        changed, removed = remove_fields(self.data, selected)
        box = QMessageBox(self); box.setWindowTitle('删除字段及其引用')
        box.setText('将删除以下字段：' + '、'.join(removed))
        box.setInformativeText('引用这些字段的目标、先验和约束也会移除。请在模板保存前重新检查优化目标和推荐设置。')
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText('删除'); box.button(QMessageBox.StandardButton.Cancel).setText('取消')
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes: self.data = changed; self.refresh()
