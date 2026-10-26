"""Model-based permutation sensitivity on the observed experimental domain."""
import math

from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.domain.template import Template


IMPORTANCE_NOTICE = (
    "重要度是当前模型在历史取值范围内的置换敏感度，相对分数合计 100；"
    "不是因果效应、准确率或独立验证结果。数据量、相关条件、先验及模型选择会影响排名。"
)


def analyze_importance(snapshot, request):
    import torch
    from experiment_planner.engine.runtime import configure_offline_runtime
    from experiment_planner.engine.models import fit_models, BernoulliLogit

    configure_offline_runtime()
    template = Template(snapshot["template"])
    seed = request.get("seed", 0)
    repeats = request.get("repeats", 8)
    if type(repeats) is not int or not 2 <= repeats <= 32:
        raise ValidationError("重要度置换次数须为 2–32 的整数")
    usable, unavailable = [], []
    for field in template.responses:
        name = field["name"]
        rows = [e for e in snapshot["experiments"] if e["status"] in ("completed", "partial")
                and (cell := e["derived"].get(name, e["observations"].get(name)))
                and cell.get("value") is not None and cell.get("status", "valid") == "valid"]
        if len(rows) >= 2: usable.append(name)
        else: unavailable.append({"response": name, "count": len(rows), "reason": "有效实测结果不足两条"})
    if not usable:
        raise CapabilityError("重要度分析至少需要同一响应有两条有效的已完成 / 部分结果实验")
    model, encoder, names, datasets, notices = fit_models(
        template, snapshot["experiments"], request.get("model", "gp_rbf_v1"), seed, response_names=usable)
    generator = torch.Generator().manual_seed(seed)
    responses = []
    for index, name in enumerate(names):
        dataset = datasets[name]
        # Bounded analysis cost; model fitting still uses all valid history.
        chosen = torch.randperm(dataset["count"], generator=generator)[:256].tolist()
        conditions = [dataset["conditions"][i] for i in chosen]
        weights = torch.tensor([dataset["data_weighting"]["records"][i]["weight"] for i in chosen], dtype=torch.double)
        projected = model.models[index]

        def centers(points):
            X = encoder.encode(points)
            with torch.no_grad():
                if isinstance(projected.inner, BernoulliLogit):
                    # Median probability of the logit-normal posterior, deterministic.
                    reduced = X[..., projected.indices] if projected.indices else torch.zeros_like(X[..., :1])
                    phi = torch.cat([torch.ones_like(reduced[..., :1]), reduced], -1)
                    return torch.sigmoid(phi @ projected.inner.coefficient_mean).reshape(-1)
                return projected.posterior(X).mean.reshape(-1)

        original = centers(conditions)
        if not torch.isfinite(original).all(): raise CapabilityError(f"{name}：重要度基准预测出现非有限数值")
        rows = []
        for field in template.parameters:
            key = field["name"]
            unique = len({condition[key] for condition in conditions})
            row = {"parameter": key, "label": field.get("label", key), "unique_count": unique,
                   "score": None, "sensitivity": None, "valid_permutations": 0, "changed_permutations": 0}
            if key not in dataset["features"]:
                row["reason"] = "未进入该响应模型（文字、关闭模型输入或无关先验）"
            elif unique < 2:
                row["reason"] = "历史取值没有变化，无法估计"
            else:
                numerator = denominator = 0.
                for _ in range(repeats):
                    permutation = torch.randperm(len(conditions), generator=generator).tolist()
                    points, positions = [], []
                    for i, source in enumerate(permutation):
                        changed = {**conditions[i], key: conditions[source][key]}
                        try: template.validate_conditions(changed, execution=False)
                        except ValidationError: continue
                        points.append(changed); positions.append(i)
                        if changed[key] != conditions[i][key]: row["changed_permutations"] += 1
                    if points:
                        predicted = centers(points)
                        if not torch.isfinite(predicted).all(): raise CapabilityError(f"{name}：{key} 置换预测出现非有限数值")
                        local_weights = weights[positions]
                        numerator += float(((predicted - original[positions]).square() * local_weights).sum())
                        denominator += float(local_weights.sum())
                        row["valid_permutations"] += len(points)
                if denominator > 0 and row["changed_permutations"]:
                    row.update(sensitivity=numerator / denominator, reason="已估计")
                else:
                    row["reason"] = "置换后无合法条件，现有约束下无法估计单独影响"
            rows.append(row)
        total = sum(row["sensitivity"] or 0 for row in rows)
        informative = total > max(1e-20, float(original.square().mean()) * 1e-20)
        for row in rows:
            if row["sensitivity"] is not None:
                if informative: row["score"] = 100. * row["sensitivity"] / total
                else: row["reason"] = "模型变化过小，无法可靠排名"
        responses.append({"response": name, "count": dataset["count"], "analyzed_count": len(conditions),
                          "informative": informative, "parameters": rows,
                          "center": "概率中位数" if isinstance(projected.inner, BernoulliLogit) else "后验均值"})
    informative = [response for response in responses if response["informative"]]
    ranking = []
    for field in template.parameters:
        scores = [next(r for r in response["parameters"] if r["parameter"] == field["name"])["score"] for response in informative]
        score = sum(s or 0 for s in scores) / len(informative) if any(s is not None for s in scores) else None
        if score is not None and not math.isfinite(score): raise CapabilityError("重要度分数非有限")
        ranking.append({"parameter": field["name"], "label": field.get("label", field["name"]), "score": score})
    ranking.sort(key=lambda row: -(row["score"] if row["score"] is not None else -1))
    return {"revision": snapshot["revision"], "template_version": template.data["template_version"],
            "model": request.get("model", "gp_rbf_v1"), "seed": seed, "repeats": repeats,
            "ranking": ranking, "responses": responses, "unavailable_responses": unavailable,
            "model_datasets": datasets, "notices": [IMPORTANCE_NOTICE,
                "综合分数对可排名的基础响应等权平均，不按优化目标权重；只在满足输入约束的置换条件上计算，最多抽取 256 条历史条件。",
                "本分析使用历史实际输入的确定位置，不叠加未来输入执行波动。", *notices]}
