"""Generate synthetic evidence for prediction capture, backfill and scoring."""
import json
import os
from pathlib import Path
import platform
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from experiment_planner.application.analysis import analyze
from experiment_planner.application.service import PlannerService
from experiment_planner.domain.template import Template
from experiment_planner.io.exchange import export_records
from experiment_planner.io.score_export import prediction_score_report, export_prediction_scores
from experiment_planner.storage.project import Project
from experiment_planner.ui.desktop import PythonWindow
from experiment_planner.ui.prediction_scores import PredictionScoresDialog


def main():
    output=Path("docs/evidence/prediction-scoring-2026-10-27"); output.mkdir(parents=True,exist_ok=True)
    template=Template({"schema_version":2,"template_version":1,"name":"预测回填合成示例（非真实数据）",
        "parameters":[{"name":"x","label":"实验条件 X","bounds":[0.,1.]}],
        "measurements":[{"name":"quality","label":"响应质量","is_response":True,"unit":"1"}],
        "derived_metrics":[{"name":"quality_twice","label":"两倍响应","expression":"quality * 2","unit":"1"}],
        "objectives":[{"metric":"quality","direction":"maximize"}],
        "optimization":{"mode":"single","default_model_preset":"bayesian_linear_v1"},"ratio_policy":{"mode":"remove"}})
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as scratch:
        path=Path(scratch)/"synthetic.sqlite"; project=Project.create(path,"上次预测与回填评分：合成数据",template)
        service=PlannerService(project)
        for x in (0.,.25,.75,1.):
            service.add_record({"x":x},{"quality":{"value":20*x,"uncertainty":{"kind":"std","amount":.5}}})
        eid=service.add_record({"x":.5},{},status="pending")
        report=analyze(project.snapshot(),{"conditions":[{"x":.5}],"model":"bayesian_linear_v1","seed":7,
            "source_experiments":[{"experiment_id":eid,"record_uid":project.experiment(eid)["record_uid"]}]})
        service.save_record_predictions(report); snapshot=project.experiment(eid)["last_prediction"]
        window=PythonWindow(); window.set_project(project); window.go_to(0); window.resize(1280,820); window.show(); app.processEvents()
        window.grab().save(str(output/"before-backfill.png"))
        window.service.revise_record(eid,{"x":.5},{"quality":13.},status="completed"); window.refresh(); app.processEvents()
        assert project.experiment(eid)["last_prediction"]==snapshot
        window.grab().save(str(output/"after-backfill.png"))
        scores=prediction_score_report(project,[eid]); dialog=PredictionScoresDialog(scores,window); dialog.resize(1400,760); dialog.show(); app.processEvents()
        dialog.grab().save(str(output/"score-details.png")); dialog.close()
        export_prediction_scores(scores,output/"synthetic-scores.xlsx"); export_records(project,output/"synthetic-records.xlsx")
        (output/"synthetic-score-report.json").write_text(json.dumps(scores,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        expected=project.experiment(eid); window.close(); app.processEvents()
        with Project(path) as reopened: assert reopened.experiment(eid)==expected
    (output/"environment.json").write_text(json.dumps({"python":platform.python_version(),"platform":platform.platform(),
        "qt_platform":os.environ["QT_QPA_PLATFORM"],"model":"bayesian_linear_v1","seed":7,
        "prediction_frozen_after_backfill":True,"reopen_preserves_score":True,"data":"synthetic only"},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"已保存上次预测 / 回填评分示例：{output}")


if __name__=="__main__": main()
