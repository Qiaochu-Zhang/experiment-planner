"""Lossless typed JSON tree: templates can be edited without JSON syntax."""
import copy
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from experiment_planner.domain.errors import ValidationError

TYPES = [("文本", "str"), ("数值", "float"), ("整数", "int"), ("开关", "bool"), ("未设置", "null"), ("属性组", "dict"), ("列表", "list")]
LABELS = {"parameters":"工艺参数", "measurements":"原始测量", "derived_metrics":"派生指标 / 公式", "objectives":"优化目标", "optimization":"优化方式", "ratio_policy":"分母策略", "batch_defaults":"推荐默认设置", "knowledge_priors":"先验关系", "input_constraints":"输入约束", "outcome_constraints":"输出约束", "name":"内部名称", "label":"中文显示名称", "bounds":"范围 [下限，上限]", "expression":"计算公式", "value_type":"数据类型", "unit":"单位", "execution_rounding":"执行精度", "digits":"小数位数", "display_digits":"显示小数位数", "use_as_model_input":"作为模型输入", "is_response":"作为响应", "model_base":"直接建模", "note":"备注", "fixed_value":"固定值", "values":"离散取值", "enabled":"启用", "measured_at":"测量时点", "exploration_strength":"探索强度", "exploration_count":"专门探索名额"}


def chinese_buttons(box):
    for code, text in ((QDialogButtonBox.StandardButton.Save,"保存"), (QDialogButtonBox.StandardButton.Cancel,"取消"), (QDialogButtonBox.StandardButton.Ok,"确定"), (QDialogButtonBox.StandardButton.Close,"关闭")):
        if box.button(code): box.button(code).setText(text)
    return box


class ValueDialog(QDialog):
    def __init__(self, key="", value="", allow_key=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑属性")
        form = QFormLayout(self)
        self.key = QLineEdit(key); self.key.setEnabled(allow_key)
        self.kind = QComboBox()
        for label, code in TYPES: self.kind.addItem(label,code)
        kind = "null" if value is None else type(value).__name__
        self.kind.setCurrentIndex(self.kind.findData(kind))
        self.value = QLineEdit("" if value is None or isinstance(value,(dict,list)) else str(value))
        self.boolean = QComboBox(); self.boolean.addItem("否",False); self.boolean.addItem("是",True)
        self.boolean.setCurrentIndex(int(value is True))
        form.addRow("属性名", self.key); form.addRow("类型", self.kind); form.addRow("值",self.value); form.addRow("开关值",self.boolean)
        hint = QLabel("属性组和列表可在确定后逐项添加。编辑已有容器时保持容器类型，可保留全部子项。")
        hint.setWordWrap(True); form.addRow(hint)
        self.original = copy.deepcopy(value)
        buttons = chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.validate_accept); buttons.rejected.connect(self.reject); form.addRow(buttons)

    def result_value(self):
        kind = self.kind.currentData()
        if kind == "null": return None
        if kind == "bool": return self.boolean.currentData()
        if kind in ("dict","list"):
            cls = dict if kind == "dict" else list
            return copy.deepcopy(self.original) if isinstance(self.original, cls) else cls()
        if kind == "str": return self.value.text()
        try: result = int(self.value.text()) if kind == "int" else float(self.value.text())
        except ValueError as exc: raise ValidationError("请输入合法的整数或数值") from exc
        if not math.isfinite(result): raise ValidationError("数值必须有限")
        return result

    def validate_accept(self):
        try: self.result_value()
        except ValidationError as exc: QMessageBox.warning(self,"输入有误",str(exc)); return
        self.accept()


class JsonTreeEditor(QDialog):
    def __init__(self, data, parent=None, title="完整模板 · 逐项编辑"):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(1000,730)
        layout = QVBoxLayout(self)
        info = QLabel("双击属性修改。选择属性组或列表可添加子项；选择一项可删除。原有未知属性会保留。")
        info.setWordWrap(True); layout.addWidget(info)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["属性", "当前值", "类型"])
        layout.addWidget(self.tree)
        self.fill(self.tree.invisibleRootItem(), "模板", data)
        self.tree.topLevelItem(0).setExpanded(True); self.tree.setColumnWidth(0,430); self.tree.setColumnWidth(1,360)
        self.tree.itemDoubleClicked.connect(lambda item,_: self.edit_item(item))
        actions=QHBoxLayout();layout.addLayout(actions)
        for title, action in (("修改选中项",lambda:self.edit_item(self.tree.currentItem())),("添加属性 / 列表项",self.add_item),("删除选中项",self.remove_item)):
            b=QPushButton(title);b.clicked.connect(action);actions.addWidget(b)
        buttons=chinese_buttons(QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel))
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def fill(self, parent, key, value):
        item=QTreeWidgetItem(parent)
        item.setData(0,Qt.ItemDataRole.UserRole,str(key))
        item.setText(0,f"{LABELS.get(str(key),str(key))}  ({key})" if str(key) in LABELS else str(key))
        kind="null" if value is None else type(value).__name__
        item.setData(2,Qt.ItemDataRole.UserRole,kind)
        item.setText(2,dict((c,l) for l,c in TYPES).get(kind,kind))
        item.setData(1,Qt.ItemDataRole.UserRole,value if kind not in ("dict","list") else None)
        item.setText(1,"未设置" if value is None else ("是" if value is True else "否" if value is False else str(value)) if kind not in ("dict","list") else f"{len(value)} 项")
        if isinstance(value,dict):
            for k,v in value.items():self.fill(item,k,v)
        elif isinstance(value,list):
            for i,v in enumerate(value):self.fill(item,str(i+1),v)
        return item

    def read_item(self,item):
        kind=item.data(2,Qt.ItemDataRole.UserRole)
        if kind=="dict":
            pairs=[(item.child(i).data(0,Qt.ItemDataRole.UserRole),self.read_item(item.child(i))) for i in range(item.childCount())]
            if len({k for k,_ in pairs}) != len(pairs):raise ValidationError("属性名重复，请修改后保存")
            return dict(pairs)
        if kind=="list":return [self.read_item(item.child(i)) for i in range(item.childCount())]
        return item.data(1,Qt.ItemDataRole.UserRole)

    def data(self):return self.read_item(self.tree.topLevelItem(0))

    def edit_item(self,item):
        if item is None or item.parent() is None:return
        parent=item.parent();key=item.data(0,Qt.ItemDataRole.UserRole)
        dialog=ValueDialog(key,self.read_item(item),parent.data(2,Qt.ItemDataRole.UserRole)=="dict",self)
        if dialog.exec():
            index=parent.indexOfChild(item);parent.takeChild(index)
            replacement=self.fill(parent,dialog.key.text(),dialog.result_value())
            parent.takeChild(parent.indexOfChild(replacement));parent.insertChild(index,replacement)

    def add_item(self):
        parent=self.tree.currentItem() or self.tree.topLevelItem(0)
        if parent.data(2,Qt.ItemDataRole.UserRole) not in ("dict","list"):
            parent=parent.parent()
        is_dict=parent.data(2,Qt.ItemDataRole.UserRole)=="dict"
        dialog=ValueDialog("新属性" if is_dict else str(parent.childCount()+1),"",is_dict,self)
        if dialog.exec():self.fill(parent,dialog.key.text(),dialog.result_value());parent.setExpanded(True)

    def remove_item(self):
        item=self.tree.currentItem()
        if item and item.parent():item.parent().takeChild(item.parent().indexOfChild(item))
