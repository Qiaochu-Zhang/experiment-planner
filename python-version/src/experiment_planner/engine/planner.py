from dataclasses import asdict
import importlib.metadata

import torch
from botorch.acquisition.multi_objective.logei import qLogNoisyExpectedHypervolumeImprovement
from botorch.acquisition.logei import qLogNoisyExpectedImprovement
from botorch.sampling.get_sampler import get_sampler

from experiment_planner.domain.errors import CapabilityError, ValidationError
from experiment_planner.domain.template import Template
from experiment_planner.engine.ax_bridge import rebuild, snapshot as ax_snapshot
from experiment_planner.engine.models import fit_models
from experiment_planner.engine.objectives import Objectives, prediction_summary
from experiment_planner.engine.space import BatchRequest, candidate_pool, changes, key
from experiment_planner.knowledge.priors import check_capabilities


def generate(snapshot, request):
    from experiment_planner.engine.runtime import configure_offline_runtime
    configure_offline_runtime()
    template = Template(snapshot["template"])
    records = snapshot["experiments"]
    by_id = {r["id"]: r for r in records}
    if request.baseline_id is not None:
        if request.baseline_id not in by_id: raise ValidationError("基准实验不存在")
        request.baseline = by_id[request.baseline_id]["actual"].copy()
    request.validate(template)
    template.require_ratio_configuration()
    check_capabilities(template, request.model)
    ax_experiment, ax_mapping = rebuild(template, records, snapshot["name"])
    candidates = []
    for rid in request.repeat_ids:
        if rid not in by_id or by_id[rid]["status"] not in ("completed", "partial"):
            raise ValidationError("复测只能选择已有有效实验")
        conditions = by_id[rid]["actual"].copy()
        template.validate_conditions(conditions)
        candidates.append({"conditions": conditions, "arrangement": "repeat", "repeat_of": rid})
    if request.mode == "cross":
        a, b = request.cross_values
        rows = [(False, False)] if request.repeat_baseline else []
        rows += [(True, False), (False, True), (True, True)]
        pending = {key(e["actual"]) for e in records if e["status"] in ("pending", "running")}
        for ca, cb in rows:
            condition = request.baseline.copy()
            if ca: condition[a] = request.cross_values[a]
            if cb: condition[b] = request.cross_values[b]
            template.validate_conditions(condition)
            if key(condition) in pending: raise ValidationError("交叉布局包含现有待做条件，请先完成或取消原计划")
            candidates.append({"conditions": condition, "arrangement": "cross", "cross_members": [n for n, flag in ((a,ca),(b,cb)) if flag]})
        pool = []
    else:
        pool = candidate_pool(template, request, excluded=[r["actual"] for r in records] + [c["conditions"] for c in candidates])
    # Insufficient responses are an initialization state, never synthetic predictions.
    counts = {}
    for response in template.responses:
        name = response["name"]
        counts[name] = sum(1 for r in records if r["status"] in ("completed", "partial") and (cell := r["derived"].get(name, r["observations"].get(name))) is not None and cell.get("value") is not None and cell.get("status", "valid") == "valid")
    initialized = bool(counts) and all(c >= 2 for c in counts.values())
    stage, notices, reference, datasets, fitted = "initialization", ["初始化：基础响应数据不足，预测尚不可用"], None, {}, None
    if initialized:
        model, encoder, names, datasets, notices = fit_models(template, records, request.model, request.seed)
        fitted = model, encoder, names
        stage = "model_driven"
        objectives = Objectives(template, names)
        all_conditions = []
        seen = set()
        for dataset in datasets.values():
            for condition in dataset["conditions"]:
                if key(condition) not in seen: all_conditions.append(condition); seen.add(key(condition))
        baseline = encoder.encode(all_conditions)
        pending_conditions = [r["actual"] for r in records if r["status"] in ("pending", "running")] + [c["conditions"] for c in candidates]
        pending = encoder.encode(pending_conditions) if pending_conditions else None
        with torch.no_grad(), torch.random.fork_rng():
            torch.manual_seed(request.seed)
            sampler = get_sampler(model.posterior(baseline[:1]), torch.Size([32]), seed=request.seed)
            sampled = model.posterior(baseline).rsample(torch.Size([64]))
            transformed = objectives.transformed(sampled)
            if not torch.isfinite(transformed).all(): raise CapabilityError("目标公式产生非有限后验样本；需要配置适用的目标策略")
            config = template.data["optimization"]
            if config["mode"] == "pareto":
                reference = config.get("reference_point")
                if reference is None:
                    means = transformed.mean(0)
                    reference = (means.amin(0) - .1 * (means.amax(0)-means.amin(0)).clamp_min(1)).tolist()
                    notices.append("参考点按有向目标的后验均值最小值减 10% 范围生成，已保存在本批次；最小化目标在有向空间为负值")
                if len(reference) != len(objectives.objectives): raise ValidationError("Pareto 参考点维数不符")
                acquisition = qLogNoisyExpectedHypervolumeImprovement(model=model, ref_point=reference, X_baseline=baseline, sampler=sampler, objective=objectives.botorch_objective(), constraints=objectives.constraints() or None, X_pending=pending, cache_root=False, cache_pending=True)
            elif config["mode"] in ("single", "weighted"):
                acquisition = qLogNoisyExpectedImprovement(model=model, X_baseline=baseline, sampler=sampler, objective=objectives.botorch_objective(), constraints=objectives.constraints() or None, X_pending=pending, cache_root=False)
            else: raise ValidationError("未知优化模式")
            while pool and len(candidates) < request.n:
                X = encoder.encode(pool)
                scores = torch.cat([acquisition(chunk.unsqueeze(-2)).reshape(-1) for chunk in X.split(16)])
                if not torch.isfinite(scores).all(): raise CapabilityError("采集函数返回非有限评分，未保存批次")
                chosen = int(scores.argmax())
                condition = pool.pop(chosen)
                candidates.append({"conditions": condition, "arrangement": "new", "log_acquisition": scores[chosen].item()})
                pending_conditions.append(condition)
                acquisition.set_X_pending(encoder.encode(pending_conditions))
    else:
        for condition in pool[:max(0, request.n-len(candidates))]:
            candidates.append({"conditions": condition, "arrangement": "initialization"})
    if fitted and candidates:
        predictions = prediction_summary(*fitted, template, [c["conditions"] for c in candidates], seed=request.seed)
    else: predictions = [None] * len(candidates)
    for candidate, prediction in zip(candidates, predictions):
        template.validate_conditions(candidate["conditions"])
        candidate["changes"] = changes(template, request.baseline, candidate["conditions"])
        candidate["prediction"] = prediction
        candidate["baseline_id"] = request.baseline_id
    shortfall = None
    if len(candidates) < request.n:
        shortfall = "完整交叉布局已返回；其余配额未自动追加实验" if request.mode == "cross" else "当前合法候选池不足（含冻结、网格、约束与历史去重）；未放宽条件；有限采样不证明全空间无解"
    if request.show_trend_plots: notices.append("本批次保存趋势图请求；当前原型需通过独立分析接口生成切片，尚未自动生成批次图")
    return {"revision": snapshot["revision"], "template_version": template.data["template_version"], "request": asdict(request), "stage": stage, "candidates": candidates, "shortfall": shortfall, "notices": notices, "reference_point": reference, "model_datasets": datasets, "ax_snapshot": ax_snapshot(ax_experiment, ax_mapping), "versions": {p: importlib.metadata.version(p) for p in ("ax-platform", "botorch", "torch")}}
