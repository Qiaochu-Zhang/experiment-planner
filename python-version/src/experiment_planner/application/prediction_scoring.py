"""Frozen per-record predictions and measurement-as-reference scoring."""
import ast
from copy import deepcopy
import json
import math
import uuid


SCORING_FORMULAS = [
    ("对照值", "本功能按用户选择，将当前有效测量结果当作真实结果；派生指标由测量重算。"),
    ("点预测", "优先使用保存的预测均值；均值不可用时使用预测中位数，并明确标注。"),
    ("有符号误差", "e = 预测中心 − 测量值"),
    ("绝对误差 AE", "AE = abs(e)，越小越好。"),
    ("平方误差 SE", "SE = e²，越小越好。"),
    ("区间覆盖", "L ≤ 测量值 ≤ U 时为是，包含端点；L/U 为保存的 2.5%/97.5% 分位数。"),
    ("区间宽度", "W = U − L"),
    ("区间得分 IS95", "IS95 = (U−L) + 40×max(L−y,0) + 40×max(y−U,0)，y 为测量值；越小越好，不是百分制。"),
    ("汇总", "MAE = 平均(AE)；RMSE = √平均(e²)；覆盖率 = 覆盖条数/有效区间评分条数；平均宽度和平均 IS95 分别取有效项平均。"),
    ("是否响应", "Brier = (p−y)²，p 为保存的预测概率、y 为 0/1；不把概率区间当成下一次是否结果的区间。"),
    ("计数", "未测、条件或公式不一致、非有限预测等分别说明，不当作零分；汇总按指标、单位及模型分组，区间与点误差分开计数。"),
    ("口径", "直接评价保存的模型区间，不额外叠加未来测量噪声；其对实测的覆盖率为本次对照结果，不保证为 95%。预测时已有结果的记录标为已有结果对照。"),
]


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def field_spec(data, name):
    fields = {f["name"]: f for section in ("parameters", "measurements", "derived_metrics")
              for f in (data or {}).get(section, [])}
    if name in fields:
        return fields[name]
    policy = (data or {}).get("ratio_policy", {})
    if policy.get("mode") == "stabilized" and name == policy.get("stable_metric_name", "selectivity_stable"):
        original = fields.get(policy.get("original_metric"))
        if original:
            return {**original, "name": name, "label": original.get("label", name) + "（稳定化）", "ratio_policy": policy}
    return None


def definition(data, name, seen=()):
    field = field_spec(data, name)
    if field is None or name in seen:
        return None
    result = {key: field.get(key, default) for key, default in (("value_type", "float"), ("unit", "1"), ("expression", None))}
    if "ratio_policy" in field:
        result["ratio_policy"] = field["ratio_policy"]
    if result["expression"]:
        try:
            names = {node.id for node in ast.walk(ast.parse(result["expression"], mode="eval")) if isinstance(node, ast.Name)}
        except (SyntaxError, TypeError):
            return None
        result["dependencies"] = {n: definition(data, n, (*seen, name)) for n in sorted(names) if field_spec(data, n)}
    return result


def known_results(record):
    return {name: deepcopy(cell.get("value")) for name, cell in {**record.get("observations", {}), **record.get("derived", {})}.items()
            if cell.get("value") is not None and cell.get("status", "valid") == "valid"}


def make_prediction_snapshot(template_data, conditions, prediction, *, model=None, seed=None,
                             revision=None, source="manual", saved_at=None, record_uid=None,
                             known_values=None, training_includes_record=False, snapshot_id=None):
    return {"id": snapshot_id or str(uuid.uuid4()), "conditions": deepcopy(conditions),
            "prediction": deepcopy(prediction), "template_snapshot": deepcopy(template_data),
            "model": model, "seed": seed, "revision": revision, "source": source,
            "saved_at": saved_at, "record_uid": record_uid, "known_values": deepcopy(known_values or {}),
            "training_includes_record": bool(training_includes_record)}


def snapshot_for_record(project, record, batch_cache=None):
    if record.get("last_prediction"):
        return deepcopy(record["last_prediction"])
    if not record.get("prediction"):
        return None
    cache = batch_cache if batch_cache is not None else {}
    bid = record.get("batch_id")
    if bid not in cache:
        row = project.db.execute("SELECT revision,payload FROM batches WHERE id=?", (bid,)).fetchone()
        cache[bid] = {"revision": row[0], **json.loads(row[1])} if row else {}
    batch = cache[bid]
    request = batch.get("request", {})
    return make_prediction_snapshot(batch.get("template_snapshot"),
        record.get("prediction_conditions") or record.get("suggested") or record["actual"], record["prediction"],
        model=request.get("model"), seed=request.get("seed"), revision=batch.get("revision"),
        source="legacy_recommendation", record_uid=record.get("record_uid"),
        snapshot_id=f"legacy:{bid}:{record.get('record_uid', record.get('id'))}")


