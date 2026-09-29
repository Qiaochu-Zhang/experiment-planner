"""Typed condition form shared by prediction and cross-layout controls."""
import json

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget

from experiment_planner.domain.template import parse_value
from experiment_planner.ui.help import attach_help, help_label


class ConditionsForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.form=QFormLayout(self);self.editors={};self.template=None

    def set_template(self,template):
        old=self.toPlainText()
        while self.form.rowCount():self.form.removeRow(0)
        self.template=template;self.editors={}
        values=json.loads(old) if old else {}
        for f in template.parameters:
            name=f["name"]
            if f.get("value_type") in ("bool","category") or "values" in f:
                editor=QComboBox()
                for v in f.get("values",[False,True]):editor.addItem("是" if v is True else "否" if v is False else str(v),v)
                if name in values:editor.setCurrentIndex(max(0,editor.findData(values[name])))
            else:
                editor=QLineEdit(str(values.get(name,f.get("fixed_value",""))))
                if "bounds" in f:editor.setPlaceholderText(f"范围 {f['bounds'][0]}–{f['bounds'][1]}")
            editor.setObjectName(name);attach_help(editor,name,f.get("note") or None)
            self.editors[name]=editor
            self.form.addRow(help_label(f"{f.get('label',name)} ({f.get('unit','1')})",name),editor)

    def values(self):
        if not self.template:return {}
        return {f["name"]:parse_value(self.editors[f["name"]].currentData() if isinstance(self.editors[f["name"]],QComboBox) else self.editors[f["name"]].text(),f) for f in self.template.parameters}

    def set_values(self,values):
        for name,value in values.items():
            editor=self.editors.get(name)
            if isinstance(editor,QComboBox):editor.setCurrentIndex(max(0,editor.findData(value)))
            elif editor is not None:editor.setText("" if value is None else str(value))

    def toPlainText(self):
        if not self.editors:return ""
        # Keep raw incomplete user input when rebuilding the form.
        data={name:w.currentData() if isinstance(w,QComboBox) else w.text() for name,w in self.editors.items()}
        try:data=self.values()
        except ValueError:pass
        return json.dumps(data,ensure_ascii=False)

    def setPlainText(self,text):self.set_values(json.loads(text))

    def clear(self):
        while self.form.rowCount():self.form.removeRow(0)
        self.editors={};self.template=None
