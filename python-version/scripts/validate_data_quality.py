"""Create reproducible synthetic examples and offscreen screenshots for the new workflow."""
import json
import os
from pathlib import Path
import platform
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from experiment_planner.application.analysis import analyze
from experiment_planner.application.importance import analyze_importance
from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.io.exchange import export_records, export_importance
from experiment_planner.storage.project import Project
from experiment_planner.ui.data_quality import DataWeightingDialog
from experiment_planner.ui.desktop import PythonWindow


def main():
    output = Path("docs/evidence/data-quality-2026-10-26")
    output.mkdir(parents=True, exist_ok=True)
    template = Template({"schema_version": 2, "template_version": 1, "name": "合成反应实验（非真实数据）",
        "parameters": [{"name": "temperature", "label": "温度", "bounds": [20., 80.], "unit": "°C"},
                       {"name": "duration", "label": "反应时间", "bounds": [10., 100.], "unit": "s"},
                       {"name": "route", "label": "处理路线", "value_type": "category", "values": ["甲", "乙"]}],
        "measurements": [{"name": "quality", "label": "响应质量", "is_response": True}],
        "derived_metrics": [], "objectives": [{"metric": "quality", "direction": "maximize"}],
        "optimization": {"mode": "single", "default_model_preset": "bayesian_linear_v1"},
        "ratio_policy": {"mode": "remove"}})
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as scratch:
        project = Project.create(Path(scratch) / "synthetic.sqlite", "合成数据功能示例", template)
        service = PlannerService(project)
        for temperature in (20., 40., 60., 80.):
            for duration in (20., 80.):
                for route in ("甲", "乙"):
                    service.add_record({"temperature": temperature, "duration": duration, "route": route},
                        {"quality": {"value": .4*temperature+.01*duration+(route == "乙"),
                                     "uncertainty": {"kind": "std", "amount": .5}}},
                        experiment_batch="早期批次" if temperature < 50 else "近期批次",
                        performed_at="2026-01-01" if temperature < 50 else "2026-10-01")
        service.update_template(template.revised(data_weighting={"recency_half_life_days": 180,
                                "batch_confidence": {"早期批次": .6, "近期批次": 1.}}))
        condition = {"temperature": 50., "duration": 60., "route": "乙"}
        prediction = analyze(project.snapshot(), {"conditions": [condition], "model": "bayesian_linear_v1", "seed": 7})
        service.commit_batch({"revision": project.revision, "request": {"n": 1}, "stage": "model_driven",
            "notices": [], "template_version": project.template.data["template_version"],
            "candidates": [{"conditions": condition, "arrangement": "new", "prediction": prediction["predictions"][0]}]})
        report = analyze_importance(project.snapshot(), {"model": "bayesian_linear_v1", "seed": 7})
        export_records(project, output / "synthetic-records.xlsx")
        export_importance(report, project.template, output / "synthetic-importance.xlsx")
        (output / "synthetic-importance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window = PythonWindow(); window.set_project(project); window.resize(1280, 820)
        window.go_to(0); window.show(); window.table.scrollToBottom(); app.processEvents()
        window.grab().save(str(output / "records.png"))
        dialog = DataWeightingDialog(project.template, project.experiments(), window); dialog.show(); app.processEvents()
        dialog.grab().save(str(output / "weighting.png")); dialog.close()
        window.go_to(3); window.prediction_tabs.setCurrentWidget(window.importance)
        window.importance.display_report(report, project.template, report["revision"]); app.processEvents()
        window.grab().save(str(output / "importance.png"))
        original_font = app.font(); large_font = app.font(); large_font.setPointSizeF(original_font.pointSizeF()*1.5); app.setFont(large_font)
        for widget in window.findChildren(QWidget): widget.setFont(large_font)
        window.resize(1024, 650); window.go_to(0); app.processEvents()
        window.table.scrollToBottom()
        window.grab().save(str(output / "records-font150.png"))
        app.setFont(original_font); window.close(); app.processEvents()
    (output / "environment.json").write_text(json.dumps({"python": platform.python_version(),
        "platform": platform.platform(), "qt_platform": os.environ["QT_QPA_PLATFORM"],
        "model": "bayesian_linear_v1", "data": "synthetic only"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存合成示例与界面截图：{output}")


if __name__ == "__main__":
    main()