def evaluate_record(template, record, snapshot):
    """Never fit a model here; all comparison values come from the frozen snapshot."""
    result = {"snapshot_id": snapshot.get("id") if snapshot else None,
              "reference": "measurement_as_truth", "rows": []}
    if not snapshot:
        return result
    old_data = snapshot.get("template_snapshot")
    cells = {**record.get("observations", {}), **record.get("derived", {})}
    conditions_match = snapshot.get("conditions") == record.get("actual")
    prediction = snapshot.get("prediction") or {}
    ordered_names = [f["name"] for section in ("parameters", "measurements", "derived_metrics")
                     for f in (old_data or template.data).get(section, []) if f["name"] in prediction]
    ordered_names += sorted(set(prediction) - set(ordered_names))
    for name in ordered_names:
        item = prediction[name]
        if not isinstance(item, dict) or not ("mean" in item or "quantiles" in item):
            continue
        field = field_spec(old_data, name) or field_spec(template.data, name)
        if field is None:
            continue  # Feasibility / transformed objectives have no recorded measurement.
        boolean = field.get("value_type") == "bool"
        if field.get("value_type") in ("text", "category"):
            continue
        q = item.get("quantiles")
        valid_q = isinstance(q, (list, tuple)) and len(q) == 3 and all(finite(v) for v in q) and q[0] <= q[1] <= q[2]
        mean = item.get("mean") if finite(item.get("mean")) else None
        median = q[1] if valid_q else None
        center = mean if mean is not None else median
        cell = cells.get(name, {})
        measured = cell.get("value")
        if boolean and type(measured) is bool:
            measured = int(measured)
        measured = measured if finite(measured) else None
        row = {"metric": name, "label": field.get("label", name), "unit": field.get("unit", "1"),
               "kind": "boolean" if boolean else "numeric", "model": snapshot.get("model"),
               "prediction_mean": mean, "prediction_median": median, "prediction_center": center,
               "center_kind": "均值" if mean is not None else "中位数" if median is not None else "不可用",
               "lower95": q[0] if valid_q else None, "upper95": q[2] if valid_q else None,
               "measured": measured, "signed_error": None, "absolute_error": None,
               "squared_error": None, "covered95": None, "width95": None, "interval_score95": None,
               "brier_score": None, "status": "unmeasured", "reason": "待补充有效测量值",
               "comparison_kind": "预测时已有结果对照" if name in snapshot.get("known_values", {}) or snapshot.get("training_includes_record") else "事前预测对照"}
        result["rows"].append(row)
        reason = None
        if not conditions_match:
            reason = "实验条件已改变，原预测不适用"
        elif old_data is not None and definition(old_data, name) != definition(template.data, name):
            reason = "字段、单位或公式已改变，不能直接与原预测比较"
        elif old_data is None and name not in {f["name"] for f in template.measurements}:
            reason = "旧预测缺少模板快照，无法核对派生公式"
        elif record.get("status") in ("failed", "cancelled"):
            reason = "实验状态为失败或取消，不纳入评分"
        elif cell.get("status", "valid") != "valid":
            reason = "当前派生或测量结果无效，暂不评分"
        elif measured is None:
            continue
        elif item.get("nonfinite_sample_count", 0):
            reason = "预测含非有限样本，暂不作为完整预测评分"
        elif center is None:
            reason = "原预测中心不可用"
        if reason:
            row.update(status="unavailable", reason=reason)
            continue
        if boolean:
            if measured not in (0, 1) or not 0 <= center <= 1:
                row.update(status="unavailable", reason="是否响应须为 0/1，预测概率须在 0–1 内")
                continue
            row.update(brier_score=(center-measured)**2, status="scored", reason="Brier 概率评分；不对是否读数计算概率区间覆盖")
            continue
        error = center - measured
        row.update(signed_error=error if finite(error) else None,
                   absolute_error=abs(error) if finite(error) else None,
                   squared_error=error*error if finite(error*error) else None)
        if valid_q:
            width = q[2] - q[0]
            score = width + 40 * max(q[0]-measured, 0) + 40 * max(measured-q[2], 0)
            row.update(covered95=q[0] <= measured <= q[2], width95=width if finite(width) else None,
                       interval_score95=score if finite(score) else None)
        row.update(status="scored" if row["absolute_error"] is not None else "unavailable",
                   reason="已按测量值评分" if valid_q else "已计算点误差；原预测 95% 区间不可用")
        if row["absolute_error"] is None:
            row["reason"] = "误差超出数值范围，暂不计分"
    return result


def summarize_evaluations(evaluations):
    groups = {}
    for evaluation in evaluations:
        for row in evaluation.get("rows", []):
            if row["status"] != "scored":
                continue
            key = (row["metric"], row["unit"], row.get("model"), row["kind"])
            groups.setdefault(key, []).append(row)
    def average(values):
        return math.fsum(v / len(values) for v in values) if values else None
    result = []
    for (metric, unit, model, kind), rows in groups.items():
        errors = [r["absolute_error"] for r in rows if r["absolute_error"] is not None]
        intervals = [r for r in rows if r["interval_score95"] is not None and r["width95"] is not None]
        scale = max(errors, default=0)
        rmse = scale * math.sqrt(math.fsum((e/scale)**2 for e in errors) / len(errors)) if scale else 0. if errors else None
        result.append({"metric": metric, "label": rows[0]["label"], "unit": unit, "model": model, "kind": kind,
                       "point_count": len(errors), "interval_count": len(intervals), "mae": average(errors), "rmse": rmse,
                       "coverage95": sum(r["covered95"] for r in intervals)/len(intervals) if intervals else None,
                       "mean_width95": average([r["width95"] for r in intervals]),
                       "mean_interval_score95": average([r["interval_score95"] for r in intervals]),
                       "brier_count": sum(r["brier_score"] is not None for r in rows),
                       "mean_brier_score": average([r["brier_score"] for r in rows if r["brier_score"] is not None]),
                       "known_result_comparisons": sum(r["comparison_kind"] == "预测时已有结果对照" for r in rows)})
    return result


def project_evaluations(project, experiment_ids=None):
    wanted = set(experiment_ids) if experiment_ids is not None else None
    cache, entries = {}, []
    for record in project.experiments():
        if wanted is not None and record["id"] not in wanted:
            continue
        snapshot = snapshot_for_record(project, record, cache)
        entries.append({"record": record, "snapshot": snapshot,
                        "evaluation": evaluate_record(project.template, record, snapshot)})
    return entries
