"""Chinese presentation; original diagnostics remain available for debugging."""
import json
import math
import traceback

from experiment_planner.precision.rounding import display
from experiment_planner.domain.errors import ValidationError, StaleVersionError, ModelTrainingError


def exception_diagnostic(error):
    """Preserve the exception type, message, traceback and chained causes."""
    if isinstance(error, ModelTrainingError):
        # Put actionable training context before long library stack traces. The
        # TracebackException is a copy; keep the exception's notes intact for CLI.
        trace = traceback.TracebackException.from_exception(error)
        details = "\n".join(trace.__notes__ or [])
        trace.__notes__ = []
        return details + "\n\n原始异常堆栈及原因链：\n" + "".join(trace.format())
    return "".join(traceback.format_exception(error))


def user_error(error):
    if isinstance(error, (ValidationError, StaleVersionError, ModelTrainingError)):
        return str(error)
    if isinstance(error, json.JSONDecodeError):
        return f"配置格式有误：第 {error.lineno} 行、第 {error.colno} 列。请检查逗号、引号及括号。"
    if isinstance(error, PermissionError):
        return "无法写入所选位置。请关闭占用文件的程序，或选择有写入权限的目录。"
    if isinstance(error, FileNotFoundError):
        return "找不到文件，请检查路径或重新选择文件。"
    if isinstance(error, ValueError):
        return "输入格式不正确。请检查数值、实验编号和配置内容。"
    if isinstance(error, OSError):
        return "文件或系统操作未完成。请检查路径、可用空间及文件访问权限。"
    return "计算或操作未完成，请检查当前配置和数据；展开详细信息可查看原始诊断。"


def warning_text(warning):
    text = str(warning.message).lower()
    if "jitter" in text or "positive definite" in text or "p.d." in text:
        return "模型矩阵接近奇异，计算库加入了微小数值稳定项；重复条件或高度相似条件可能触发此提示。"
    if "optimization" in text or "convergence" in text or "optimizer" in text:
        return "模型拟合出现收敛提示，建议检查数据尺度、测量误差或比较其他模型。"
    if "deprecated" in text or "deprecation" in warning.category.__name__.lower():
        return "依赖库提示某个接口将更新；本次计算结果仍按当前版本产生。"
    if "standard" in text or "scale" in text:
        return "计算库提示数据尺度可能影响拟合，请检查输入范围与响应单位。"
    return "计算库产生提示，原始诊断已保留，可通过“技术详情”查看。"


def batch_text(batch, template):
    labels = {f["name"]: f.get("label", f["name"]) for f in template.fields}
    kinds = {"new": "常规优化", "exploration": "专门探索", "repeat": "复测", "cross": "交叉布局", "initialization": "初始化"}
    lines = ["阶段：" + ("模型推荐" if batch["stage"] == "model_driven" else "初始化（数据不足，暂不预测）")]
    req = batch["request"]
    lines.append(f"本轮总名额 {req['n']}；专门探索 {req.get('exploration_count', 0)}；探索强度 {req.get('exploration_strength', 0):g}")
    for i, c in enumerate(batch["candidates"], 1):
        lines.append(f"\n{i}. {kinds.get(c['arrangement'], c['arrangement'])}：" + "，".join(f"{labels.get(k,k)}={v:g}" if isinstance(v,(int,float)) else f"{labels.get(k,k)}={v}" for k,v in c["conditions"].items()))
        if c.get("prediction"):
            lines.extend(prediction_lines(c["prediction"], labels, template))
    if batch.get("shortfall"): lines.append("\n名额说明：" + batch["shortfall"])
    lines += ["\n提示：" + n for n in batch.get("notices", [])]
    return "\n".join(lines)


def formatted(value, name, template):
    field = next((f for f in template.fields if f["name"] == name), {})
    policy = template.data.get("ratio_policy", {})
    if name in ("raw_selectivity", "raw_selectivity_abs", policy.get("stable_metric_name")):
        field = next((f for f in template.fields if f["name"] == policy.get("original_metric")), field)
    digits = field.get("display_digits")
    return display(value, digits) if digits is not None else f"{value:.5g}"


