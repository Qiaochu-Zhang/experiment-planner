"""Chinese presentation; original diagnostics remain available for debugging."""
import json

from experiment_planner.domain.errors import ValidationError, StaleVersionError


def user_error(error):
    if isinstance(error, (ValidationError, StaleVersionError)):
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
            lines.extend(prediction_lines(c["prediction"], labels))
    if batch.get("shortfall"): lines.append("\n名额说明：" + batch["shortfall"])
    lines += ["\n提示：" + n for n in batch.get("notices", [])]
    return "\n".join(lines)


def prediction_lines(prediction, labels):
    lines = []
    for item in prediction.get("objective_predictions", []):
        name = item["definition"]["metric"]
        q = item.get("quantiles")
        if q:
            lines.append(f"  {labels.get(name, name)}：目标中位数 {q[1]:.5g}，中央 95% 区间 [{q[0]:.5g}, {q[2]:.5g}]")
    lines.append(f"  预测可行概率：{prediction.get('feasibility_probability', 1):.1%}（不是预测准确率）")
    return lines


def analysis_text(report, template):
    labels = {f["name"]: f.get("label", f["name"]) for f in template.fields}
    lines = ["预测区间表示潜在响应，不包含额外的未来量测误差。"]
    for i, prediction in enumerate(report["predictions"], 1):
        lines.append(f"\n条件 {i}")
        for name, item in prediction.items():
            if not isinstance(item, dict) or not item.get("quantiles"): continue
            q = item["quantiles"]
            label = labels.get(name, {"raw_selectivity":"原始刻蚀量比值", "raw_selectivity_abs":"原始比值绝对值", "selectivity_stable":"稳定化比值"}.get(name,name))
            lines.append(f"{label}：中位数 {q[1]:.5g}，中央 95% 区间 [{q[0]:.5g}, {q[2]:.5g}]")
        lines.extend(prediction_lines(prediction, labels))
    lines += ["\n提示：" + n for n in report.get("notices", [])]
    return "\n".join(lines)
