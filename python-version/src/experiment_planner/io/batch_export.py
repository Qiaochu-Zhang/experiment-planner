"""Export saved recommendations, without refitting or reading edited conditions."""
import json
from pathlib import Path

from experiment_planner.domain.errors import ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.io.prediction_export import prediction_rows, write_sheet


ARRANGEMENTS = {"new": "常规优化", "exploration": "专门探索", "repeat": "复测",
                "cross": "交叉布局", "initialization": "初始化"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def export_batch(project, path, *, batch_id=None):
    """Export a batch snapshot; default to the latest saved batch, including repeats."""
    from openpyxl import Workbook
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise ValidationError("推荐批次导出请选择 Excel (.xlsx)")
    batches = project.batches()
    batch = next((b for b in reversed(batches) if batch_id is None or b["id"] == batch_id), None)
    if not batch or not batch.get("candidates"):
        raise ValidationError("没有可导出的推荐实验，请先计算并保存下一批实验")
    snapshot = batch.get("template_snapshot")
    template = Template(snapshot) if snapshot else project.template
    legacy_ids = []
    if any("experiment_id" not in c for c in batch["candidates"]):
        for event in project.history():
            if event["entity"] == "batch" and event["entity_id"] == str(batch["id"]):
                legacy_ids = json.loads(event["new_payload"]).get("experiment_ids", [])
                break
    fields = {f["name"]: f for f in template.parameters}
    # Include every saved condition, even if an old project's current template differs.
    names = list(dict.fromkeys([*fields, *(n for c in batch["candidates"] for n in c["conditions"])]))
    condition_headers = {}
    for name in names:
        field = fields.get(name, {})
        condition_headers[name] = f"条件：{field.get('label', name)} [{name}] ({field.get('unit', '1')})"
    overview, predictions = [], []
    for index, candidate in enumerate(batch["candidates"], 1):
        prediction = candidate.get("prediction") or {}
        common = {"批次编号": batch["id"], "批内序号": index,
                  "实验编号（推荐时）": candidate.get("experiment_id", legacy_ids[index-1] if index <= len(legacy_ids) else None),
                  "记录唯一标识": candidate.get("record_uid"),
                  "安排": ARRANGEMENTS.get(candidate.get("arrangement"), candidate.get("arrangement", "新实验")),
                  "基准实验编号": candidate.get("baseline_id"), "复测来源编号": candidate.get("repeat_of"),
                  **{heading: candidate["conditions"].get(name) for name, heading in condition_headers.items()}}
        row = {**common, "预测状态": "已有预测" if prediction else "初始化：数据不足，暂无预测" if batch.get("stage") == "initialization" else "暂无预测",
               "计算口径": "含输入执行波动" if "nominal_prediction" in prediction else "输入确定" if prediction else None,
               "预测可行概率": prediction.get("feasibility_probability"),
               "相对基准变化": _json(candidate.get("changes", {}))}
        for detail in prediction_rows(prediction, template):
            predictions.append({**common, **detail})
            # Wide execution sheet: the primary prediction, including transformed objectives.
            if detail["计算口径"] == row["计算口径"]:
                prefix = f"{detail['结果类别']}：{detail['指标名称']} [{detail['指标']}] ({detail['单位']})"
                for key in ("预测均值", "预测中位数50%", "下限2.5%", "上限97.5%", "预测状态", "说明"):
                    row[f"{prefix} / {key}"] = detail[key]
        if not prediction:
            predictions.append({**common, "预测状态": row["预测状态"], "预测均值": None,
                                "预测中位数50%": None, "下限2.5%": None, "上限97.5%": None})
        overview.append(row)
    definitions = [{"内部名称": field["name"], "显示名称": field.get("label", field["name"]),
                    "类别": kind, "单位": field.get("unit", "1"), "类型": field.get("value_type", "float"),
                    "允许下限": (field.get("bounds") or [None, None])[0],
                    "允许上限": (field.get("bounds") or [None, None])[1],
                    "离散值/固定值": _json(field.get("values", field.get("fixed_value"))),
                    "公式": field.get("expression"), "备注": field.get("note", ""),
                    "输入不确定度": _json(field.get("input_uncertainty"))}
                   for kind, group in (("输入条件", template.parameters), ("原始测量", template.measurements),
                                       ("派生指标", template.metrics)) for field in group]
    metadata = [
        ("项目", project.name), ("批次编号", batch["id"]), ("推荐时数据版本", batch.get("revision")),
        ("推荐时模板版本", batch.get("template_version", template.data["template_version"])),
        ("模板说明来源", "推荐时模板快照" if snapshot else "旧批次未保存模板快照，字段说明使用当前模板；条件和预测仍为原批次值"),
        ("阶段", batch.get("stage")), ("模型", batch.get("request", {}).get("model")),
        ("实验数量", len(overview)), ("推荐设置", _json(batch.get("request", {}))),
        ("目标与优化设置", _json({"objectives": template.data.get("objectives"), "optimization": template.data.get("optimization"),
                                  "ratio_policy": template.data.get("ratio_policy")})),
        ("输入不确定度总设置", _json(template.data.get("input_uncertainty"))),
        ("名额说明", batch.get("shortfall")), ("批次提示", "\n".join(batch.get("notices", []))),
        ("区间含义", "下限2.5%和上限97.5%为中央95%预测区间，不是确定的最大/最小值；输入允许范围见字段说明。区间未额外叠加未来测量噪声。"),
        ("预测值", "分别列出后验均值和中位数。原始比值不声明均值存在，均值留空；区间不可用时留空并写明状态，非有限样本警告保留。"),
        ("计算口径", "推荐实验页列出本批次采用的预测；启用输入执行波动时，预测明细同时保留输入确定与含波动的两组结果。目标行包含目标变换后的值，目标定义单独列出。"),
        ("快照说明", "使用推荐时保存的全部条件和预测，不重新训练、不按显示位数取整。包括本批次的复测；后续回填、更正或删除不改变本文件的推荐快照。实验编号可能复用，请结合批次编号和记录唯一标识识别。"),
        ("保存说明", "Excel 导出独立保存；桌面项目仍需点击保存项目或 Ctrl+S，才能在重新打开后继续导出此批次。"),
    ]
    for index, candidate in enumerate(batch["candidates"], 1):
        prediction = candidate.get("prediction") or {}
        if prediction.get("input_uncertainty"):
            metadata.append((f"批内序号{index}输入波动配置与采样", _json(prediction["input_uncertainty"])))
    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        write_sheet(workbook, "推荐实验", overview)
        write_sheet(workbook, "预测明细", predictions)
        write_sheet(workbook, "字段说明", definitions)
        write_sheet(workbook, "批次说明", [{"项目": key, "内容": value} for key, value in metadata])
        workbook.save(path)
    finally:
        workbook.close()