def record_result_text(record, field, template):
    """Render saved recommendation predictions without fitting or inventing measurements."""
    name = field["name"]
    cell = record.get("observations", {}).get(name, record.get("derived", {}).get(name, {}))
    if cell.get("value") is not None:
        return display(cell["value"], field.get("display_digits"))
    last = record.get("last_prediction") or {}
    prediction = last.get("prediction") or record.get("prediction") or {}
    if not prediction or record.get("status") not in ("pending", "running", "partial"):
        return "未测"
    snapshot = last.get("conditions") or record.get("prediction_conditions") or record.get("suggested")
    if snapshot is not None and snapshot != record["actual"]:
        return "未测（条件已改，原预测不适用）"
    if last.get("template_snapshot"):
        from experiment_planner.application.prediction_scoring import definition
        if definition(last["template_snapshot"], name) != definition(template.data, name):
            return "未测（字段或公式已改，原预测不适用）"
    item = prediction.get(name)
    if not isinstance(item, dict): return "未测"
    value, kind = item.get("mean"), "均值"
    if type(value) not in (int, float) or not math.isfinite(value):
        q = item.get("quantiles")
        value = q[1] if isinstance(q, (list, tuple)) and len(q) == 3 else None
        kind = "中位数"
    if type(value) not in (int, float) or not math.isfinite(value):
        return "未测（预测不可用）"
    suffix = "；有限样本" if item.get("nonfinite_sample_count") else ""
    return f"未测（预测{kind} {formatted(value, name, template)}{suffix}）"


def record_score_text(evaluation):
    if not evaluation.get("rows"): return "暂无保存预测"
    parts = []
    for row in evaluation["rows"]:
        if row["status"] != "scored":
            parts.append(f"{row['label']}：{row['reason']}")
        elif row["kind"] == "boolean":
            parts.append(f"{row['label']}：Brier={row['brier_score']:.5g}")
        else:
            text = f"{row['label']}：AE={row['absolute_error']:.5g}"
            if row["interval_score95"] is not None: text += f"，IS95={row['interval_score95']:.5g}"
            parts.append(text)
    return "；".join(parts)


def _interval_lines(item, name, label, template, *, objective=False):
    """An unavailable interval must not prevent other predictions being shown."""
    prefix = f"  {label}：" if objective else f"{label}："
    q = item.get("quantiles")
    notice = item.get("summary_notice", "")
    if q is None:
        lines = [prefix + ("目标预测区间不可用" if objective else "预测区间不可用")]
    elif (not isinstance(q, (list, tuple)) or len(q) != 3
          or any(type(v) not in (int, float) or not math.isfinite(v) for v in q)):
        # Older/cached reports can still contain invalid intervals. Keep their
        # raw content in technical details, but never display it as a prediction.
        lines = [prefix + "预测区间不可用：区间含非有限值或格式错误，请查看技术详情。"]
    else:
        q = [formatted(v, name, template) for v in q]
        median = "目标中位数" if objective else "中位数"
        interval = "有限样本中央 95% 区间" if item.get("nonfinite_sample_count", 0) else "中央 95% 区间"
        lines = [f"{prefix}{median} {q[1]}，{interval} [{q[0]}, {q[2]}]"]
    if notice:
        lines.append(f"  {label}提示：{notice}")
    return lines


def prediction_lines(prediction, labels, template):
    lines = []
    if prediction.get("input_uncertainty"):
        lines.append("  以下目标预测及可行概率已考虑所选输入的执行波动。")
    for item in prediction.get("objective_predictions", []):
        name = item["definition"]["metric"]
        lines.extend(_interval_lines(item, name, labels.get(name, name), template, objective=True))
    lines.append(f"  预测可行概率：{prediction.get('feasibility_probability', 1):.1%}（不是预测准确率）")
    return lines


def analysis_text(report, template):
    labels = {f["name"]: f.get("label", f["name"]) for f in template.fields}
    lines = ["预测区间表示潜在响应，不包含额外的未来量测误差。"]
    for i, prediction in enumerate(report["predictions"], 1):
        lines.append(f"\n条件 {i}")
        variants = [(None, prediction)]
        if "nominal_prediction" in prediction:
            variants = [("输入确定时", prediction["nominal_prediction"]), ("考虑输入执行波动后", prediction)]
        for title, variant in variants:
            if title: lines.append(title + "：")
            for name, item in variant.items():
                if not isinstance(item, dict) or "quantiles" not in item: continue
                label = labels.get(name, {"raw_selectivity":"原始刻蚀量比值", "raw_selectivity_abs":"原始比值绝对值", "selectivity_stable":"稳定化比值"}.get(name,name))
                lines.extend(_interval_lines(item, name, label, template))
            lines.extend(prediction_lines(variant, labels, template))
    lines += ["\n提示：" + n for n in report.get("notices", [])]
    return "\n".join(lines)
