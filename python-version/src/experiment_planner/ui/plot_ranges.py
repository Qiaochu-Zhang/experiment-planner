"""Per-axis display ranges, independent of the project's model bounds."""
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QWidget

from experiment_planner.domain.errors import ValidationError


class PlotRangesForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.template = None
        self.editors = {}

    def set_template(self, template):
        self.clear()
        self.template = template

    def set_variables(self, text):
        previous = {name: (lo.text(), hi.text()) for name, (lo, hi) in self.editors.items()}
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors = {}
        if self.template is None:
            return
        fields = {p["name"]: p for p in self.template.parameters}
        for name in dict.fromkeys(v.strip() for v in text.split(",") if v.strip()):
            field = fields.get(name)
            if field is None or "bounds" not in field or field.get("value_type", "float") not in ("float", "int"):
                continue  # The analysis validator supplies the actionable error.
            row = QHBoxLayout()
            editors = []
            for index, title in enumerate(("下限", "上限")):
                editor = QLineEdit(previous.get(name, ("", ""))[index])
                editor.setPlaceholderText(str(field["bounds"][index]))
                editor.setAccessibleName(f"{field.get('label', name)}绘图{title}")
                row.addWidget(QLabel(title)); row.addWidget(editor)
                editors.append(editor)
            label = QLabel(f"{field.get('label', name)} ({field.get('unit', '1')})")
            label.setWordWrap(True)
            self.form.addRow(label, row)
            self.editors[name] = tuple(editors)

    def values(self):
        fields = {p["name"]: p for p in self.template.parameters} if self.template else {}
        result = {}
        for name, editors in self.editors.items():
            field = fields[name]
            try:
                result[name] = [float(editor.text().strip()) if editor.text().strip() else field["bounds"][i]
                                for i, editor in enumerate(editors)]
            except ValueError as exc:
                raise ValidationError(f"{field.get('label', name)}：绘图上下限需要数值") from exc
        return result

    def reset(self):
        for editors in self.editors.values():
            for editor in editors:
                editor.clear()

    def clear(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors = {}
        self.template = None
