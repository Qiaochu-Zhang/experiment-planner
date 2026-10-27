"""Human-readable tables for persisted predictions and measurement comparisons."""
from pathlib import Path

from experiment_planner.application.prediction_scoring import (
    SCORING_FORMULAS, project_evaluations, summarize_evaluations,
)
from experiment_planner.domain.errors import ValidationError


def prediction_score_report(project, experiment_ids=None):
    with project.transaction():
        entries = project_evaluations(project, experiment_ids)
        return {"project_name": project.name, "revision": project.revision, "entries": entries,
                "summaries": summarize_evaluations([e["evaluation"] for e in entries])}


def prediction_score_tables(report):
    rows, snapshots, conditions = [], [], []
    for entry in report["entries"]:
        record, snapshot = entry["record"], entry["snapshot"]
        snapshot = snapshot or {}
        shared = {"实验编号": record["id"], "记录唯一标识": record.get("record_uid"),
                  "实验批次": record.get("experiment_batch", ""), "预测记录时间": snapshot.get("saved_at"),
                  "模型": snapshot.get("model") or "旧预测未记录模型", "预测数据版本": snapshot.get("revision"),
                  "预测模板版本": (snapshot.get("template_snapshot") or {}).get("template_version"),
                  "预测快照标识": snapshot.get("id")}
        for score in entry["evaluation"]["rows"]:
            rows.append({**shared, "指标": score["metric"], "指标名称": score["label"], "单位": score["unit"],
                         "上次预测中心": score["prediction_center"], "中心类型": score["center_kind"],
                         "上次预测均值": score["prediction_mean"], "上次预测中位数": score["prediction_median"],
                         "上次预测下限2.5%": score["lower95"], "上次预测上限97.5%": score["upper95"],
                         "测量对照值": score["measured"], "有符号误差": score["signed_error"],
                         "绝对误差 AE": score["absolute_error"], "平方误差 SE": score["squared_error"],
                         "区间覆盖": score["covered95"], "区间宽度": score["width95"],
                         "区间得分 IS95（越小越好）": score["interval_score95"], "Brier 概率得分": score["brier_score"],
                         "对照类型": score["comparison_kind"], "状态 / 说明": score["reason"],
                         "评分参照": "将测量结果当作真实结果，直接对照上次保存预测"})
        if not entry["evaluation"]["rows"]:
            rows.append({**shared, "指标": "", "状态 / 说明": "暂无上次预测；先预测并记录，随后回填测量结果"})
        snapshots.append({**shared, "预测来源": snapshot.get("source"), "随机种子": snapshot.get("seed"),
                          "当前记录更新时间": record.get("updated"), "当前数据版本": report["revision"],
                          "预测时已使用本记录训练": snapshot.get("training_includes_record"),
                          "预测时已有测量的字段": "、".join(snapshot.get("known_values", {}))})
        for name, value in snapshot.get("conditions", {}).items():
            conditions.append({"实验编号": record["id"], "预测快照标识": snapshot.get("id"), "输入字段": name,
                               "上次预测条件": value, "当前实际条件": record["actual"].get(name),
                               "条件一致": value == record["actual"].get(name)})
    summaries = []
    for s in report["summaries"]:
        summaries.append({"指标": s["metric"], "指标名称": s["label"], "单位": s["unit"], "模型": s["model"],
                          "有效点误差条数": s["point_count"], "MAE": s["mae"], "RMSE": s["rmse"],
                          "有效区间条数": s["interval_count"], "覆盖率": s["coverage95"], "平均区间宽度": s["mean_width95"],
                          "平均 IS95（越小越好）": s["mean_interval_score95"],
                          "Brier 条数": s["brier_count"], "平均 Brier": s["mean_brier_score"],
                          "预测时已有结果的对照条数": s["known_result_comparisons"]})
    return rows, summaries, snapshots, conditions


def export_prediction_scores(report, path):
    if not report.get("entries"):
        raise ValidationError("没有可导出的实验预测 / 评分记录")
    rows, summaries, snapshots, conditions = prediction_score_tables(report)
    path = Path(path)
    if path.suffix.lower() == ".csv":
        from experiment_planner.io.exchange import write_table
        headers = list(dict.fromkeys(key for row in rows for key in row))
        return write_table(path, headers, rows, "上次预测与评分")
    if path.suffix.lower() != ".xlsx":
        raise ValidationError("预测评分导出请选择 Excel (.xlsx) 或 CSV")
    from openpyxl import Workbook
    from openpyxl.styles import Alignment
    workbook = Workbook(); workbook.remove(workbook.active)
    for title, data in (("评分明细", rows), ("指标汇总", summaries), ("上次预测信息", snapshots), ("预测条件核对", conditions),
                        ("评分公式", [{"项目": label, "公式 / 说明": formula} for label, formula in SCORING_FORMULAS])):
        sheet = workbook.create_sheet(title)
        headers = list(dict.fromkeys(key for row in data for key in row)) or ["说明"]
        sheet.append(headers)
        for row in data: sheet.append([row.get(key) for key in headers])
        for cells in sheet:
            for cell in cells:
                if isinstance(cell.value, str): cell.data_type = "s"
        for cell in sheet[1]: cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 40
        sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    workbook.save(path); workbook.close()
