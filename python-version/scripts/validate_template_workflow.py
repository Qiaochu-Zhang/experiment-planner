"""Reproduce Excel definition examples and offscreen template screenshots."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from experiment_planner.application.template_editing import blank_template
from experiment_planner.domain.template import Template
from experiment_planner.io.template_excel import write_template_excel
from experiment_planner.storage.project import Project
from experiment_planner.storage.session import ProjectSession
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.field_editor import FieldDialog, FieldsEditor
from experiment_planner.ui.template_editor import TemplateEditor
from experiment_planner.ui.interaction import remove_wheel_filter


def main():
    examples = ROOT / "examples/template_definitions"
    evidence = ROOT / "docs/evidence/v0.4.0"
    examples.mkdir(parents=True, exist_ok=True); evidence.mkdir(parents=True, exist_ok=True)
    data = blank_template()
    data.update(name="自定义模板定义示例", parameters=[
        {"name": "speed", "label": "速度设定", "value_type": "float", "unit": "1", "bounds": [0, 10], "use_as_model_input": True, "execution_rounding": {"mode": "none"}, "note": "示例输入，可替换为自己的实验参数"},
        {"name": "sample", "label": "样品标记", "value_type": "text", "unit": "1", "values": ["样品甲", "样品乙"], "use_as_model_input": False, "note": "文字条件只保存，不参与数值模型"}],
        measurements=[{"name": "quality", "label": "测量结果", "value_type": "float", "unit": "kg", "is_response": True, "model_base": True, "measured_at": "after", "note": "自定义单位示例"}],
        derived_metrics=[{"name": "double_quality", "label": "测量结果的两倍", "value_type": "float", "unit": "kg", "expression": "quality * 2", "is_response": True, "model_base": False}],
        objectives=[{"metric": "double_quality", "direction": "maximize", "transform": "identity"}])
    template = Template(data)
    write_template_excel(blank_template(), examples / "空白模板定义.xlsx")
    template.write(examples / "模板定义示例.xlsx")
    restored = Template.read(examples / "模板定义示例.xlsx")
    assert restored.graph.evaluate({"quality": 3})["double_quality"].value == 6
    app = QApplication([])
    window = PythonWindow()
    editor = TemplateEditor(template); editor.show(); app.processEvents()
    editor.grab().save(str(evidence / "precision.png")); editor.close()
    fields = FieldsEditor(data); fields.show(); app.processEvents()
    fields.grab().save(str(evidence / "fields.png")); fields.close()
    field = FieldDialog("parameters", data["parameters"][1]); field.show(); app.processEvents()
    field.grab().save(str(evidence / "text-field.png")); field.close()
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "示例.sqlite"
        with Project.create(target, "保存示例", template): pass
        window.set_project(ProjectSession(target))
        window.service.add_record({"speed": 2, "sample": "样品甲"}, {"quality": 5})
        window.refresh(); window.show(); app.processEvents()
        window.grab().save(str(evidence / "save-project.png"))
        def capture_prompt():
            prompt = QApplication.activeModalWidget()
            assert isinstance(prompt, QMessageBox)
            prompt.grab().save(str(evidence / "save-prompt.png"))
            prompt.button(QMessageBox.StandardButton.Discard).click()
        QTimer.singleShot(0, capture_prompt); window.close()
        with Project(target) as disk: assert disk.experiments() == []
    app.clipboard().clear()
    for widget in app.topLevelWidgets(): widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    remove_wheel_filter()
    (evidence / "artifact-check.json").write_text(json.dumps({"python": sys.version, "excel_roundtrip": "passed", "discard_keeps_original_file": "passed", "screenshots": ["precision.png", "fields.png", "text-field.png", "save-project.png", "save-prompt.png"]}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
